from evdev import ecodes
import pytest
from gillete.model import key_code
from gillete.shortcuts import friendly_key, parse_key


@pytest.mark.parametrize('name',['BTN_SIDE','BTN_EXTRA','BTN_BACK','BTN_FORWARD','BTN_TASK','BTN_0','BTN_A','KEY_LEFTCTRL','KEY_PAGEUP'])
def test_editable_button_labels_preserve_event_identity(name):
    assert key_code(parse_key(friendly_key(name))) == key_code(name)


def test_every_accepted_linux_key_label_round_trips():
    for name in ecodes.ecodes:
        try:
            code = key_code(name)
        except ValueError:
            continue
        assert key_code(parse_key(friendly_key(name))) == code, name
