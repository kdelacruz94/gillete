"""Compile supported actions to stored bindings; never silently omit software actions."""

from dataclasses import dataclass

from .model import Action, MODEL_CONTROLS, MODELS, Profile
from .hypershift import PULSE_CONTROLS, shifted_controls
from .onboard import Location
from .protocol import ProtocolError, V2_CONTROLS


V3_CONTROLS = {**V2_CONTROLS, "ring_finger": 0x39, "top_front": 0x6A,
               "top_rear": 0x80, "profile_button": 0x0E}
CONTROL_IDS = {MODELS[0]: V2_CONTROLS, MODELS[1]: V3_CONTROLS}
# V3 physical correspondence is documented by OpenSnek's pinned 2026-10-17
# capture; local normal/shifted side-12 programming is verified separately.
MODIFIERS = dict(zip(("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_LEFTALT", "KEY_LEFTMETA",
                      "KEY_RIGHTCTRL", "KEY_RIGHTSHIFT", "KEY_RIGHTALT", "KEY_RIGHTMETA"), range(8)))
USAGES = {**{f"KEY_{chr(65 + i)}": 4 + i for i in range(26)},
          **{f"KEY_{digit}": 0x1E + i for i, digit in enumerate("1234567890")},
          **{f"KEY_F{i}": 0x39 + i for i in range(1, 13)},
          **{f"KEY_F{i}": 0x68 + i - 13 for i in range(13, 25)},
          **{key: 0xE0 + bit for key, bit in MODIFIERS.items()},
          **dict(zip(("KEY_ENTER", "KEY_ESC", "KEY_BACKSPACE", "KEY_TAB", "KEY_SPACE",
                      "KEY_MINUS", "KEY_EQUAL", "KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_BACKSLASH"), range(0x28, 0x32))),
          **dict(zip(("KEY_SEMICOLON", "KEY_APOSTROPHE", "KEY_GRAVE", "KEY_COMMA", "KEY_DOT", "KEY_SLASH", "KEY_CAPSLOCK"), range(0x33, 0x3A))),
          **dict(zip(("KEY_INSERT", "KEY_HOME", "KEY_PAGEUP", "KEY_DELETE", "KEY_END", "KEY_PAGEDOWN", "KEY_RIGHT", "KEY_LEFT", "KEY_DOWN", "KEY_UP"), range(0x49, 0x53))),
          "KEY_SYSRQ": 0x46, "KEY_SCROLLLOCK": 0x47, "KEY_PAUSE": 0x48,
          "KEY_NUMLOCK": 0x53, "KEY_KPSLASH": 0x54, "KEY_KPASTERISK": 0x55,
          "KEY_KPMINUS": 0x56, "KEY_KPPLUS": 0x57, "KEY_KPENTER": 0x58,
          **{f"KEY_KP{i}": 0x58 + i for i in range(1, 10)}, "KEY_KP0": 0x62,
          "KEY_KPDOT": 0x63, "KEY_102ND": 0x64, "KEY_COMPOSE": 0x65}
MEDIA = {"KEY_VOLUMEUP": 0xE9, "KEY_VOLUMEDOWN": 0xEA, "KEY_MUTE": 0xE2,
         "KEY_PLAYPAUSE": 0xCD, "KEY_NEXTSONG": 0xB5, "KEY_PREVIOUSSONG": 0xB6}
MOUSE = {"BTN_LEFT": 1, "BTN_RIGHT": 2, "BTN_MIDDLE": 3, "BTN_SIDE": 4, "BTN_EXTRA": 5}


class SoftwareOnly(ValueError):
    pass


