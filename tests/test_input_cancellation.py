"""Real packet buffers, simulated outputs: no desktop or physical mouse access."""

import asyncio
from copy import deepcopy
import socket
import threading
from types import SimpleNamespace

from evdev import ecodes as E
import pytest

from gillete.device_session import DeviceSession
from gillete.devices import Device
from gillete.compile_onboard import CONTROL_IDS
from gillete.engine import Engine
from gillete.focus import ProfileCoordinator
from gillete.macros import KeyLedger, RecordingOutput
from gillete.hardware import Snapshot
from gillete.model import Action, Layers, MODELS, Profile
from gillete.profiles import Configuration, Rule, Window
from gillete.onboard import Location
from gillete.protocol import DeviceUnavailable, ProtocolError
from gillete.reports import Frame
from gillete.runtime import Router


class TrackedRouter(Router):
    def __init__(self, engine):
        super().__init__(engine)
        self.receipts = asyncio.Queue()

    async def feed(self, frame, **kwargs):
        await super().feed(frame, **kwargs)
        self.receipts.put_nowait(frame)

    async def processed(self, count=1):
        for _ in range(count):
            await asyncio.wait_for(self.receipts.get(), 1)


async def setup_session(tmp_path, model=MODELS[0]):
    first = Profile('default', 'First', Layers(normal={'side_1': Action('keys', keys=('KEY_A',))}))
    second = Profile('next', 'Second', Layers(normal={'side_1': Action('keys', keys=('KEY_B',))}))
    config = Configuration(profiles={'default': first, 'next': second}, rules=[Rule('next', app_class='next')])
    coordinator = ProfileCoordinator(config)
    pins = []
    async def pin(model, profile): pins.append((model, profile))
    session = DeviceSession(SimpleNamespace(model=model), coordinator, tmp_path, pin)
    output = RecordingOutput()
    engine = Engine(model, first, KeyLedger(output), input_boundary=session.capture_pending,
                    dpi=lambda target: session.enqueue('dpi', target),
                    device_action=lambda target: session.enqueue('native', target),
                    select_profile=lambda target: session.enqueue('profile', target))
    session.engine = engine
    session.failure = asyncio.get_running_loop().create_future()
    await coordinator.attach('test', engine)
    await coordinator.focus_changed(Window('one', 'first'))
    return session, output, pins


@pytest.mark.parametrize('buffer', ['hidraw', 'python'])
@pytest.mark.parametrize('boundary', ['focus', 'pinned_focus', 'profile', 'emergency', 'monitor_lost'])
def test_buffered_press_never_runs_after_cancellation_until_release_and_fresh_press(tmp_path, buffer, boundary):
    async def check():
        session, output, _ = await setup_session(tmp_path)
        engine, coordinator = session.engine, session.coordinator
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        reader.setblocking(False)
        session.fds[reader.fileno()] = '02'
        router = TrackedRouter(engine)
        task = None
        press = b'\0\0\x1e' + bytes(5)
        try:
            writer.send(press)
            if buffer == 'python':
                session.read_ready(reader.fileno())
            if boundary == 'focus':
                await coordinator.focus_changed(Window('two', 'next'))
            elif boundary == 'pinned_focus':
                coordinator.config.pinned[MODELS[0]] = 'default'
                await coordinator.focus_changed(Window('two', 'next'))
            elif boundary == 'profile':
                config = deepcopy(coordinator.config)
                config.pinned[MODELS[0]] = 'next'
                await coordinator.reload(config)
            elif boundary == 'emergency':
                await engine.cancel(preserve_pointer=False)
            else:
                await coordinator.unavailable()
                await coordinator.focus_changed(Window('two', 'next'))
            task = asyncio.create_task(session.process_frames(router))
            await router.processed()
            assert not output.events and 'side_1' in engine.disarmed
            # A duplicate held report is not a new press in the new generation.
            writer.send(press)
            session.read_ready(reader.fileno())
            await router.processed()
            assert not output.events
            for raw in (bytes(8), press, bytes(8)):
                writer.send(raw)
                session.read_ready(reader.fileno())
                await router.processed()
            key = E.KEY_A if boundary in {'pinned_focus', 'emergency'} else E.KEY_B
            assert output.events == [('key', key, 1), ('key', key, 0)]
            assert not engine.disarmed and not engine.ledger.holders
        finally:
            session.stop_requested.set()
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await coordinator.detach('test')
            reader.close()
            writer.close()
    asyncio.run(check())


