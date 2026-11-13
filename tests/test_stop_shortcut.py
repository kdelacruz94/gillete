import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from gillete.emergency import EmergencyShortcut
from gillete.model import MODELS
from gillete.profiles import Configuration, ProfileStore
from gillete.service import Daemon
from gillete.stop_shortcut import DEFAULT, StopShortcut


def test_old_configuration_defaults_and_new_preferences_roundtrip_without_other_changes(tmp_path):
    data = Configuration().json()
    del data['emergency_shortcut']
    assert Configuration.parse(data).emergency_shortcut == DEFAULT
    store = ProfileStore(tmp_path / 'profiles.json')
    config = store.read()
    config.emergency_shortcut = ' super + shift + f8 '
    store.save(config, expected_revision=0)
    loaded = store.read()
    assert loaded.emergency_shortcut == 'Shift+Super+F8'
    assert loaded.defaults == config.defaults and not loaded.startup_models
    assert loaded.profiles == config.profiles


@pytest.mark.parametrize('value', [None, True, 8, [], {}, '', 'Ctrl++F8', 'Ctrl+Ctrl+F8',
    'Alt+Ctrl', 'F8+Ctrl', 'F1+F2', 'Ctrl+KEY_A', 'Ctrl+F25', 'Ctrl+F8;exec',
    'CTRL, Pause, exec, anything', 'Ctrl+\nF8\nkeyword anything',
    # A bare Escape would swallow every Escape press on the desktop.
    'Escape', ' escape ', 'Ctrl+Esc', 'Escape+Ctrl'])
def test_invalid_or_injected_shortcuts_cannot_enter_saved_configuration(value):
    data = Configuration().json()
    data['emergency_shortcut'] = value
    with pytest.raises(ValueError): Configuration.parse(data)


class Desktop:
    """Inert bind registry at the compositor IPC boundary, not a desktop."""
    def __init__(self, shortcut, *, backend='lua'):
        self.shortcut, self.backend = shortcut, backend
        self.bindings, self.calls = [], []
        self.refuse_unbind = False

    async def __call__(self, *args):
        self.calls.append(args)
        if args == ('-j', 'binds'):
            return json.dumps(self.bindings)
        if args[0] == 'eval' and self.backend == 'legacy':
            return 'unknown request'
        if (args[0] == 'eval' and args[1].startswith('hl.bind(')
                or args[:2] == ('keyword', 'bind')):
            chord = self.shortcut.shortcut
            if self.backend == 'lua':
                assert args[1].startswith('hl.bind(' + json.dumps(chord.lua) + ', ')
            else:
                assert args[2] == chord.legacy + ', exec, ' + self.shortcut.command
            self.bindings.append({'key': chord.key, 'keycode': 0, 'modmask': chord.mask,
                'dispatcher': 'HL.Dispatcher(exec_cmd)' if self.backend == 'lua' else 'exec',
                'arg': '100' if self.backend == 'lua' else self.shortcut.command,
                'description': self.shortcut.description, 'submap': ''})
        elif args[0] == 'eval' and args[1].startswith('hl.unbind('):
            chord = args[1][len('hl.unbind('):-1]
            decoded = json.loads(chord)
            if not self.refuse_unbind:
                self.bindings[:] = [binding for binding in self.bindings
                    if StopShortcut.parse(decoded).matches(binding) is False]
        elif args[:2] == ('keyword', 'unbind'):
            mods, key = args[2].split(', ')
            chord = StopShortcut.parse('+'.join((*mods.split(), key)))
            if not self.refuse_unbind:
                self.bindings[:] = [b for b in self.bindings if not chord.matches(b)]
        else:
            raise AssertionError(args)
        return 'ok'


@pytest.mark.parametrize('backend', ['lua', 'legacy'])
@pytest.mark.parametrize('preference', ['Ctrl+Shift+F8', 'Super+F12', 'F10', 'Ctrl+Alt+Escape'])
def test_custom_shortcut_installs_recovers_and_removes_exact_chord(tmp_path, backend, preference):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut=preference)
        desktop = Desktop(shortcut, backend=backend)
        desktop.bindings.append({'key': 'F3', 'modmask': 0, 'arg': 'user'})
        user = deepcopy(desktop.bindings)
        shortcut.hyprctl = desktop
        await shortcut.install()
        receipt = json.loads(shortcut.receipt.read_text())
        assert receipt['shortcut'] == preference and shortcut.installed
        recovered = EmergencyShortcut(shortcut.focus, shortcut.receipt, shortcut=preference)
        recovered.hyprctl = desktop
        await recovered.install()
        await recovered.remove()
        assert desktop.bindings == user and not shortcut.receipt.exists()
        assert not recovered.installed
    asyncio.run(check())


