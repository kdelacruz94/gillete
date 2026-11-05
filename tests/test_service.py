import asyncio
import json
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
from gillete.profiles import Configuration, ProfileStore
from gillete.service import Daemon


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
