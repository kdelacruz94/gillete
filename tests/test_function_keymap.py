from evdev import ecodes
import re
import pytest

from gillete.function_keymap import MAX_TEXT, REAL_MODIFIERS, XKB, compile_keymap, symbols_end


MARKER = 'gillete-fkeys-offline-test'


def mask(xkb, keymap, *names):
    return sum(1 << xkb.keymap_mod_get_index(keymap, name.encode()) for name in names)


@pytest.mark.parametrize('format', [1, 2])
def test_real_library_removes_modified_f23_and_f24_aliases(format):
    names = {'rules': 'evdev', 'model': 'pc105', 'layout': 'us', 'variant': '',
             'options': 'fkeys:basic_13-24'}
    result = compile_keymap(names, marker=MARKER, format=format)
    assert result.verified_combinations == 12 * 256
    assert result.format == format and len(result.text.encode()) < MAX_TEXT
    xkb = XKB()
    with xkb.context() as context, xkb.keymap(context, names=names, format=format) as original, \
            xkb.keymap(context, text=result.text, format=format) as corrected, \
            xkb.state(original) as old, xkb.state(corrected) as new:
        for number, modifiers, old_symbol in ((23, ('Shift', 'Mod4'), 'XF86Assistant'),
                                              (24, ('Control', 'Mod4'), 'XF86TouchpadToggle')):
            code = getattr(ecodes, f'KEY_F{number}') + 8
            for state, keymap in ((old, original), (new, corrected)):
                xkb.state_update_mask(state, mask(xkb, keymap, *modifiers), 0, 0, 0, 0, 0)
            assert xkb.state_key_get_one_sym(old, code) == xkb.keysym_from_name(old_symbol.encode(), 0)
            assert xkb.state_key_get_one_sym(new, code) == xkb.keysym_from_name(f'F{number}'.encode(), 0)
            assert not xkb.state_key_get_consumed_mods(new, code)
        assert xkb.keymap_layout_get_name(corrected, 0).decode() == result.layout_names[0]
        assert result.layout_names[0].startswith(MARKER + ': ')


@pytest.mark.parametrize('layout,variant,options', [
    ('us,de', ',nodeadkeys', 'caps:escape,compose:ralt'),
    ('us,ru', ',phonetic', 'grp:alt_shift_toggle'),
    ('us', 'dvorak', 'ctrl:swapcaps'),
])
def test_layouts_options_regular_keys_media_keys_and_modifiers_are_preserved(layout, variant, options):
    names = {'rules': 'evdev', 'model': 'pc105', 'layout': layout, 'variant': variant, 'options': options}
    result = compile_keymap(names, marker=MARKER)
    xkb = XKB()
    with xkb.context() as context, xkb.keymap(context, names=names) as original, \
            xkb.keymap(context, text=result.text) as corrected, \
            xkb.state(original) as old, xkb.state(corrected) as new:
        layouts = xkb.keymap_num_layouts(original)
        assert xkb.keymap_num_layouts(corrected) == layouts == len(layout.split(','))
        assert result.verified_combinations == layouts * 12 * 256
        codes = [ecodes.ecodes[name] + 8 for name in ('KEY_A', 'KEY_Z', 'KEY_K', 'KEY_M', 'KEY_1', 'KEY_CAPSLOCK',
            'KEY_LEFTCTRL', 'KEY_LEFTSHIFT', 'KEY_LEFTMETA', 'KEY_RIGHTALT', 'KEY_VOLUMEUP', 'KEY_F1', 'KEY_F12')]
        for group in range(layouts):
            for bits in range(256):
                for state, keymap in ((old, original), (new, corrected)):
                    held = [name for i, name in enumerate(REAL_MODIFIERS) if bits & (1 << i)]
                    xkb.state_update_mask(state, mask(xkb, keymap, *held), 0, 0, 0, 0, group)
                for code in codes:
                    assert xkb.state_key_get_one_sym(old, code) == xkb.state_key_get_one_sym(new, code)
                    assert xkb.state_key_get_consumed_mods(old, code) == xkb.state_key_get_consumed_mods(new, code)
                    assert xkb.keymap_key_repeats(original, code) == xkb.keymap_key_repeats(corrected, code)
        # A corrected function key in every group keeps the application's
        # actual modifier state; this is not a release-and-repress workaround.
        for group in range(layouts):
            for number in range(13, 25):
                code = getattr(ecodes, f'KEY_F{number}') + 8
                xkb.state_update_mask(new, 255, 0, 0, 0, 0, group)
                assert xkb.state_key_get_one_sym(new, code) == xkb.keysym_from_name(f'F{number}'.encode(), 0)


