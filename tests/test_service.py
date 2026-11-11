import asyncio
import json
import signal
import time
from types import SimpleNamespace

import pytest

from gillete.compile_onboard import CONTROL_IDS
from gillete.device_controls import Controls, restore_setting
from gillete.device_session import DeviceSession
from gillete.devices import Device
from gillete.emergency import EmergencyShortcut
from gillete.focus import ProfileCoordinator
from gillete.hardware import Snapshot
from gillete.model import MODELS
from gillete.onboard import Location
from gillete.profiles import Configuration, ProfileStore, Window
from gillete.protocol import ProtocolError
from gillete.service import Daemon, request


def test_session_rejects_unreachable_shift_before_output_or_input_ownership(tmp_path, monkeypatch):
    import gillete.device_session as sessions
    from gillete.model import Action, Layers, Profile
    device = Device(MODELS[1], 'Test', '2.4 GHz', 0xE8, '/test', 'test')
    snapshot = Snapshot(0xE8, device.model, 'test', 1, (1,), 1, set(CONTROL_IDS[device.model].values()),
                        {Location(1, c, l): bytes((1, c, 0)) + bytes.fromhex('0202001e000000')
                         for c in CONTROL_IDS[device.model].values() for l in (0, 1)}, {})
    monkeypatch.setattr(sessions, 'inspect', lambda _: snapshot)
    def forbidden(*_): raise AssertionError('Preflight must precede input/output ownership')
    monkeypatch.setattr(sessions, 'UInputOutput', forbidden)
    monkeypatch.setattr(sessions, 'transport', forbidden)
    async def check():
        config = Configuration(profiles={'default': Profile('default', 'Default', Layers(
            shifted={'side_1': Action('keys', keys=('KEY_F23',))}))})
        coordinator = ProfileCoordinator(config)
        coordinator.available = True
        session = DeviceSession(device, coordinator, tmp_path, None)
        monkeypatch.setattr(session, 'open_inputs', forbidden)
        await session.run()
        assert 'HyperShift configuration needs attention' in session.error and not session.ready
        assert not list(tmp_path.glob('*.json'))
        # The same validation also protects live config reloads and pins.
        config.profiles['default'].common.normal['ring_finger'] = Action('hypershift', playback='held')
        session.validate_profiles(config)
        config.profiles['default'].common.normal.clear()
        with pytest.raises(ProtocolError, match='HyperShift configuration'):
            session.validate_profiles(config)
    asyncio.run(check())


@pytest.mark.parametrize('fail_keyboard_setup', [False, True])
def test_session_restores_mode_and_releases_inputs_even_if_output_close_fails(tmp_path, monkeypatch, fail_keyboard_setup):
    import gillete.device_session as sessions
    device = Device(MODELS[1], 'Test', '2.4 GHz', 0xE8, '/test', 'test')
    snapshot = Snapshot(0xE8, device.model, 'test', 1, (1,), 1, set(CONTROL_IDS[device.model].values()),
                        {Location(1, c, l): bytes((1, c, 0)) + bytes.fromhex('0202001e000000')
                         for c in CONTROL_IDS[device.model].values() for l in (0, 1)}, {})
    class IO:
        product = 0xE8
        mode = bytes(2)
        closed = False
        def __enter__(self): return self
        def __exit__(self): self.closed = True
        def device_serial(self): return 'test'
        def execute(self, command): return self.mode
        def _exchange(self, command): self.mode = command.payload
    io = IO()
    class Output:
        def __init__(self, suffix): pass
        async def prepare_keyboard(self):
            if fail_keyboard_setup:
                raise RuntimeError('Keymap setup failure')
        async def restore_keyboard(self): pass
        def close(self): raise OSError('Output unavailable')
    source = SimpleNamespace(closed=False)
    def close_source(): source.closed = True
    source.close = close_source
    monkeypatch.setattr(sessions, 'inspect', lambda _: snapshot)
    monkeypatch.setattr(sessions, 'transport', lambda _: io)
    monkeypatch.setattr(sessions, 'UInputOutput', Output)
    async def check():
        coordinator = ProfileCoordinator(Configuration())
        coordinator.available = True
        async def fail_attach(*_): raise RuntimeError('Attach failure')
        monkeypatch.setattr(coordinator, 'attach', fail_attach)
        session = DeviceSession(device, coordinator, tmp_path, None)
        monkeypatch.setattr(session, 'open_inputs', lambda: session.evdev.append(source))
        await session.run()
        if fail_keyboard_setup:
            assert io.mode == bytes(2) and not io.closed and not source.closed
            assert 'Keymap setup failure' in session.error and 'Output close failed' in session.error
            assert not list(tmp_path.glob('mode-*.json'))
            return
        assert io.mode == bytes(2) and io.closed and source.closed
        assert 'Attach failure' in session.error and 'Output close failed' in session.error
        journal = next(tmp_path.glob('mode-*.json'))
        assert json.loads(journal.read_text())['status'] == 'normal-mode-restored'
    asyncio.run(check())