def test_stale_reports_preserve_pointer_motion_and_releases_but_not_wheel_actions():
    async def check():
        profile = Profile('p', 'P', Layers(normal={'wheel_up': Action('turbo', keys=('KEY_1',), playback='toggle')}))
        stored = {('left_click', False): Action('keys', keys=('BTN_LEFT',))}
        output = RecordingOutput()
        engine = Engine(MODELS[0], profile, KeyLedger(output), stored=stored)
        router = Router(engine)
        await router.feed(Frame('pointer', frozenset({'left_click'})))
        await engine.cancel()  # Ordinary focus change preserves a native drag.
        await router.feed(Frame('pointer', motion=(('REL_X', 5),), pulses=(('wheel_up', 2),)), activate=False)
        assert output.events == [('key', E.BTN_LEFT, 1), ('key', E.BTN_LEFT, 0), ('relative', E.REL_X, 5)]
        assert not engine.macros.jobs and not engine.ledger.holders
        await router.feed(Frame('pointer', pulses=(('wheel_up', 1),)))
        await asyncio.sleep(0)
        assert engine.macros.jobs
        await router.close()
        assert not engine.ledger.holders
    asyncio.run(check())


def test_report_waiting_on_mode_query_is_rechecked_after_focus_changes(tmp_path):
    async def check():
        session, output, _ = await setup_session(tmp_path)
        querying, finish = asyncio.Event(), asyncio.Event()
        async def mode_query():
            querying.set()
            await finish.wait()
        session.verify_mode = mode_query
        session.needs_mode_check = True
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        reader.setblocking(False)
        session.fds[reader.fileno()] = '02'
        router = TrackedRouter(session.engine)
        task = asyncio.create_task(session.process_frames(router))
        try:
            writer.send(b'\0\0\x1e' + bytes(5))
            session.read_ready(reader.fileno())
            await asyncio.wait_for(querying.wait(), 1)
            await session.coordinator.focus_changed(Window('two', 'next'))
            finish.set()
            await router.processed()
            assert not output.events and 'side_1' in session.engine.disarmed
        finally:
            finish.set()
            session.stop_requested.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await session.coordinator.detach('test')
            reader.close()
            writer.close()
    asyncio.run(check())


def test_old_cross_interface_trigger_and_button_wait_for_release_without_restarting_shift():
    async def check():
        profile = Profile('p', 'P', Layers(normal={'ring_finger': Action('hypershift', playback='toggle'),
                                                  'side_1': Action('keys', keys=('KEY_A',))},
                                          shifted={'side_1': Action('keys', keys=('KEY_B',))}))
        output = RecordingOutput()
        engine = Engine(MODELS[1], profile, KeyLedger(output))
        router = Router(engine)
        for source, control in (('vendor', 'ring_finger'), ('side', 'side_1')):
            await router.feed(Frame(source, frozenset({control})), activate=False)
            await router.feed(Frame(source, frozenset({control})))
        assert not engine.shifted and not output.events
        for source in ('side', 'vendor'):
            await router.feed(Frame(source))
        await router.feed(Frame('vendor', frozenset({'ring_finger'})))
        await router.feed(Frame('side', frozenset({'side_1'})))
        assert engine.shifted and output.events == [('key', E.KEY_B, 1)]
        await router.close()
        assert output.events[-1] == ('key', E.KEY_B, 0)
    asyncio.run(check())