def test_escape_needs_a_modifier_and_uses_the_linux_esc_keycode():
    chord = StopShortcut.parse(' alt + ctrl + escape ')
    assert chord.label == 'Ctrl+Alt+Escape' and chord.lua == 'CTRL + ALT + Escape'
    assert chord.legacy == 'CTRL ALT, Escape' and chord.mask == 12
    assert chord.keycodes == {9}  # KEY_ESC (1) plus the XKB offset
    assert chord.matches({'key': 'Escape', 'modmask': 12})
    assert chord.matches({'key': '', 'keycode': 9, 'modmask': 12})
    assert not chord.matches({'key': 'Escape', 'modmask': 64})  # Super+Escape stays the user's
    assert StopShortcut.parse('Shift+Escape').label == 'Shift+Escape'


def test_escape_conflict_with_an_existing_binding_is_refused(tmp_path):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json',
                                     shortcut='Ctrl+Alt+Escape')
        desktop = Desktop(shortcut)
        desktop.bindings.append({'key': '', 'keycode': 9, 'modmask': 12, 'arg': 'user'})
        before = deepcopy(desktop.bindings)
        shortcut.hyprctl = desktop
        with pytest.raises(RuntimeError, match=r'Ctrl\+Alt\+Escape is already bound'):
            await shortcut.install()
        assert desktop.bindings == before and not shortcut.installed
    asyncio.run(check())


@pytest.mark.parametrize('kind', ['symbol', 'code', 'submap', 'ignore_mods'])
def test_custom_key_conflicts_do_not_mutate_or_replace_the_users_binding(tmp_path, kind):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut='Ctrl+F8')
        desktop = Desktop(shortcut)
        binding = {'key': 'F8', 'modmask': 4, 'arg': 'user'}
        if kind == 'code': binding.update(key='', keycode=74)
        if kind == 'submap': binding['submap'] = 'game'
        if kind == 'ignore_mods': binding.update(modmask=0, ignoreMods=True)
        desktop.bindings.append(binding)
        before = deepcopy(desktop.bindings)
        shortcut.hyprctl = desktop
        with pytest.raises(RuntimeError, match=r'Ctrl\+F8 is already bound'):
            await shortcut.install()
        assert desktop.bindings == before and not shortcut.installed
        assert all(call == ('-j', 'binds') for call in desktop.calls)
        assert not shortcut.receipt.exists()
    asyncio.run(check())


@pytest.mark.parametrize('backend', ['lua', 'legacy'])
@pytest.mark.parametrize('previous_receipt', ['default', 'custom'])
def test_new_preference_recovers_exact_old_receipt_after_interruption(tmp_path, backend, previous_receipt):
    async def check():
        previous = DEFAULT if previous_receipt == 'default' else 'Alt+F2'
        old = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut=previous)
        desktop = Desktop(old, backend=backend)
        old.hyprctl = desktop
        await old.install()
        if previous_receipt == 'default':
            # Older installations did not store a shortcut field.
            receipt = json.loads(old.receipt.read_text())
            del receipt['shortcut']
            old.receipt.write_text(json.dumps(receipt))
        new = EmergencyShortcut(old.focus, old.receipt, shortcut='Super+F8')
        desktop.shortcut = new
        new.hyprctl = desktop
        await new.install()
        assert len(desktop.bindings) == 1 and desktop.bindings[0]['key'] == 'F8'
        assert json.loads(new.receipt.read_text())['shortcut'] == 'Super+F8'
        await new.remove()
        assert not desktop.bindings
    asyncio.run(check())


@pytest.mark.parametrize('operation', ['remove', 'recover'])
def test_cleanup_with_a_new_shared_binding_keeps_user_binding_and_recovery_data(tmp_path, operation):
    async def check():
        old = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut='Alt+F8')
        desktop = Desktop(old)
        old.hyprctl = desktop
        await old.install()
        desktop.bindings.append({'key': 'F8', 'modmask': 8, 'arg': 'new user action', 'submap': 'game'})
        before, receipt = deepcopy(desktop.bindings), old.receipt.read_bytes()
        new = EmergencyShortcut(old.focus, old.receipt, shortcut='Super+F9')
        new.hyprctl = desktop
        with pytest.raises(RuntimeError, match='shares'):
            await (old.remove() if operation == 'remove' else new.install())
        assert desktop.bindings == before and old.receipt.read_bytes() == receipt
    asyncio.run(check())


def test_failed_removal_retains_receipt_and_ownership_for_retry(tmp_path):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut='Alt+F8')
        desktop = Desktop(shortcut)
        shortcut.hyprctl = desktop
        await shortcut.install()
        desktop.refuse_unbind = True
        with pytest.raises(RuntimeError, match='not verified'): await shortcut.remove()
        assert shortcut.installed and shortcut.receipt.exists()
        desktop.refuse_unbind = False
        await shortcut.remove()
        assert not shortcut.installed and not shortcut.receipt.exists()
    asyncio.run(check())


