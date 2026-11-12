"""Known software prerequisites for actions that call a device control adapter.

Available means the implemented adapter has the required readback, not that
physical setter behavior or persistence has completed hardware acceptance.
"""

from dataclasses import dataclass

from .hypershift import resolve_action
from .model import MODEL_CONTROLS, MODELS
from .protocol import ProtocolError
from .settings import Stages, decode_dpi


def decode_wheel_mode(raw):
    if not isinstance(raw, bytes) or len(raw) != 2 or raw[0] != 1 or raw[1] not in (0, 1, 2):
        raise ProtocolError('Unrecognized wheel-mode response')
    return raw[1]


@dataclass(frozen=True)
class Support:
    available: bool | None
    message: str

    @property
    def text(self):
        prefix = 'Software action unavailable: ' if self.available is False else 'Needs a mouse read: ' if self.available is None else ''
        return prefix + self.message


def support(action, model, snapshot=None):
    if action is None or action.kind not in ('dpi', 'device'):
        return None
    if action.kind == 'device' and model != MODELS[1]:
        return Support(False, 'Native wheel-mode and onboard-slot actions require the Naga V3 Pro. '
                              'Choose another V2 mapping or add a V2 override to a shared assignment.')
    if snapshot is None or snapshot.model != model:
        return Support(None, 'Read this mouse to check its DPI stages, wheel mode or assigned onboard slots.')
    expected = (0xB4,) if model == MODELS[0] else (0xE7, 0xE8)
    if snapshot.product not in expected:
        return Support(False, 'The mouse read does not match this model. Read the selected mouse again.')
    if snapshot.product == 0xE7:
        return Support(False, 'Wired DPI, wheel-mode and onboard-slot writes still need hardware validation. '
                              'Choose a keyboard/mouse action, Linux profile switch or disable this assignment.')
    if action.kind == 'dpi':
        try:
            decode_dpi(bytes.fromhex(snapshot.settings['dpi']), snapshot.product)
            Stages.decode(bytes.fromhex(snapshot.settings['stages']), snapshot.product)
        except (KeyError, TypeError, ValueError):
            return Support(False, 'DPI and stage values must be read successfully before using a DPI-stage button. '
                                  'The last read is missing or unrecognized. Read the mouse again or choose another software mapping.')
        return Support(True, 'Uses the mouse’s stored DPI stages. Hardware-write validation is pending.')
    if action.target == 'onboard_profile_cycle':
        if not snapshot.assigned or snapshot.active not in snapshot.assigned:
            return Support(False, 'Read a consistent assigned-slot inventory before using this action.')
        if len(snapshot.assigned) == 1:
            return Support(True, 'No effect: only one onboard slot is assigned. Use Switch profile for Linux profiles.')
        return Support(False, 'Cycling multiple onboard slots from the Linux service is not implemented. '
                              'Use Switch profile for Linux profiles, or choose another software mapping.')
    try:
        decode_wheel_mode(bytes.fromhex(snapshot.metadata['wheel_mode']))
    except (KeyError, TypeError, ValueError):
        return Support(False, 'Wheel mode must be read successfully before using native wheel-mode cycling. '
                              'The last read is missing or unrecognized. Read the mouse again or choose another software mapping.')
    return Support(True, 'Cycles the mouse’s wheel modes. Hardware-write validation is pending.')


def issues(profile, model, stored, snapshot):
    result = []
    for control in MODEL_CONTROLS[model]:
        for shifted in (False, True):
            action = resolve_action(profile, model, control, shifted, stored)
            state = support(action, model, snapshot)
            if state is not None and state.available is not True:
                result.append(f'{control} ({"HyperShift" if shifted else "normal"}): {state.message}')
    return result