def test_daemon_starts_disabled_and_manual_pin_is_durable(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        daemon = Daemon(store)
        assert all(not d['requested'] and not d['active'] for d in daemon.status()['devices'].values())
        await daemon.command({'command': 'pin', 'model': MODELS[0], 'profile': 'default'})
        assert store.read().pinned == {MODELS[0]: 'default'}
        await daemon.command({'command': 'pin', 'model': MODELS[0], 'profile': 'automatic'})
        assert store.read().pinned == {}
        with pytest.raises(ValueError, match='monitoring'):
            await daemon.command({'command': 'enable', 'model': MODELS[0]})
    asyncio.run(check())


def test_pending_focus_blocks_enable_and_saved_startup_until_details_settle(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = store.read()
        config.startup_models = [MODELS[0]]
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        daemon.sleep_monitor_ready = True
        await daemon.coordinator.focus_changed(Window('one', 'app'))
        await daemon.coordinator.focus_event(moved=True)
        installs = []
        async def install(): installs.append(True)
        daemon.emergency.install = install
        with pytest.raises(ValueError, match='current focus'):
            await daemon.command({'command': 'enable', 'model': MODELS[1]})
        await daemon.start_preferences()
        assert not daemon.requested and not installs and daemon.startup_pending == {MODELS[0]}
        assert daemon.status()['focus_available'] and daemon.status()['focus_pending']
        await daemon.coordinator.focus_changed(Window('two', 'other'), revision=daemon.coordinator.focus_revision)
        await daemon.start_preferences()
        assert daemon.requested == {MODELS[0]} and installs == [True]
        assert not daemon.status()['focus_pending']
    asyncio.run(check())


def test_stop_during_keyboard_setup_never_takes_mouse_ownership(tmp_path, monkeypatch):
    import gillete.device_session as sessions
    device = Device(MODELS[1], 'Test', '2.4 GHz', 0xE8, '/test', 'test')
    snapshot = Snapshot(0xE8, device.model, 'test', 1, (1,), 1, set(CONTROL_IDS[device.model].values()),
                        {Location(1, c, l): bytes((1, c, 0)) + bytes.fromhex('0202001e000000')
                         for c in CONTROL_IDS[device.model].values() for l in (0, 1)}, {})
    monkeypatch.setattr(sessions, 'inspect', lambda _: snapshot)
    def forbidden(*_): raise AssertionError('Cancelled startup must not open/grab/change mouse mode')
    monkeypatch.setattr(sessions, 'transport', forbidden)
    async def check():
        started, finish = asyncio.Event(), asyncio.Event()
        released = []
        class Output:
            def __init__(self, suffix): pass
            async def prepare_keyboard(self):
                started.set()
                await finish.wait()
            async def restore_keyboard(self): released.append('keyboard restored')
            def close(self): released.append('closed')
        monkeypatch.setattr(sessions, 'UInputOutput', Output)
        coordinator = ProfileCoordinator(Configuration())
        coordinator.available = True
        session = DeviceSession(device, coordinator, tmp_path, None)
        monkeypatch.setattr(session, 'open_inputs', forbidden)
        task = asyncio.create_task(session.run())
        await asyncio.wait_for(started.wait(), 1)
        session.stop_requested.set()
        finish.set()
        await asyncio.wait_for(task, 1)
        assert released == ['closed', 'keyboard restored']
        assert not session.ready and not session.error and not list(tmp_path.iterdir())
    asyncio.run(check())


def test_existing_emergency_binding_is_never_overwritten(tmp_path):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), receipt=tmp_path / 'emergency.json')
        calls = []
        async def hyprctl(*args):
            calls.append(args)
            return json.dumps([{'key': 'Pause', 'modmask': 12, 'dispatcher': 'exec', 'arg': 'user-command'}])
        shortcut.hyprctl = hyprctl
        with pytest.raises(RuntimeError, match='already bound'):
            await shortcut.install()
        shortcut.installed = True
        await shortcut.remove()
        assert all(c == ('-j', 'binds') for c in calls)
    asyncio.run(check())