def test_custom_compiled_source_preserves_other_keys_and_clears_function_key_modifier_actions():
    xkb = XKB()
    names = {'rules': 'evdev', 'model': 'pc105', 'layout': 'us', 'variant': '', 'options': ''}
    with xkb.context() as context, xkb.keymap(context, names=names) as original:
        text = xkb.text(original, 1)
    end = symbols_end(text)
    text = (text[:end] + '\nreplace key <AD01> {[Greek_alpha, Greek_ALPHA]};\n'
            'replace key <FK23> { [Super_L], actions[Group1]=[SetMods(modifiers=Mod4)], repeat=false };\n'
            'modifier_map Mod4 { <FK23> };\n' + text[end:])
    result = compile_keymap({}, marker=MARKER, source=text)
    with xkb.context() as context, xkb.keymap(context, text=result.text) as corrected, xkb.state(corrected) as state:
        assert xkb.state_key_get_one_sym(state, ecodes.KEY_Q + 8) == xkb.keysym_from_name(b'Greek_alpha', 0)
        assert not xkb.keymap_key_repeats(corrected, ecodes.KEY_F23 + 8)
        assert xkb.state_key_get_one_sym(state, ecodes.KEY_F23 + 8) == xkb.keysym_from_name(b'F23', 0)
        xkb.state_update_key(state, ecodes.KEY_F23 + 8, 1)
        assert not xkb.state_serialize_mods(state, 8)


@pytest.mark.parametrize('names,marker,source,format', [
    ({'layout': 'layout-that-does-not-exist'}, MARKER, None, 1),
    ({'layout': 'us', 'variant': 'variant-that-does-not-exist'}, MARKER, None, 1),
    ({'options': 'option:that-does-not-exist'}, MARKER, None, 1),
    ({'layout': 'us,de,ru,fr,es'}, MARKER, None, 1),
    ({'layout': 42}, MARKER, None, 1), ({'options': 'caps:escape\0'}, MARKER, None, 1),
    ({'extra': 'value'}, MARKER, None, 1), ({}, 'unowned-map', None, 1),
    ({}, MARKER, '\0', 1), ({}, MARKER, 'x' * (MAX_TEXT + 1), 1),
    ({}, MARKER, 'not a valid keymap', 1), ({}, MARKER, None, True),
])
def test_invalid_input_does_not_fall_back_to_an_unrelated_us_map(names, marker, source, format):
    with pytest.raises((ValueError, RuntimeError)):
        compile_keymap(names, marker=marker, source=source, format=format)


def test_symbols_locator_ignores_fake_sections_and_braces_in_names_and_comments():
    text = ('xkb_keymap { xkb_keycodes "xkb_symbols { fake }" { }; '
            '/* xkb_symbols { } */ xkb_symbols "name { }" { '
            'key <FK23> { [ F23 ] }; // }\n }; };')
    assert text[symbols_end(text):] == '}; };'
    with pytest.raises(ValueError): symbols_end('xkb_keymap { xkb_symbols {')


def test_format_two_keeps_more_than_four_groups():
    xkb = XKB()
    names = {'rules': 'evdev', 'model': 'pc105', 'layout': 'us,de,ru,fr', 'variant': '', 'options': ''}
    with xkb.context() as context, xkb.keymap(context, names=names, format=2) as keymap:
        source = xkb.text(keymap, 2)
    end = symbols_end(source)
    source = source[:end] + '\nname[Group5]="Extra"; key <AD01> { symbols[Group5]=[a,A] };\n' + source[end:]
    result = compile_keymap({}, marker=MARKER, format=2, source=source)
    assert len(result.layout_names) == 5 and result.verified_combinations == 5 * 12 * 256


def test_rmlvo_group_limit_cannot_silently_drop_an_extra_requested_layout():
    with pytest.raises(ValueError):
        compile_keymap({'layout': 'us,de,ru,fr,es'}, marker=MARKER, format=2)


def test_custom_non_evdev_function_keycodes_cannot_validate_the_wrong_linux_keys():
    xkb = XKB()
    names = {'rules': 'evdev', 'model': 'pc105', 'layout': 'us', 'variant': '', 'options': ''}
    with xkb.context() as context, xkb.keymap(context, names=names) as keymap:
        source = xkb.text(keymap, 1)
    source, count = re.subn(r'(<FK2[34]>\s*=\s*)(\d+)',
                           lambda m: m[1] + str(int(m[2]) + (1 if 'FK23' in m[1] else -1)), source)
    assert count == 2
    with pytest.raises(ValueError, match='differ from Linux evdev'):
        compile_keymap({}, marker=MARKER, source=source)
