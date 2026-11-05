import pytest

from gillete.protocol import ProtocolError
from gillete.raw_keyboard import keyboard_usages


def test_boot_and_composite_f24_press_and_release():
    assert keyboard_usages(bytes.fromhex("0000730000000000"), numbered=False) == {0x73}
    assert keyboard_usages(bytes(8), numbered=False) == set()
    assert keyboard_usages(bytes([1, 0, 0x73]) + bytes(13), numbered=True) == {0x73}
    assert keyboard_usages(bytes([1]) + bytes(15), numbered=True) == set()


def test_composite_other_reports_are_not_misclassified_as_keyboard():
    assert keyboard_usages(bytes([4, 0x73]) + bytes(14), numbered=True) is None
    assert keyboard_usages(bytes([5, 0x73]) + bytes(14), numbered=True) is None


def test_modifiers_and_rollover():
    assert keyboard_usages(bytes.fromhex("0300040000000000"), numbered=False) == {0xE0, 0xE1, 4}
    with pytest.raises(ProtocolError):
        keyboard_usages(bytes.fromhex("0000010101010101"), numbered=False)
    with pytest.raises(ProtocolError):
        keyboard_usages(bytes([1, 0]), numbered=True)