def describe_function(function: bytes) -> str:
    """Conservative display decoding; unrecognized bytes remain preserved."""
    from .shortcuts import friendly_key
    if len(function) != 7:
        return "Unrecognized device action"
    if function == bytes(7) or function == bytes.fromhex("00010000000000"):
        return "Disabled"
    kind, size, a, b, c, d, e = function
    if kind == 2 and size in (1, 2) and not (c or d or e):
        key = next((key for key, usage in USAGES.items() if usage == b), None)
        if key:
            modifiers = [key for key, bit in MODIFIERS.items() if a & (1 << bit)]
            return "+".join(friendly_key(k) for k in [*modifiers, key])
    if function == bytes((0x0C, 1, a, 0, 0, 0, 0)) and a in (1, 0x39):
        return "HyperShift (hold)"
    if kind == 1 and size == 1 and not (b or c or d or e):
        return {1: "Left click", 2: "Right click", 3: "Wheel click", 4: "Back", 5: "Forward",
                9: "Scroll up", 10: "Scroll down"}.get(a, "Device mouse action")
    if kind == 0x0E and size in (1, 3) and a in (0x68, 0x69) and (b, c, d, e) == (0, 0x14, 0, 0):
        return "Scroll left" if a == 0x68 else "Scroll right"
    if kind == 0x0A and size == 2 and not (a or c or d or e):
        key = next((key for key, usage in MEDIA.items() if usage == b), None)
        if key:
            return friendly_key(key)
    # These identify stored families only. Timing and referenced macro content
    # remain unresolved; stored_actions deliberately cannot execute them yet.
    # See docs/remaining-protocol-research.md for capture/source boundaries.
    if kind == 0x0D and size == 4 and not e:
        key = next((key for key, usage in USAGES.items() if usage == b), None)
        if key:
            modifiers = [name for name, bit in MODIFIERS.items() if a & (1 << bit)]
            chord = '+'.join(friendly_key(k) for k in [*modifiers, key])
            return f'Stored turbo {chord} · raw parameter 0x{c:02x}{d:02x} (timing unverified)'
    if kind == 0x0E and size == 3 and not (d or e):
        key = next((key for key, code in MOUSE.items() if code == a), None)
        if key:
            return f'Stored turbo {friendly_key(key)} · raw parameter 0x{b:02x}{c:02x} (timing unverified)'
    if kind == 5 and size == 2 and not (c or d or e):
        return f'Stored toggle-macro reference 0x{a:02x}{b:02x} (content unresolved)'
    if function == bytes.fromhex("06010100000000"):
        return "DPI up"
    if function == bytes.fromhex("06010200000000"):
        return "DPI down"
    if function == bytes.fromhex("07010400000000"):
        return "Cycle onboard profile"
    if function == bytes.fromhex("12010100000000"):
        return "Cycle wheel mode"
    return "Device-defined action"


def encode_action(action: Action, model: str) -> bytes:
    if action.kind == 'device':
        if model != MODELS[1]:
            raise SoftwareOnly('This native device action is supported only on the V3')
        return bytes.fromhex('12010100000000' if action.target == 'wheel_mode_cycle' else '07010400000000')
    if action.kind == "disabled":
        return bytes(7)
    if action.kind == "hypershift" and action.playback == "held":
        return bytes((0x0C, 1, 1 if model == MODELS[0] else 0x39, 0, 0, 0, 0))
    if action.kind == "dpi":
        return bytes((6, 1, 1 if action.target == "up" else 2, 0, 0, 0, 0))
    if action.kind == "scroll":
        if abs(action.value) != 1:
            raise SoftwareOnly("Multi-step scroll amounts require the service")
        if action.axis == "REL_WHEEL":
            return bytes((1, 1, 9 if action.value > 0 else 10, 0, 0, 0, 0))
        return bytes((0x0E, 3 if model == MODELS[0] else 1,
                      0x69 if action.value > 0 else 0x68, 0, 0x14, 0, 0))
    if action.kind == "keys":
        if len(action.keys) == 1 and action.keys[0] in MOUSE:
            return bytes((1, 1, MOUSE[action.keys[0]], 0, 0, 0, 0))
        if len(action.keys) == 1 and action.keys[0] in MEDIA:
            return bytes((0x0A, 2, 0, MEDIA[action.keys[0]], 0, 0, 0))
        if len(action.keys) == 1 and action.keys[0] in MODIFIERS:
            return bytes((2, 2, 0, USAGES[action.keys[0]], 0, 0, 0))
        regular = [key for key in action.keys if key not in MODIFIERS]
        if len(regular) != 1 or regular[0] not in USAGES:
            raise SoftwareOnly("Onboard keyboard chords need one supported key plus modifiers")
        mask = sum(1 << MODIFIERS[k] for k in action.keys if k in MODIFIERS)
        return bytes((2, 2, mask, USAGES[regular[0]], 0, 0, 0))
    raise SoftwareOnly(f"{action.kind} requires the Linux service or an explicit standalone replacement")