@pytest.mark.parametrize('reason', ['cancel', 'stop', 'unavailable'])
def test_button_command_waiting_for_hardware_lock_cannot_write_after_cancellation(tmp_path, reason):
    async def check():
        session, _, pins = await setup_session(tmp_path)
        writes = []
        controls = SimpleNamespace(dpi=lambda target: writes.append(('dpi', target)),
                                   native=lambda target: writes.append(('native', target)))
        engine = session.engine
        engine.profile.common.normal.update({'side_2': Action('dpi', target='up'),
                                              'side_3': Action('profile', target='next'),
                                              'side_4': Action('device', target='wheel_mode_cycle')})
        for control in ('side_2', 'side_3', 'side_4'):
            await engine.press(control)
            await engine.release(control)
        await session.io_lock.acquire()
        task = asyncio.create_task(session.process_controls(controls))
        await asyncio.sleep(0)  # First command has left the queue and waits for the lock.
        assert session.control_queue.qsize() == 2
        if reason == 'cancel':
            await engine.cancel()
        elif reason == 'stop':
            session.stop_requested.set()
        else:
            session.coordinator.available = False
        session.io_lock.release()
        session.control_queue.put_nowait(None)
        await asyncio.wait_for(task, 1)
        assert not writes and not pins
        # A subsequently enabled, freshly pressed action still works normally.
        session.stop_requested.clear()
        session.coordinator.available = True
        for control in ('side_2', 'side_3', 'side_4'):
            await engine.press(control)
            await engine.release(control)
        session.control_queue.put_nowait(None)
        await session.process_controls(controls)
        assert writes == [('dpi', 'up'), ('native', 'wheel_mode_cycle')]
        assert pins == [(MODELS[0], 'next')]
    asyncio.run(check())


def test_admitted_hardware_operation_finishes_before_cancellation_releases_its_lock(tmp_path):
    async def check():
        session, _, _ = await setup_session(tmp_path)
        started, finish = asyncio.Event(), threading.Event()
        writes = []
        loop = asyncio.get_running_loop()
        def operation():
            loop.call_soon_threadsafe(started.set)
            if not finish.wait(2): raise RuntimeError('Test worker was not released')
            writes.append('completed')
        task = asyncio.create_task(session.hardware_call(operation, generation=session.engine.generation))
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await session.engine.cancel()
            await asyncio.sleep(0)
            assert not task.done() and session.io_lock.locked()
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert writes == ['completed'] and not session.io_lock.locked()
    asyncio.run(check())


def test_command_queue_overflow_stops_before_any_queued_command_can_execute(tmp_path):
    async def check():
        session, _, pins = await setup_session(tmp_path)
        writes = []
        controls = SimpleNamespace(dpi=lambda target: writes.append(target))
        for _ in range(session.control_queue.maxsize):
            await session.enqueue('dpi', 'up')
        with pytest.raises(ProtocolError, match='command queue overflowed'):
            await session.enqueue('dpi', 'up')
        assert session.stop_requested.is_set() and session.failure.done()
        task = asyncio.create_task(session.process_controls(controls))
        await asyncio.sleep(0)
        session.control_queue.put_nowait(None)
        await task
        assert not writes and not pins
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['undrained', 'overflow', 'disconnect'])
def test_uncertain_input_buffer_stops_before_queued_actions_execute(tmp_path, failure):
    async def check():
        session, output, _ = await setup_session(tmp_path)
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        reader.setblocking(False)
        session.fds[reader.fileno()] = '02'
        try:
            if failure == 'overflow':
                for _ in range(session.frames.maxsize):
                    session.frames.put_nowait((0, session.engine.generation, Frame('side')))
            for _ in range(129 if failure == 'undrained' else 1):
                writer.send(b'' if failure == 'disconnect' else b'\0\0\x1e' + bytes(5))
            await session.engine.cancel()
            assert session.stop_requested.is_set() and session.failure.done()
            assert str(session.failure.result())
            await asyncio.wait_for(session.process_frames(Router(session.engine)), 1)
            assert not output.events
        finally:
            reader.close()
            writer.close()
    asyncio.run(check())


@pytest.mark.parametrize('worker_error', [None, DeviceUnavailable('No reply after disconnect'),
                                        ProtocolError('Settings recovery required at timeout.json')])
