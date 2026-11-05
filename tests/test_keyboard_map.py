import asyncio
import json

import pytest

from gillete.keyboard_map import FUNCTION_KEYS, KeyboardMap


def fixture_map(options='', accept=True, legacy=False):
    mapping = KeyboardMap('gillete-virtual-input-test', signature='test')
    keyboard = {'name': mapping.name, 'address': 'own', 'options': options, 'layout': 'de'}
    physical = {'name': 'physical-keyboard', 'address': 'other', 'options': 'compose:ralt', 'layout': 'us'}
    commands = []

    async def hyprctl(*args):
        if args == ('-j', 'devices'):
            return json.dumps({'keyboards': [physical, keyboard]})
        commands.append(args)
        if args[0] == 'eval':
            if legacy:
                return 'unknown request\n'
            assert args[1].startswith('hl.device({name="gillete-virtual-input-test", resolve_binds_by_sym=true, kb_options=')
            value = json.loads(args[1].split('kb_options=', 1)[1][:-2])
        else:
            if args[1] == 'device[gillete-virtual-input-test]:resolve_binds_by_sym':
                assert args[2] == 'true'
                return 'ok\n'
            assert args[:2] == ('keyword', 'device[gillete-virtual-input-test]:kb_options')
            value = args[2]
        if accept:
            keyboard['options'] = value
        return 'ok\n'

    mapping.hyprctl = hyprctl
    return mapping, keyboard, physical, commands


@pytest.mark.parametrize('legacy', [False, True])
def test_function_key_option_is_scoped_preserves_options_and_restores(legacy):
    async def check():
        mapping, keyboard, physical, commands = fixture_map('caps:escape,compose:ralt', legacy=legacy)
        await mapping.install()
        assert keyboard['options'] == 'caps:escape,compose:ralt,' + FUNCTION_KEYS
        assert keyboard['layout'] == 'de'
        await mapping.restore()
        assert keyboard['options'] == 'caps:escape,compose:ralt'
        assert physical == {'name': 'physical-keyboard', 'address': 'other', 'options': 'compose:ralt', 'layout': 'us'}
        assert commands
    asyncio.run(check())


@pytest.mark.parametrize('change', ['user-edit', 'recreated-device'])
def test_cleanup_does_not_replace_new_user_options_or_a_different_device(change):
    async def check():
        mapping, keyboard, _, commands = fixture_map()
        await mapping.install()
        count = len(commands)
        if change == 'user-edit':
            keyboard['options'] = 'caps:ctrl_modifier'
        else:
            keyboard['address'] = 'new-device'
        with pytest.raises(RuntimeError, match='not retained'):
            await mapping.verify()
        await mapping.restore()
        assert len(commands) == count
    asyncio.run(check())


def test_rejected_setup_never_reports_success():
    async def check():
        mapping, keyboard, _, _ = fixture_map(accept=False)
        with pytest.raises(RuntimeError, match='not retained'):
            await mapping.install()
        assert keyboard['options'] == ''
    asyncio.run(check())


def test_preexisting_correction_is_not_duplicated_or_removed():
    async def check():
        mapping, keyboard, _, commands = fixture_map(FUNCTION_KEYS)
        await mapping.install()
        count = len(commands)
        await mapping.restore()
        assert len(commands) == count
        assert keyboard['options'] == FUNCTION_KEYS
    asyncio.run(check())
