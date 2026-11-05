"""One explicitly enabled mouse: input ownership, mode lease and cleanup."""

import asyncio
import fcntl
import os
from pathlib import Path
import struct
import time
from uuid import uuid4

from evdev import InputDevice

from .device_controls import Controls
from .driver_mode import ModeLease
from .engine import Engine
from .hardware import inspect, read_journal, transport
from .macros import KeyLedger
from .protocol import Command, ProtocolError
from .reports import decode
from .runtime import Router, UInputOutput
from .stored_actions import from_snapshot, unresolved


class DeviceSession:
    def __init__(self, device, coordinator, state, pin_profile):
        self.device, self.coordinator = device, coordinator
        self.state, self.pin_profile = state, pin_profile
        self.stop_requested = asyncio.Event()
        self.ready = False
        self.error = ''
        self.engine = None
        self.snapshot = None
        self.frames = asyncio.Queue(maxsize=4096)
        self.control_queue = asyncio.Queue(maxsize=32)
        self.io_lock = asyncio.Lock()
        self.fds, self.evdev = {}, []
        self.output = self.io = self.lease = None
        self.failure = None
        self.launch_waiters = set()
        self.needs_mode_check = False

    async def hardware_call(self, fn, *args):
        async with self.io_lock:
            # Cancellation must not leave a worker touching a closed HID fd.
            task = asyncio.create_task(asyncio.to_thread(fn, *args))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    def fail(self, error):
        if self.failure is not None and not self.failure.done():
            self.failure.set_result(error)

    def read_ready(self, fd):
        try:
            for _ in range(128):
                raw = os.read(fd, 4096)
                if not raw:
                    raise OSError('Mouse input disconnected')
                frame = decode(self.device.model, self.fds[fd], raw)
                if frame is not None:
                    self.frames.put_nowait((time.monotonic(), frame))
                else:
                    self.needs_mode_check = True
        except BlockingIOError:
            pass
        except Exception as error:
            self.fail(error)

    async def enqueue(self, kind, target):
        self.control_queue.put_nowait((kind, target))

    async def launch(self, argv):
        process = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
                                                       stdout=asyncio.subprocess.DEVNULL,
                                                       stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        waiter = asyncio.create_task(process.wait())
        self.launch_waiters.add(waiter)
        waiter.add_done_callback(self.launch_waiters.discard)

    def validate_profiles(self, config):
        if self.engine is None:
            return
        issues = []
        for profile in config.profiles.values():
            missing = unresolved(profile, self.device.model, self.engine.stored)
            issues.extend(f"{profile.name}: {c} ({'HyperShift' if s else 'normal'})" for c, s in missing)
        if issues:
            raise ProtocolError('Stored firmware actions need explicit software mappings: ' + '; '.join(issues))

    def recover_previous_mode(self):
        # Only this app's mode leases are considered; no binding journal is
        # automatically restored. The serial must match before any mode write.
        for path in sorted(self.state.glob('mode-*.json')):
            document = read_journal(path)
            if document.get('kind') != 'driver-mode' or document.get('status') == 'normal-mode-restored':
                continue
            if document.get('product') != self.device.product_id:
                continue
            with transport(self.device) as io:
                if io.device_serial() == document.get('serial'):
                    ModeLease(io, path).restore()

    def open_inputs(self):
        for node in self.device.interfaces:
            if node['kind'] == 'input':
                source = InputDevice(node['path'])
                self.evdev.append(source)
                if source.info.vendor != 0x1532 or source.info.product != self.device.product_id:
                    raise ProtocolError('Input identity changed')
                if source.active_keys():
                    raise ProtocolError('Release all mouse buttons before enabling software remapping')
                try:
                    source.grab()
                except OSError as error:
                    raise ProtocolError('Another application owns a mouse interface; suspend its remapping first') from error
            elif node['kind'] == 'hidraw' and node['number'] in ('00', '01', '02'):
                fd = os.open(node['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
                self.fds[fd] = node['number']
                info = bytearray(8)
                fcntl.ioctl(fd, 0x80084803, info, True)
                if struct.unpack('IHH', info) != (3, 0x1532, self.device.product_id):
                    raise ProtocolError('Raw input identity changed')
        if len(self.fds) != 3 or set(self.fds.values()) != {'00', '01', '02'} or not self.evdev:
            raise ProtocolError('Mouse input interfaces are incomplete')

    async def verify_mode(self):
        mode = await self.hardware_call(self.io.execute, Command(0, 0x84, bytes(2)))
        if mode != b'\3\0':
            raise ProtocolError('Mouse mode changed or the mouse restarted; reconnecting')

    async def process_frames(self, router):
        previous = time.monotonic()
        while True:
            timestamp, frame = await self.frames.get()
            if timestamp - previous > 2 or self.needs_mode_check:
                await self.verify_mode()
                self.needs_mode_check = False
            previous = timestamp
            async with self.coordinator.lock:
                await router.feed(frame)

    async def process_controls(self, controls):
        while True:
            item = await self.control_queue.get()
            if item is None:
                return
            kind, target = item
            if kind == 'profile':
                await self.pin_profile(self.device.model, target)
            else:
                await self.hardware_call(controls.dpi if kind == 'dpi' else controls.native, target)

    async def watch_held_input(self):
        # Receiver USB nodes can remain present while a wireless mouse is off.
        # Check reachability while actions/holds are active, not continuously
        # while idle. A wake after an input gap is checked before translation.
        while True:
            await asyncio.sleep(.3)
            if self.engine.pressed or self.engine.macros.jobs:
                await self.verify_mode()

    async def run(self):
        tasks = []
        loop = asyncio.get_running_loop()
        self.failure = loop.create_future()
        attached = False
        try:
            await self.hardware_call(self.recover_previous_mode)
            self.snapshot = await self.hardware_call(inspect, self.device)
            stored, _ = from_snapshot(self.snapshot)
            # Create the engine with a fake-free output only after preflight.
            profile = self.coordinator.config.select(self.device.model, self.coordinator.window)
            self.engine = Engine(self.device.model, profile, KeyLedger(None), stored=stored,
                                 launch=self.launch,
                                 dpi=lambda target: self.enqueue('dpi', target),
                                 device_action=lambda target: self.enqueue('native', target),
                                 select_profile=lambda target: self.enqueue('profile', target))
            self.validate_profiles(self.coordinator.config)
            if not self.coordinator.available:
                raise ProtocolError('Hyprland focus monitoring is unavailable')
            if self.stop_requested.is_set():
                return
            self.output = UInputOutput(f'{self.device.product_id:04x}')
            self.engine.ledger.output = self.output
            await self.output.prepare_keyboard()
            self.io = transport(self.device)
            self.io.__enter__()
            if await self.hardware_call(self.io.device_serial) != self.snapshot.serial:
                raise ProtocolError('Mouse identity changed after inspection')
            self.open_inputs()
            self.lease = ModeLease(self.io, self.state / f'mode-{uuid4().hex}.json')
            await self.hardware_call(self.lease.enter)
            controls = Controls(self.io, self.snapshot, self.state)
            router = Router(self.engine)
            await self.coordinator.attach(self.device.identity, self.engine)
            attached = True
            for fd in self.fds:
                loop.add_reader(fd, self.read_ready, fd)
            self.ready = True
            tasks = [asyncio.create_task(self.process_frames(router)),
                     asyncio.create_task(self.process_controls(controls)),
                     asyncio.create_task(self.watch_held_input()),
                     asyncio.create_task(self.output.keymap.watch()),
                     asyncio.create_task(self.stop_requested.wait())]
            done, _ = await asyncio.wait([*tasks, self.failure], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                result = task.result()
                if isinstance(result, Exception):
                    raise result
        except Exception as error:
            self.error = str(error)
        finally:
            self.ready = False
            for fd in self.fds:
                loop.remove_reader(fd)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if attached:
                    await self.coordinator.detach(self.device.identity)
                elif self.engine is not None:
                    await self.engine.disconnect()
            except Exception as error:
                self.error += f' Input release failed: {error}'
            if self.output is not None:
                try:
                    self.engine.ledger.release_all()
                except Exception as error:
                    self.error += f' Output release failed: {error}'
                finally:
                    try:
                        await self.output.restore_keyboard()
                    except Exception as error:
                        self.error += f' Keyboard options restore failed: {error}'
                    try:
                        self.output.close()
                    except Exception as error:
                        self.error += f' Output close failed: {error}'
            if self.lease is not None and self.lease.document is not None:
                try:
                    await self.hardware_call(self.lease.restore)
                except Exception as error:
                    self.error += f' Mode recovery retained at {self.lease.path}: {error}'
            if self.io is not None:
                try:
                    self.io.__exit__()
                except Exception as error:
                    self.error += f' HID close failed: {error}'
            for fd in self.fds:
                try:
                    os.close(fd)
                except OSError as error:
                    self.error += f' Input close failed: {error}'
            for source in self.evdev:
                try:
                    source.close()  # also releases any successful grabs
                except OSError as error:
                    self.error += f' Input release failed: {error}'
            self.fds.clear()
            self.evdev.clear()