def test_changed_old_binding_is_preserved_when_installing_a_different_preference(tmp_path):
    async def check():
        old = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json')
        desktop = Desktop(old)
        old.hyprctl = desktop
        await old.install()
        desktop.bindings[0]['arg'] = 'user replacement'
        before = deepcopy(desktop.bindings)
        new = EmergencyShortcut(old.focus, old.receipt, shortcut='Super+F8')
        desktop.shortcut = new
        new.hyprctl = desktop
        await new.install()
        await new.remove()
        assert desktop.bindings == before
    asyncio.run(check())


@pytest.mark.parametrize('backend', ['lua', 'legacy'])
@pytest.mark.parametrize('recovery', ['shutdown', 'restart', 'new_preference'])
def test_uncertain_install_is_journaled_before_the_command_and_recoverable(tmp_path, backend, recovery):
    async def check():
        old = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut='Alt+F8')
        desktop = Desktop(old, backend=backend)
        async def lose_ack(*args):
            if (args[0] == 'eval' and args[1].startswith('hl.bind(') and backend == 'lua'
                    or args[:2] == ('keyword', 'bind')):
                receipt = json.loads(old.receipt.read_text())
                assert receipt['status'] == 'prepared' and receipt['backend'] == backend
                await desktop(*args)
                raise OSError('reply lost after creation')
            return await desktop(*args)
        old.hyprctl = lose_ack
        with pytest.raises(OSError, match='reply lost'): await old.install()
        assert desktop.bindings and not old.installed
        assert json.loads(old.receipt.read_text())['status'] == 'prepared'
        old.hyprctl = desktop
        if recovery == 'shutdown':
            await old.remove()
        else:
            new = EmergencyShortcut(old.focus, old.receipt,
                shortcut='Super+F9' if recovery == 'new_preference' else old.label)
            desktop.shortcut = new
            new.hyprctl = desktop
            await new.install()
            assert len(desktop.bindings) == 1 and new.installed
            await new.remove()
        assert not desktop.bindings and not old.receipt.exists()
    asyncio.run(check())


def test_receipt_failure_precedes_any_compositor_mutation(tmp_path, monkeypatch):
    import gillete.emergency as module
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json')
        desktop = Desktop(shortcut)
        shortcut.hyprctl = desktop
        def fail(*args): raise OSError('Disk full')
        monkeypatch.setattr(module, 'durable_json', fail)
        with pytest.raises(OSError, match='Disk full'): await shortcut.install()
        assert desktop.calls == [('-j', 'binds')] and not desktop.bindings
    asyncio.run(check())


@pytest.mark.parametrize('response', ['null', '{}', '[null]', 'not-json'])
def test_malformed_compositor_registry_cannot_authorize_an_install(tmp_path, response):
    async def check():
        shortcut = EmergencyShortcut(SimpleNamespace(signature='test'), tmp_path / 'stop.json', shortcut='Alt+F8')
        calls = []
        async def registry(*args):
            calls.append(args)
            return response
        shortcut.hyprctl = registry
        with pytest.raises((ValueError, RuntimeError)): await shortcut.install()
        assert calls == [('-j', 'binds')] and not shortcut.installed and not shortcut.receipt.exists()
    asyncio.run(check())


def test_saving_preference_during_service_run_keeps_installed_shortcut_until_restart(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = store.read()
        config.emergency_shortcut = 'Alt+F8'
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        desktop = Desktop(daemon.emergency)
        daemon.emergency.receipt = tmp_path / 'receipt.json'
        daemon.emergency.hyprctl = desktop
        daemon.coordinator.available, daemon.sleep_monitor_ready = True, True
        await daemon.command({'command': 'enable', 'model': MODELS[0]})
        before = deepcopy(desktop.bindings)
        config = store.read()
        config.emergency_shortcut = 'Ctrl+F9'
        store.save(config, expected_revision=config.revision)
        await daemon.reload_config()
        await daemon.pin(MODELS[1], 'default')
        status = daemon.status()
        assert status['emergency_shortcut'] == status['emergency_shortcut_configured'] == 'Alt+F8'
        assert status['emergency_shortcut_saved'] == 'Ctrl+F9' and status['emergency_shortcut_restart_required']
        await daemon.command({'command': 'enable', 'model': MODELS[1]})
        assert desktop.bindings == before  # A second mouse still uses the active shortcut.
        await daemon.emergency.remove()
        restarted = Daemon(store)
        assert restarted.emergency.label == 'Ctrl+F9' and not restarted.status()['emergency_shortcut_restart_required']
    asyncio.run(check())