def test_lua_emergency_binding_is_verified_recovered_and_removed(tmp_path):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), receipt=tmp_path / 'emergency.json')
        bindings = []
        async def hyprctl(*args):
            if args == ('-j', 'binds'):
                return json.dumps(bindings)
            assert args[0] == 'eval'
            if args[1].startswith('hl.bind('):
                bindings.append({'key': 'Pause', 'modmask': 12, 'description': shortcut.description,
                                 'dispatcher': 'HL.Dispatcher(exec_cmd)', 'arg': '179'})
            elif args[1].startswith('hl.unbind('):
                bindings.clear()
            return 'ok\n'
        shortcut.hyprctl = hyprctl
        await shortcut.install()
        assert shortcut.installed and bindings
        recovered = EmergencyShortcut(SimpleNamespace(signature='test'), receipt=shortcut.receipt)
        recovered.hyprctl = hyprctl
        await recovered.install()
        await recovered.remove()
        assert not bindings and not shortcut.receipt.exists()
    asyncio.run(check())


def test_uncertain_device_setting_is_rolled_back_and_journal_is_recoverable(tmp_path):
    class IO:
        product = 0xE8
        current = b'\1\0'
        fail = True
        def device_serial(self): return 'test'
        def execute(self, command): return self.current
        def _exchange(self, command):
            self.current = command.payload
            if self.fail:
                self.fail = False
                raise TimeoutError('ACK lost after write')
    io = IO()
    controls = Controls(io, SimpleNamespace(serial='test'), tmp_path)
    with pytest.raises(TimeoutError):
        controls.write_checked(2, 0x30, 0xB0, b'\1\0', b'\1\1', b'\1\0')
    assert io.current == b'\1\0'
    path = next(tmp_path.glob('setting-*.json'))
    document = json.loads(path.read_text())
    assert document['status'] == 'rolled-back-readback-verified'
    io.current = b'\1\2'
    restore_setting(io, path, document)
    assert io.current == b'\1\0'