def test_disconnect_releases_turbo_before_waiting_for_an_admitted_usb_operation(tmp_path, monkeypatch, worker_error):
    import gillete.device_session as sessions
    async def check():
        model = MODELS[0]
        device = Device(model, 'Test', '2.4 GHz', 0xB4, '/test', 'test')
        snapshot = Snapshot(0xB4, model, 'test', 1, (1,), 1, set(CONTROL_IDS[model].values()),
                            {Location(1, c, l): bytes((1, c, 0)) + bytes.fromhex('0202001e000000')
                             for c in CONTROL_IDS[model].values() for l in (0, 1)},
                            {'dpi': '01070807080000', 'stages': '01010101032003200000' + '00' * 28})
        class IO:
            product, mode, closed = 0xB4, bytes(2), False
            def __enter__(self): return self
            def __exit__(self): self.closed = True
            def device_serial(self): return 'test'
            def execute(self, command): return self.mode
            def _exchange(self, command): self.mode = command.payload
        io = IO()
        pressed, blocked, finish = asyncio.Event(), asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        class Output(RecordingOutput):
            def __init__(self, suffix):
                super().__init__()
                self.closed = False
                self.keymap = SimpleNamespace(watch=self.watch)
            async def watch(self): await asyncio.Future()
            async def prepare_keyboard(self): pass
            async def restore_keyboard(self): pass
            def close(self): self.closed = True
            def key(self, code, value):
                super().key(code, value)
                if code == E.KEY_1 and value: pressed.set()
        class Controls:
            def __init__(self, *_args): pass
            def dpi(self, target):
                loop.call_soon_threadsafe(blocked.set)
                if not finish.wait(3): raise RuntimeError('Test USB operation was not released')
                if worker_error is not None: raise worker_error
        monkeypatch.setattr(sessions, 'inspect', lambda *_: snapshot)
        monkeypatch.setattr(sessions, 'transport', lambda *_: io)
        monkeypatch.setattr(sessions, 'UInputOutput', Output)
        monkeypatch.setattr(sessions, 'Controls', Controls)
        profile = Profile('default', 'Default', Layers(normal={
            'side_1': Action('turbo', keys=('KEY_1',), playback='toggle'),
            'side_2': Action('dpi', target='up')}))
        coordinator = ProfileCoordinator(Configuration(profiles={'default': profile}))
        coordinator.available = True
        session = DeviceSession(device, coordinator, tmp_path, None)
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        reader.setblocking(False)
        fd = reader.detach()  # DeviceSession owns/ closes this real packet socket.
        monkeypatch.setattr(session, 'open_inputs', lambda: session.fds.update({fd: '02'}))
        task = asyncio.create_task(session.run())
        try:
            async with asyncio.timeout(1):
                while not session.ready:
                    assert not task.done(), session.error
                    await asyncio.sleep(.001)
            writer.send(b'\0\0\x1e' + bytes(5))
            await asyncio.wait_for(pressed.wait(), 1)
            writer.send(bytes(8))
            writer.send(b'\0\0\x1f' + bytes(5))
            await asyncio.wait_for(blocked.wait(), 1)
            session.fail(DeviceUnavailable('Mouse input disconnected'))
            async with asyncio.timeout(.5):
                while session.engine.macros.jobs or session.engine.ledger.holders:
                    await asyncio.sleep(.001)
            count = len(session.output.events)
            assert not task.done() and session.io_lock.locked() and not io.closed
            assert io.mode == b'\3\0'
            await asyncio.sleep(.02)
            assert len(session.output.events) == count  # No repeating keys while USB finishes.
        finally:
            finish.set()
            session.stop_requested.set()
            await asyncio.wait_for(task, 1)
            writer.close()
        assert io.mode == bytes(2) and io.closed and session.output.closed
        assert 'disconnected' in session.error and not session.ready
        assert not session.engine.macros.jobs and not session.engine.ledger.holders
        assert session.retryable is (worker_error is None or isinstance(worker_error, DeviceUnavailable))
        if worker_error is not None:
            assert 'Session worker failed' in session.error and str(worker_error) in session.error
        keys = [value for kind, code, value in session.output.events if kind == 'key' and code == E.KEY_1]
        assert keys and keys[::2] == [1] * (len(keys) // 2) and keys[1::2] == [0] * (len(keys) // 2)
    asyncio.run(check())
