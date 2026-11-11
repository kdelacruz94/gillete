import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from gillete.function_keymap import XKB
from gillete.keyboard_map import KeyboardMap


NAME = 'gillete-virtual-input-test-' + '1' * 32


def fixture_map(options='', accept=True, legacy=False):
    mapping = KeyboardMap(NAME, signature='test')
    keyboard = {'name': NAME, 'address': 'own', 'rules': '', 'model': '', 'layout': 'de',
                'variant': '', 'options': options, 'active_keymap': 'German'}
    physical = {'name': 'physical-keyboard', 'address': 'other', 'options': 'compose:ralt', 'layout': 'us'}
    config = {'source': '', 'bind_policy': False, 'file': None}
    commands = []

    async def hyprctl(*args):
        if args == ('-j', 'devices'): return json.dumps({'keyboards': [physical, keyboard]})
        if args == ('-j', 'getoption', 'input.kb_file'): return json.dumps({'str': config['source'] or '[[EMPTY]]'})
        commands.append(args)
        if args[0] == 'eval':
            if legacy: return 'unknown request\n'
            assert args[1].startswith('hl.device({name=' + json.dumps(NAME) + ', resolve_binds_by_sym=true, kb_file=')
            value = json.loads(args[1].split('kb_file=', 1)[1][:-2])
            config['bind_policy'] = True
        else:
            assert args[0] == 'keyword'
            if args[1] == f'device[{NAME}]:resolve_binds_by_sym':
                assert args[2] == 'true'
                config['bind_policy'] = True
                return 'ok\n'
            assert args[1] == f'device[{NAME}]:kb_file'
            value = args[2]
        config['file'] = value
        if accept:
            xkb = XKB()
            with xkb.context() as context, xkb.keymap(context, text=Path(value).read_text()) as loaded:
                keyboard['active_keymap'] = xkb.keymap_layout_get_name(loaded, 0).decode()
        return 'ok\n'

    mapping.hyprctl = hyprctl
    return mapping, keyboard, physical, commands, config


@pytest.mark.parametrize('legacy', [False, True])
def test_complete_map_is_scoped_preserves_rmlvo_and_retires_without_inverse_setters(legacy):
    async def check():
        mapping, keyboard, physical, commands, config = fixture_map('caps:escape,compose:ralt', legacy=legacy)
        before, physical_before = deepcopy(keyboard), deepcopy(physical)
        await mapping.install()
        assert keyboard['options'] == before['options'] and keyboard['layout'] == 'de'
        assert keyboard['active_keymap'] in mapping.compiled.layout_names and config['bind_policy']
        path = mapping.path
        assert path.is_file() and path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        count = len(commands)
        await mapping.restore()
        assert not path.exists() and len(commands) == count and physical == physical_before
        await mapping.restore()
    asyncio.run(check())


@pytest.mark.parametrize('change', ['user-options', 'layout', 'recreated-device', 'reload', 'edited-file', 'global-source'])
def test_changed_map_or_ownership_stops_verification_without_touching_new_user_state(change):
    async def check():
        mapping, keyboard, physical, commands, config = fixture_map()
        await mapping.install()
        count = len(commands)
        if change == 'user-options': keyboard['options'] = 'caps:ctrl_modifier'
        elif change == 'layout': keyboard['layout'] = 'us'
        elif change == 'recreated-device': keyboard['address'] = 'new-device'
        elif change == 'reload': keyboard['active_keymap'] = 'German'
        elif change == 'edited-file': mapping.path.write_text('new user value')
        else: config['source'] = '/new/custom/keymap'
        with pytest.raises(RuntimeError): await mapping.verify()
        changed = deepcopy(keyboard)
        await mapping.restore()
        assert len(commands) == count and keyboard == changed and physical['options'] == 'compose:ralt'
    asyncio.run(check())


def test_rejected_or_silently_fallback_setup_never_accepts_rmlvo_strings_as_keymap_proof():
    async def check():
        mapping, keyboard, _, commands, config = fixture_map(accept=False)
        with pytest.raises(RuntimeError, match='not retained'): await mapping.install()
        assert keyboard['options'] == '' and keyboard['active_keymap'] == 'German'
        assert config['file'] and not Path(config['file']).exists() and mapping.directory is None
        assert len(commands) == 1
    asyncio.run(check())


@pytest.mark.parametrize('name', ['physical-keyboard', 'razer-naga-v3-pro-keyboard',
    'gillete-virtual-input', 'gillete-virtual-input-test', 'gillete-virtual-input-' + 'g' * 32])
def test_physical_or_reusable_names_cannot_receive_a_keymap(name):
    with pytest.raises(ValueError, match='unique owned'): KeyboardMap(name)


def test_inherited_custom_file_is_compiled_and_watched_without_editing_it(tmp_path):
    async def check():
        mapping, keyboard, _, _, config = fixture_map()
        xkb = XKB()
        names = {'rules': 'evdev', 'model': 'pc105', 'layout': 'us', 'variant': '', 'options': 'caps:escape'}
        with xkb.context() as context, xkb.keymap(context, names=names) as keymap:
            original = xkb.text(keymap, 1)
        source = tmp_path / 'user.xkb'
        source.write_text(original)
        config['source'] = str(source)
        await mapping.install()
        assert source.read_text() == original and mapping.source_hash
        assert keyboard['active_keymap'].endswith('English (US)')
        source.write_text(original + '\n// a user edit\n')
        with pytest.raises(RuntimeError, match='Inherited custom keymap changed'): await mapping.verify()
        await mapping.restore()
        assert source.is_file()
    asyncio.run(check())


def test_relative_custom_file_blocks_before_any_mutation():
    async def check():
        mapping, _, _, commands, config = fixture_map()
        config['source'] = 'relative/user.xkb'
        with pytest.raises(RuntimeError, match='absolute inherited'): await mapping.install()
        assert not commands and mapping.directory is None
    asyncio.run(check())


@pytest.mark.parametrize('kind', ['fifo', 'directory'])
def test_special_files_cannot_block_keyboard_preparation_or_watchers(tmp_path, kind):
    path = tmp_path / 'not-a-keymap'
    if kind == 'fifo': os.mkfifo(path)
    else: path.mkdir()
    with pytest.raises(RuntimeError, match='regular files'): KeyboardMap.read_source(path)


def test_keyboard_change_during_cpu_preparation_prevents_all_setters(monkeypatch):
    import gillete.keyboard_map as module
    async def check():
        mapping, keyboard, _, commands, _ = fixture_map()
        compile = module.compile_keymap
        def changed(*args, **kwargs):
            result = compile(*args, **kwargs)
            keyboard['address'] = 'another-owner'
            return result
        monkeypatch.setattr(module, 'compile_keymap', changed)
        with pytest.raises(RuntimeError, match='changed during'): await mapping.install()
        assert not commands and mapping.directory is None
    asyncio.run(check())


def test_virtual_producer_uses_a_unique_name_and_closes_before_map_retirement(monkeypatch):
    from gillete import runtime
    outputs, calls = [], []
    class Device:
        def __init__(self, events, **kwargs): outputs.append(kwargs)
        def close(self): calls.append('close')
    monkeypatch.setattr(runtime, 'UInput', Device)
    one, two = runtime.UInputOutput('00e8'), runtime.UInputOutput('00e8')
    assert outputs[0]['name'] != outputs[1]['name'] and one.keymap.name != two.keymap.name
    one.close()
    one.close()
    two.close()
    assert calls == ['close', 'close']
