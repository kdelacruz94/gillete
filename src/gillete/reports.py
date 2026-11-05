"""Physical controls from Naga receiver reports in verified driver mode.

V3 correspondence was captured locally in v3-driver-capture1 on the 12-button
plate. V2 pointer/keyboard layouts are locally read descriptors; its driver-mode
button correspondence still needs the separate physical acceptance test.
"""

from dataclasses import dataclass
import struct

from .model import MODELS
from .protocol import ProtocolError
from .raw_keyboard import keyboard_usages


@dataclass(frozen=True)
class Frame:
    source: str
    controls: frozenset[str] = frozenset()
    motion: tuple[tuple[str, int], ...] = ()
    pulses: tuple[tuple[str, int], ...] = ()


SIDE_USAGES = dict(zip((*range(0x1E, 0x28), 0x2D, 0x2E), (f'side_{i}' for i in range(1, 13))))
VENDOR = {0x20: 'dpi_up', 0x21: 'dpi_down', 0x22: 'wheel_tilt_left', 0x23: 'wheel_tilt_right',
          0x59: 'ring_finger', 0x54: 'top_front', 0xD2: 'top_rear', 0x50: 'profile_button'}
TRANSLATED = {0x68: 'dpi_up', 0x69: 'dpi_down', 0x6A: 'wheel_tilt_left', 0x6B: 'wheel_tilt_right',
              0x6C: 'ring_finger', 0x54: 'top_front', 0x6D: 'top_rear', 0x50: 'profile_button'}
BUTTONS = {1: 'left_click', 2: 'right_click', 4: 'wheel_click',
           0x20: 'wheel_tilt_left', 0x40: 'wheel_tilt_right'}
V3_ONLY = {'ring_finger', 'top_front', 'top_rear', 'profile_button'}


def mapped(usages, mapping, model):
    if set(usages) - mapping.keys():
        raise ProtocolError('Unrecognized button report in driver mode')
    controls = frozenset(mapping[u] for u in usages)
    if model == MODELS[0] and controls & V3_ONLY:
        raise ProtocolError('V3-only control appeared on the V2')
    return controls


def decode(model: str, interface: str, raw: bytes) -> Frame | None:
    if model not in MODELS or not raw:
        raise ProtocolError('Unknown mouse or empty HID input')
    if interface == '00':
        if len(raw) != 8:
            raise ProtocolError('Unknown pointer report length')
        buttons, reserved, pan, wheel, x, y = struct.unpack('<BBbbhh', raw)
        if reserved or buttons & ~sum(BUTTONS):
            raise ProtocolError('Unsupported button plate or pointer report bits')
        held = frozenset(control for bit, control in BUTTONS.items() if buttons & bit)
        motion = tuple((axis, value) for axis, value in (('REL_X', x), ('REL_Y', y)) if value)
        pulses = []
        if wheel:
            pulses.append(('wheel_up' if wheel > 0 else 'wheel_down', abs(wheel)))
        if pan:
            # A tilt may have both a state bit and a repeated scroll value.
            # Route the physical held control only once in that case.
            control = 'wheel_tilt_right' if pan > 0 else 'wheel_tilt_left'
            if control not in held:
                pulses.append((control, abs(pan)))
        return Frame('00:pointer', held, motion, tuple(pulses))
    if interface == '02':
        return Frame('02:keyboard', mapped(keyboard_usages(raw, numbered=False), SIDE_USAGES, model))
    if interface == '01':
        if raw[0] == 4:
            if len(raw) != 16:
                raise ProtocolError('Unknown vendor-button report length')
            return Frame('01:vendor', mapped(set(raw[1:]) - {0}, VENDOR, model))
        if raw[0] == 1:
            return Frame('01:keyboard', mapped(keyboard_usages(raw, numbered=True), TRANSLATED, model))
        # Reports 5/8/9 carry device-state notifications, not physical presses.
        if raw[0] in (5, 8, 9) and len(raw) == 16:
            return None
        raise ProtocolError('Unexpected composite HID report in driver mode')
    raise ProtocolError('Unknown input interface')
