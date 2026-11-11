"""Interpret only exact known firmware functions for software execution.

Only a separately read, verified V3 once-only single-key macro body can resolve
a macro reference. Other firmware macros/turbo encodings remain recoverable
raw bytes. They are never guessed or replaced with factory defaults.
"""

from .compile_onboard import CONTROL_IDS, MEDIA, MODIFIERS, MOUSE, USAGES, encode_action
from .hypershift import resolve_action
from .model import Action, MODEL_CONTROLS, MODELS
from .onboard import Location


def decode(function: bytes, model: str) -> Action | None:
    if len(function) != 7:
        return None
    candidates = [Action('disabled'), Action('hypershift', playback='held'),
                  Action('dpi', target='up'), Action('dpi', target='down')]
    if model == MODELS[1]:
        candidates.extend(Action('device', target=target) for target in ('wheel_mode_cycle', 'onboard_profile_cycle'))
    candidates.extend(Action('keys', keys=(key,)) for key in (*MOUSE, *MEDIA))
    candidates.extend(Action('scroll', axis=axis, value=value) for axis in ('REL_WHEEL', 'REL_HWHEEL') for value in (-1, 1))
    normalized = function
    if function == bytes.fromhex('00010000000000'):
        return Action('disabled')
    if function[:2] in (b'\x02\x01', b'\x02\x02'):
        key = next((key for key, usage in USAGES.items() if usage == function[3]), None)
        if key is not None:
            keys = tuple(name for name, bit in MODIFIERS.items() if function[2] & (1 << bit)) + (key,)
            if len(set(keys)) == len(keys):
                candidates.append(Action('keys', keys=keys))
        normalized = b'\x02\x02' + function[2:]
    for candidate in candidates:
        if encode_action(candidate, model) == normalized:
            return candidate
    return None


def from_snapshot(snapshot):
    values, unknown = {}, {}
    for control, identifier in CONTROL_IDS[snapshot.model].items():
        for shifted in (False, True):
            function = snapshot.baseline[Location(snapshot.bank, identifier, int(shifted))]
            action = decode(function, snapshot.model)
            if action is None:
                from .stored_native import action as native_action
                action = native_action(snapshot, function)
            if action is None:
                unknown[control, shifted] = function
            else:
                values[control, shifted] = action
    return values, unknown


def unresolved(profile, model, stored):
    return [(control, shifted) for control in MODEL_CONTROLS[model] for shifted in (False, True)
            if resolve_action(profile, model, control, shifted, stored) is None]
