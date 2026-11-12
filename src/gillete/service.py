"""User-session daemon and private local control socket.

Mice start disabled unless selected in the saved startup preferences. The GUI
can exit while this process keeps serving profiles and cancellable actions.
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
from .diagnostics import transport_identity
from .emergency import EmergencyShortcut
from .focus import HyprlandWatcher, ProfileCoordinator
from .hardware import journal_directory
from .model import MODELS


def socket_path():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'gillete/control.sock'


class Daemon:
    def __init__(self, store, *, trace_controls=False, session_factory=None):
        self.store = store
        self.session_factory = session_factory
        self.trace_controls = trace_controls
        self.coordinator = ProfileCoordinator(store.read())
        self.focus = HyprlandWatcher(self.coordinator)
        self.emergency = EmergencyShortcut(self.focus, shortcut=self.coordinator.config.emergency_shortcut)
        self.requested = set()
        self.startup_pending = set(self.coordinator.config.startup_models)
        self.sessions = {}
        self.tasks = {}
        self.errors = {}
        self.retry_at = {}
        self.suspended = False
        self.sleep_monitor_ready = False
        self.shutdown = asyncio.Event()
        self.config_error = ''
        self.command_lock = asyncio.Lock()

    def validate_config(self, config):
        for session in self.sessions.values():
            session.validate_profiles(config)

    async def pin(self, model, identifier):
        config = self.store.read()
        if identifier is None:
            config.pinned.pop(model, None)
        else:
            if identifier not in config.profiles:
                raise ValueError('Unknown profile')
            config.pinned[model] = identifier
        self.validate_config(config)
        self.store.save(config, expected_revision=config.revision)
        await self.coordinator.reload(config)

    def status(self):
        now = time.monotonic()
        routes = {model: transport_identity(session.device) for model, session in self.sessions.items()
                  if getattr(session, 'device', None) is not None}
        return {'running': True, 'config_path': str(self.store.path.resolve()),
                'startup_pending': sorted(self.startup_pending),
                'focus_available': self.coordinator.available,
                'focus_pending': self.coordinator.focus_pending,
                'focus': asdict(self.coordinator.window), 'focus_error': self.focus.last_error,
                'suspended': self.suspended, 'suspend_monitor': self.sleep_monitor_ready,
                'emergency_shortcut': self.emergency.label if self.emergency.installed else None,
                'emergency_shortcut_configured': self.emergency.label,
                'emergency_shortcut_saved': self.coordinator.config.emergency_shortcut,
                'emergency_shortcut_restart_required': self.emergency.label != self.coordinator.config.emergency_shortcut,
                'configuration_error': self.config_error,
                'devices': {model: {'requested': model in self.requested,
                                    'active': bool(self.sessions.get(model) and self.sessions[model].ready),
                                    'profile': self.sessions[model].engine.profile.id if self.sessions.get(model) and self.sessions[model].engine else None,
                                    'error': self.errors.get(model, ''),
                                    'transport': routes.get(model),
                                    'retry_in_ms': (int(max(0, self.retry_at.get(model, 0) - now) * 1000)
                                                    if model in self.requested and model not in self.sessions else 0),
                                    'action_error': getattr(self.sessions.get(model), 'action_error', ''),
                                    'active_macros': sum(not job.done() for job in self.sessions[model].engine.macros.jobs.values()) if self.sessions.get(model) and self.sessions[model].engine else 0,
                                    'mode': 'pinned' if model in self.coordinator.config.pinned else 'automatic',
                                    **({'input_trace': self.sessions[model].input_trace.document(self.sessions[model].engine)}
                                       if self.trace_controls and model in self.sessions
                                       and self.sessions[model].engine is not None
                                       and self.sessions[model].input_trace is not None else {})} for model in MODELS}}

    async def command(self, data):
        # Serialize enable/disable and shortcut ownership across local clients.
        async with self.command_lock:
            return await self._command(data)

    async def _command(self, data):
        if not isinstance(data, dict) or set(data) - {'command', 'model', 'profile', 'config_path'}:
            raise ValueError('Invalid service request')
        if data.get('config_path') is not None and data['config_path'] != str(self.store.path.resolve()):
            raise ValueError('A service using a different profile file is already running; stop it before switching configurations')
        command, model = data.get('command'), data.get('model')
        if command == 'status':
            return self.status()
        if self.shutdown.is_set() and command != 'shutdown':
            raise ValueError('The service is shutting down')
        if command in {'enable', 'disable', 'pin', 'select-profile'} and model not in MODELS:
            raise ValueError('Unknown mouse model')
        if command == 'enable':
            self.startup_pending.discard(model)
            if (not self.sleep_monitor_ready or not self.coordinator.available
                    or self.coordinator.focus_pending or self.suspended):
                raise ValueError('Focus and suspend monitoring must be available with current focus details before enabling a mouse')
            # A shutdown during the compositor request must finish ownership
            # verification so cleanup can remove any shortcut that was created.
            installation = asyncio.create_task(self.emergency.install())
            try:
                await asyncio.shield(installation)
            except asyncio.CancelledError:
                await installation
                raise
            if (self.shutdown.is_set() or self.suspended or not self.sleep_monitor_ready
                    or not self.coordinator.available or self.coordinator.focus_pending):
                raise ValueError('Desktop monitoring changed while enabling the mouse; try again when ready')
            self.requested.add(model)
            self.errors.pop(model, None)
            self.retry_at[model] = 0
        elif command == 'disable':
            self.startup_pending.discard(model)
            self.requested.discard(model)
            if model in self.sessions:
                self.sessions[model].stop_requested.set()
                await self.tasks[model]
        elif command in {'pin', 'select-profile'}:
            if command == 'pin' and not isinstance(data.get('profile'), str):
                raise ValueError('Choose a profile or the legacy automatic selector')
            identifier = data.get('profile')
            if command == 'pin' and identifier == 'automatic': identifier = None
            await self.pin(model, identifier)
        elif command == 'stop-actions':
            self.startup_pending.clear()
            async with self.coordinator.lock:
                for engine in self.coordinator.engines.values():
                    await engine.cancel(preserve_pointer=False)
        elif command == 'shutdown':
            self.startup_pending.clear()
            self.shutdown.set()
        else:
            raise ValueError('Unknown service command')
        return self.status()

    async def client(self, reader, writer):
        try:
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
            writer.write((json.dumps(result) + '\n').encode())
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def start_preferences(self):
        if (not self.startup_pending or self.shutdown.is_set() or self.suspended
                or not self.sleep_monitor_ready or not self.coordinator.available
                or self.coordinator.focus_pending or self.config_error):
            return
        for model in list(self.startup_pending):
            async with self.command_lock:
                # A user's Disable / Stop action may have arrived while waiting.
                if model not in self.startup_pending or self.shutdown.is_set():
                    continue
                try:
                    await self._command({'command': 'enable', 'model': model})
                except (OSError, ValueError, RuntimeError) as error:
                    self.errors[model] = 'Startup: ' + str(error)

    async def supervise(self):
        while not self.shutdown.is_set():
            await self.supervise_once()
            await asyncio.sleep(.5)

    async def supervise_once(self):
        await self.start_preferences()
        for model, task in list(self.tasks.items()):
            if self.sessions[model].ready:
                self.errors.pop(model, None)
            if task.done():
                session = self.sessions.pop(model)
                self.tasks.pop(model)
                try:
                    task.result()
                except asyncio.CancelledError:
                    session.error, session.retryable = 'Mouse session was cancelled', False
                except Exception as error:
                    # An exception escaping run() has no verified cleanup outcome.
                    session.error, session.retryable = str(error) or type(error).__name__, False
                if session.error:
                    self.errors[model] = session.error
                    if not session.retryable:
                        self.requested.discard(model)
                self.retry_at[model] = time.monotonic() + 5
        devices = discover()
        if not self.coordinator.available:
            for session in self.sessions.values():
                session.stop_requested.set()
        for model in list(self.requested):
            if (model in self.sessions or self.suspended or not self.sleep_monitor_ready
                    or not self.coordinator.available or self.coordinator.focus_pending):
                continue
            if time.monotonic() < self.retry_at.get(model, 0):
                continue
            matches = [d for d in devices if d.model == model]
            if len(matches) != 1:
                self.errors[model] = 'Connect exactly one transport for this mouse' if matches else 'Mouse not connected'
                continue
            session = (self.session_factory or DeviceSession)(matches[0], self.coordinator, journal_directory(), self.pin,
                                    trace_controls=self.trace_controls)
            self.sessions[model] = session
            self.tasks[model] = asyncio.create_task(session.run())

    async def reload_config(self):
        try:
            config = self.store.read()
            if config.json() != self.coordinator.config.json():
                self.validate_config(config)
                await self.coordinator.reload(config)
            self.config_error = ''
        except (OSError, ValueError) as error:
            self.config_error = str(error)
            self.startup_pending.clear()
            self.requested.clear()
            for session in self.sessions.values():
                session.stop_requested.set()

    async def watch_config(self):
        while not self.shutdown.is_set():
            await self.reload_config()
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
            self.shutdown.set()
            if server:
                server.close()
                await server.wait_closed()
            self.startup_pending.clear()
            # Stop supervisors first so none can create a new session during teardown.
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            # Finish any admitted enable/disable request before releasing its
            # resources. New mutation requests now fail the shutdown check.
            async with self.command_lock:
                self.requested.clear()
            for session in self.sessions.values():
                session.stop_requested.set()
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
            try:
                await self.emergency.remove()
            except (OSError, ValueError, RuntimeError):
                pass
            if server:
                path.unlink(missing_ok=True)
            os.close(lock_fd)


async def request(command, *, model=None, profile=None, path=None, config_path=None):
    reader, writer = await asyncio.open_unix_connection(str(path or socket_path()), limit=1024 * 1024)
    try:
        data = {'command': command}
        if model is not None:
            data['model'] = model
        if profile is not None:
            data['profile'] = profile
        if config_path is not None:
            data['config_path'] = str(Path(config_path).resolve())
        writer.write((json.dumps(data) + '\n').encode())
        await writer.drain()
        reply = json.loads(await asyncio.wait_for(reader.readline(), 30))
        if not reply.get('ok'):
            raise RuntimeError(reply.get('error', 'Service request failed'))
        return reply['result']
    finally:
        writer.close()
        await writer.wait_closed()