@dataclass
class OnboardPlan:
    model: str
    bank: int
    targets: dict[Location, bytes]
    issues: list[str]

    @property
    def writable(self):
        return bool(self.targets) and not self.issues


def compile_profile(profile: Profile, model: str, bank: int,
                    baseline: dict[Location, bytes]) -> OnboardPlan:
    if model not in MODELS or bank not in ((1,) if model == MODELS[0] else (1, 2, 3, 4, 5)):
        raise ProtocolError("Unknown model or stored bank")
    identifiers = CONTROL_IDS[model]
    required = {Location(bank, identifier, layer) for identifier in identifiers.values() for layer in (0, 1)}
    if not required <= baseline.keys() or any(len(baseline[k]) != 7 for k in required):
        raise ProtocolError("A complete normal/shifted snapshot of this bank is required")
    normal, issues = {}, []
    for control in MODEL_CONTROLS[model]:
        where = Location(bank, identifiers[control], 0)
        action = profile.resolve(model, control)
        if action.kind == "passthrough":
            normal[where] = baseline[where]
        else:
            try:
                normal[where] = encode_action(action, model)
                if control in PULSE_CONTROLS and action.kind == 'hypershift':
                    issues.append(f'{control}: held HyperShift needs a button that can be held; '
                                  'scroll-toggle HyperShift requires the Linux service')
            except SoftwareOnly as error:
                issues.append(f"{control} (normal): {error}")
    shifted = {}
    shift_function = encode_action(Action('hypershift', playback='held'), model)
    has_shift = any(normal.get(Location(bank, identifiers[c], 0)) == shift_function
                    for c in MODEL_CONTROLS[model] if c not in PULSE_CONTROLS)
    for control in MODEL_CONTROLS[model]:
        normal_where = Location(bank, identifiers[control], 0)
        shifted_where = Location(bank, identifiers[control], 1)
        if normal_where not in normal:
            continue
        action = profile.resolve(model, control, shifted=True)
        if normal[normal_where] == shift_function:
            shifted[shifted_where] = (baseline[shifted_where]
                                     if profile.resolve(model, control).kind == 'passthrough'
                                     else normal[normal_where])
        elif action.kind == "passthrough":
            # "Keep stored" preserves the user's existing Synapse assignment
            # on this layer. Explicit normal actions already inherit through
            # Profile.resolve when their shifted mapping is unassigned.
            shifted[shifted_where] = baseline[shifted_where]
        else:
            try:
                shifted[shifted_where] = encode_action(action, model)
            except SoftwareOnly as error:
                issues.append(f"{control} (HyperShift): {error}")
    if not has_shift and shifted_controls(profile, model):
        issues.append("Shifted mappings have no HyperShift trigger on this mouse")
    if normal.get(Location(bank, identifiers["left_click"], 0), b"\0")[0] == 0x0C and model == MODELS[0]:
        issues.append("V2 left-click as a firmware HyperShift trigger has not been validated")
    return OnboardPlan(model, bank, {**normal, **shifted}, issues)
