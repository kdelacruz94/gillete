import struct

import pytest

from gillete.model import MODELS
from gillete.protocol import ProtocolError
from gillete.reports import decode


def test_v3_captured_side_and_body_button_reports():
    for number, usage in enumerate((*range(0x1E, 0x28), 0x2D, 0x2E), 1):
        assert decode(MODELS[1], '02', bytes((0, 0, usage)) + bytes(5)).controls == {f'side_{number}'}
        assert not decode(MODELS[1], '02', bytes(8)).controls
    for usage, control in ((0x20, 'dpi_up'), (0x21, 'dpi_down'), (0x59, 'ring_finger'),
                           (0x54, 'top_front'), (0xD2, 'top_rear'), (0x50, 'profile_button')):
        assert decode(MODELS[1], '01', bytes((4, usage)) + bytes(14)).controls == {control}
        assert not decode(MODELS[1], '01', b'\4' + bytes(15)).controls
    assert decode(MODELS[1], '01', bytes.fromhex('050e0300000000000000000000000000')) is None


def test_pointer_hold_release_motion_and_scroll_remain_distinct():
    for bits, control in ((1, 'left_click'), (2, 'right_click'), (4, 'wheel_click'),
                          (0x20, 'wheel_tilt_left'), (0x40, 'wheel_tilt_right')):
        frame = decode(MODELS[1], '00', struct.pack('<BBbbhh', bits, 0, 0, 0, -123, 456))
        assert frame.controls == {control}
        assert frame.motion == (('REL_X', -123), ('REL_Y', 456))
        assert not decode(MODELS[1], '00', bytes(8)).controls
    frame = decode(MODELS[1], '00', struct.pack('<BBbbhh', 0x20, 0, -1, 2, 0, 0))
    assert frame.pulses == (('wheel_up', 2),)  # no duplicate tilt
    assert decode(MODELS[1], '00', struct.pack('<BBbbhh', 0, 0, 0, -1, 0, 0)).pulses == (('wheel_down', 1),)


def test_openrazer_translated_controls_and_unknown_inputs():
    frame = decode(MODELS[0], '01', bytes((1, 0, 0x68, 0x69)) + bytes(12))
    assert frame.controls == {'dpi_up', 'dpi_down'}
    with pytest.raises(ProtocolError):
        decode(MODELS[0], '01', bytes((4, 0x59)) + bytes(14))
    with pytest.raises(ProtocolError):
        decode(MODELS[1], '00', b'\x08' + bytes(7))
    with pytest.raises(ProtocolError):
        decode(MODELS[1], '02', bytes((0, 0, 1)) + bytes(5))
