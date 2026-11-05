"""User-session daemon and private local control socket.

Starting the daemon alone never enables a mouse. Each enable is explicit; the
GUI can exit while this process keeps serving profiles and cancellable actions.
"""

import asyncio
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import struct
import time

from .device_session import DeviceSession
from .devices import discover
from .emergency import EmergencyShortcut
from .focus import HyprlandWatcher, ProfileCoordinator
from .hardware import journal_directory
from .model import MODELS


def socket_path():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'gillete/control.sock'


class Daemon:
    def __init__(self, store):
        self.store = store
        self.coordinator = ProfileCoordinator(store.read())
        self.focus = HyprlandWatcher(self.coordinator)
        self.emergency = EmergencyShortcut(self.focus)
        self.requested = set()
        self.sessions = {}
        self.tasks = {}
        self.errors = {}
        self.retry_at = {}
        self.suspended = False
        self.sleep_monitor_ready = False
        self.shutdown = asyncio.Event()
        self.config_error = ''

    def validate_config(self, config):
        for session in self.sessions.values():
            session.validate_profiles(config)

    async def pin(self, model, identifier):
        config = self.store.read()
        if identifier == 'automatic':
            config.pinned.pop(model, None)
        else:
            if identifier not in config.profiles:
                raise ValueError('Unknown profile')
            config.pinned[model] = identifier
        self.validate_config(config)
        self.store.save(config, expected_revision=config.revision)
        await self.coordinator.reload(config)

    def status(self):
        return {'running': True, 'focus_available': self.coordinator.available,
                'focus': asdict(self.coordinator.window), 'focus_error': self.focus.last_error,
                'suspended': self.suspended, 'suspend_monitor': self.sleep_monitor_ready,
                'emergency_shortcut': self.emergency.label if self.emergency.installed else None,
                'configuration_error': self.config_error,
                'devices': {model: {'requested': model in self.requested,
                                    'active': bool(self.sessions.get(model) and self.sessions[model].ready),
                                    'profile': self.sessions[model].engine.profile.id if self.sessions.get(model) and self.sessions[model].engine else None,
                                    'error': self.errors.get(model, ''),
                                    'active_macros': sum(not job.done() for job in self.sessions[model].engine.macros.jobs.values()) if self.sessions.get(model) and self.sessions[model].engine else 0,
                                    'mode': 'pinned' if model in self.coordinator.config.pinned else 'automatic'} for model in MODELS}}

    async def command(self, data):
        if not isinstance(data, dict) or set(data) - {'command', 'model', 'profile'}:
            raise ValueError('Invalid service request')
        command, model = data.get('command'), data.get('model')
        if command == 'status':
            return self.status()
        if command in {'enable', 'disable', 'pin'} and model not in MODELS:
            raise ValueError('Unknown mouse model')
        if command == 'enable':
            if not self.sleep_monitor_ready or not self.coordinator.available:
                raise ValueError('Focus and suspend monitoring must be available before enabling a mouse')
            await self.emergency.install()
            self.requested.add(model)
            self.errors.pop(model, None)
            self.retry_at[model] = 0
        elif command == 'disable':
            self.requested.discard(model)
            if model in self.sessions:
                self.sessions[model].stop_requested.set()
                await self.tasks[model]
        elif command == 'pin':
            await self.pin(model, data.get('profile'))
        elif command == 'stop-actions':
            async with self.coordinator.lock:
                for engine in self.coordinator.engines.values():
                    await engine.cancel(preserve_pointer=False)
        elif command == 'shutdown':
            self.shutdown.set()
        else:
            raise ValueError('Unknown service command')
        return self.status()

    async def client(self, reader, writer):
        try:
            raw = writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _, uid, _ = struct.unpack('3i', raw)
            if uid != os.getuid():
                raise PermissionError('Service accepts only its owning user')
            line = await asyncio.wait_for(reader.readline(), 3)
            if len(line) > 16384:
                raise ValueError('Service request is too large')
            result = {'ok': True, 'result': await self.command(json.loads(line))}
        except Exception as error:
            result = {'ok': False, 'error': str(error)}
        try:
            writer.write((json.dumps(result) + '\n').encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def supervise(self):
        while not self.shutdown.is_set():
            for model, task in list(self.tasks.items()):
                if task.done():
                    session = self.sessions.pop(model)
                    self.tasks.pop(model)
                    try:
                        task.result()
                    except Exception as error:
                        session.error = str(error)
                    if session.error:
                        self.errors[model] = session.error
                        temporary = any(word in session.error.lower() for word in ('timeout', 'disconnected', 'restarted', 'no matching completed'))
                        if not temporary:
                            self.requested.discard(model)
                    self.retry_at[model] = time.monotonic() + 5
            devices = discover()
            for model in list(self.requested):
                if model in self.sessions or self.suspended or not self.sleep_monitor_ready:
                    continue
                if time.monotonic() < self.retry_at.get(model, 0):
                    continue
                matches = [d for d in devices if d.model == model]
                if len(matches) != 1:
                    self.errors[model] = 'Connect exactly one transport for this mouse' if matches else 'Mouse not connected'
                    continue
                session = DeviceSession(matches[0], self.coordinator, journal_directory(), self.pin)
                self.sessions[model] = session
                self.tasks[model] = asyncio.create_task(session.run())
            await asyncio.sleep(.5)

    async def watch_config(self):
        while not self.shutdown.is_set():
            try:
                config = self.store.read()
                if config.json() != self.coordinator.config.json():
                    self.validate_config(config)
                    await self.coordinator.reload(config)
                self.config_error = ''
            except (OSError, ValueError) as error:
                self.config_error = str(error)
                self.requested.clear()
                for session in self.sessions.values():
                    session.stop_requested.set()
            await asyncio.sleep(.5)

    async def watch_sleep(self):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                'dbus-monitor', '--system', "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=16384)
            while line := await process.stdout.readline():
                text = line.strip()
                # dbus-monitor emits NameAcquired on successful bus connection.
                if b'member=NameAcquired' in text:
                    self.sleep_monitor_ready = True
                if text == b'boolean true':
                    self.suspended = True
                    async with self.coordinator.lock:
                        for engine in self.coordinator.engines.values():
                            await engine.cancel(preserve_pointer=False)
                    for session in self.sessions.values():
                        session.stop_requested.set()
                elif text == b'boolean false':
                    self.suspended = False
            raise RuntimeError('Suspend monitor disconnected')
        finally:
            self.sleep_monitor_ready = False
            self.requested.clear()
            for session in self.sessions.values():
                session.stop_requested.set()
            if process is not None and process.returncode is None:
                process.terminate()
                await process.wait()

    async def run(self, path=None):
        if os.geteuid() == 0:
            raise RuntimeError('Run the service as your desktop user, not root')
        path = path or socket_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
            raise PermissionError('Service socket directory must be owned by you with mode 0700')
        lock_fd = os.open(path.parent / 'service.lock', os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        jobs = []
        server = None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(self.client, str(path), limit=16385)
            os.chmod(path, 0o600)
            jobs = [asyncio.create_task(self.focus.run()), asyncio.create_task(self.watch_sleep()),
                    asyncio.create_task(self.watch_config()), asyncio.create_task(self.supervise()),
                    asyncio.create_task(self.shutdown.wait())]
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().add_signal_handler(sig, self.shutdown.set)
            done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for job in done:
                job.result()
        finally:
            self.requested.clear()
            for session in self.sessions.values():
                session.stop_requested.set()
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            try:
                await self.emergency.remove()
            except (OSError, ValueError, RuntimeError):
                pass
            if server:
                server.close()
                await server.wait_closed()
                path.unlink(missing_ok=True)
            os.close(lock_fd)


async def request(command, *, model=None, profile=None, path=None):
    reader, writer = await asyncio.open_unix_connection(str(path or socket_path()), limit=1024 * 1024)
    try:
        data = {'command': command}
        if model is not None:
            data['model'] = model
        if profile is not None:
            data['profile'] = profile
        writer.write((json.dumps(data) + '\n').encode())
        await writer.drain()
        reply = json.loads(await asyncio.wait_for(reader.readline(), 30))
        if not reply.get('ok'):
            raise RuntimeError(reply.get('error', 'Service request failed'))
        return reply['result']
    finally:
        writer.close()
        await writer.wait_closed()