def test_saved_startup_waits_for_monitors_and_disable_cancels_pending_choice(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = store.read()
        config.startup_models = list(MODELS)
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        installs = []
        async def install(): installs.append(True)
        daemon.emergency.install = install
        await daemon.start_preferences()
        assert not daemon.requested and not installs
        await daemon.command({'command': 'disable', 'model': MODELS[0]})
        daemon.sleep_monitor_ready = True
        await daemon.start_preferences()
        assert not daemon.requested
        daemon.coordinator.available = True
        daemon.suspended = True
        await daemon.start_preferences()
        assert not daemon.requested
        daemon.suspended = False
        await daemon.start_preferences()
        assert daemon.requested == {MODELS[1]} and len(installs) == 1
        await daemon.start_preferences()
        assert len(installs) == 1 and not daemon.startup_pending
        # User startup choices persist; live disabling does not silently rewrite them.
        assert store.read().startup_models == list(MODELS)
    asyncio.run(check())


def test_startup_failure_is_visible_and_never_retried_without_explicit_enable(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = store.read()
        config.startup_models = [MODELS[0]]
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        daemon.coordinator.available = daemon.sleep_monitor_ready = True
        attempts = []
        async def conflict():
            attempts.append(True)
            raise RuntimeError('Emergency shortcut already bound')
        daemon.emergency.install = conflict
        await daemon.start_preferences()
        await daemon.start_preferences()
        assert len(attempts) == 1 and not daemon.requested and not daemon.startup_pending
        assert 'already bound' in daemon.status()['devices'][MODELS[0]]['error']
        with pytest.raises(ValueError, match='different profile'):
            await daemon.command({'command': 'enable', 'model': MODELS[1], 'config_path': '/different.json'})
        assert len(attempts) == 1
    asyncio.run(check())


def test_cancelling_startup_waits_for_shortcut_ownership_before_cleanup(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = store.read()
        config.startup_models = [MODELS[1]]
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        daemon.sleep_monitor_ready = daemon.coordinator.available = True
        started, finish = asyncio.Event(), asyncio.Event()
        installed = []
        async def install():
            started.set()
            await finish.wait()
            installed.append(True)
        daemon.emergency.install = install
        task = asyncio.create_task(daemon.start_preferences())
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not daemon.requested
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert installed == [True] and not daemon.requested
    asyncio.run(check())


def test_focus_loss_rejects_new_input_before_it_can_start_an_action(tmp_path):
    from gillete.reports import Frame
    async def check():
        session = DeviceSession(SimpleNamespace(), ProfileCoordinator(Configuration()), tmp_path, None)
        seen = []
        async def feed(frame): seen.append(frame)
        session.frames.put_nowait((time.monotonic(), 0, Frame('pointer', frozenset({'left_click'}))))
        with pytest.raises(ProtocolError, match='focus monitoring'):
            await session.process_frames(SimpleNamespace(feed=feed))
        assert not seen
    asyncio.run(check())


def test_suspend_monitor_cancels_held_output_and_resume_does_not_restart_macro(tmp_path, monkeypatch):
    import gillete.service as services
    from gillete.engine import Engine
    from gillete.macros import KeyLedger, RecordingOutput
    from gillete.model import Action, Layers, Profile
    async def check():
        daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
        profile = Profile('default', 'Default', Layers(normal={
            'side_1': Action('turbo', keys=('KEY_1',), playback='toggle', press_ms=500, interval_ms=1000)}))
        daemon.coordinator.config.profiles['default'] = profile
        output = RecordingOutput()
        engine = Engine(MODELS[0], profile, KeyLedger(output))
        await daemon.coordinator.attach('test', engine)
        daemon.requested.add(MODELS[0])
        stop = asyncio.Event()
        daemon.sessions[MODELS[0]] = SimpleNamespace(stop_requested=stop)
        await engine.press('side_1')
        await engine.release('side_1')
        await asyncio.sleep(0)
        assert engine.macros.jobs and engine.ledger.holders
        reader = asyncio.StreamReader()
        class Monitor:
            stdout, returncode = reader, None
            def terminate(self): self.returncode = 0
            async def wait(self): return self.returncode
        monitor = Monitor()
        async def spawn(*args, **kwargs):
            assert args[:2] == ('dbus-monitor', '--system')
            return monitor
        monkeypatch.setattr(services.asyncio, 'create_subprocess_exec', spawn)
        task = asyncio.create_task(daemon.watch_sleep())
        try:
            reader.feed_data(b'signal member=NameAcquired\nboolean true\n')
            await asyncio.wait_for(stop.wait(), 1)
            assert daemon.suspended and daemon.sleep_monitor_ready
            assert not engine.macros.jobs and not engine.ledger.holders
            count = len(output.events)
            reader.feed_data(b'boolean false\n')
            async with asyncio.timeout(1):
                while daemon.suspended:
                    await asyncio.sleep(.001)
            assert stop.is_set() and len(output.events) == count and not engine.macros.jobs
            assert daemon.requested == {MODELS[0]}  # Supervisor may create a new, empty session.
        finally:
            reader.feed_eof()
            with pytest.raises(RuntimeError, match='Suspend monitor disconnected'):
                await task
        assert not daemon.sleep_monitor_ready and not daemon.requested
        assert monitor.returncode == 0
    asyncio.run(check())


def test_real_service_socket_startup_config_identity_and_orderly_shutdown(tmp_path, monkeypatch):
    import gillete.service as services
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = store.read()
        config.startup_models = [MODELS[1]]
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        ready = asyncio.Event()
        restored = []
        class Session:
            def __init__(self, device, *_args, trace_controls=False):
                assert not trace_controls
                self.ready = False
                self.engine = None
                self.error = ''
                self.stop_requested = asyncio.Event()
            async def run(self):
                self.ready = True
                ready.set()
                try:
                    await self.stop_requested.wait()
                finally:
                    self.ready = False
                    restored.append(True)
        async def focus():
            daemon.coordinator.available = True
            await asyncio.Future()
        async def sleep_monitor():
            daemon.sleep_monitor_ready = True
            await asyncio.Future()
        shortcut = []
        async def install(): shortcut.append('installed')
        async def remove(): shortcut.append('removed')
        monkeypatch.setattr(services, 'DeviceSession', Session)
        monkeypatch.setattr(services, 'discover', lambda: [SimpleNamespace(model=MODELS[1])])
        daemon.focus.run = focus
        daemon.watch_sleep = sleep_monitor
        daemon.emergency.install, daemon.emergency.remove = install, remove
        path = tmp_path / 'runtime/control.sock'
        task = asyncio.create_task(daemon.run(path))
        try:
            await asyncio.wait_for(ready.wait(), 3)
            state = await request('status', path=path, config_path=store.path)
            assert state['devices'][MODELS[1]]['active'] and not state['devices'][MODELS[0]]['requested']
            with pytest.raises(RuntimeError, match='different profile'):
                await request('disable', model=MODELS[1], path=path, config_path=tmp_path / 'other.json')
            assert not restored
            await request('shutdown', path=path, config_path=store.path)
            await asyncio.wait_for(task, 3)
            assert restored == [True] and shortcut == ['installed', 'removed']
            assert not path.exists()
            with pytest.raises(ValueError, match='shutting down'):
                await daemon.command({'command': 'enable', 'model': MODELS[1]})
        finally:
            daemon.shutdown.set()
            await task
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_running_loop().remove_signal_handler(sig)
    asyncio.run(check())
