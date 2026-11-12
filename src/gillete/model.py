"""Versioned, validated configuration shared by the GUI and service."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from evdev import ecodes


class ConfigurationError(ValueError):
    pass


MODELS = ("naga_v2_hyperspeed", "naga_v3_pro")
COMMON_CONTROLS = (
    "left_click", "right_click", "wheel_click", "wheel_up", "wheel_down",
    "wheel_tilt_left", "wheel_tilt_right", "dpi_up", "dpi_down",
    *(f"side_{i}" for i in range(1, 13)),
)
MODEL_CONTROLS = {
    MODELS[0]: COMMON_CONTROLS,
    MODELS[1]: (*COMMON_CONTROLS, "ring_finger", "top_front", "top_rear", "profile_button"),
}
# This is a logical inventory, not a claim that every wire ID is verified.
CONTROLS = frozenset(c for controls in MODEL_CONTROLS.values() for c in controls)
ACTION_KINDS = frozenset({"passthrough", "disabled", "keys", "macro", "turbo",
                          "hypershift", "profile", "launch", "scroll", "dpi", "device"})
STANDALONE_KINDS = frozenset({'passthrough', 'disabled', 'keys', 'hypershift', 'scroll', 'dpi', 'device'})


def integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def key_code(name: str) -> int:
    if not isinstance(name, str) or not name.startswith(("KEY_", "BTN_")):
        raise ConfigurationError(f"Invalid Linux key name: {name!r}")
    value = ecodes.ecodes.get(name)
    if not isinstance(value, int) or name in {"KEY_RESERVED", "KEY_MAX", "KEY_CNT", "BTN_MISC"}:
        raise ConfigurationError(f"Unknown/invalid Linux key: {name}")
    return value


def object_fields(data: Any, allowed: set[str], context: str) -> dict:
    if not isinstance(data, dict) or set(data) - allowed:
        raise ConfigurationError(f"Invalid {context} fields")
    return data


@dataclass(frozen=True)
class Step:
    kind: str
    key: str = ""
    milliseconds: int = 0
    axis: str = ""
    value: int = 0

    def __post_init__(self):
        if self.kind not in {"down", "up", "wait", "relative"}:
            raise ConfigurationError("Unknown macro step kind")
        if self.kind in {"down", "up"}:
            key_code(self.key)
        elif self.kind == "wait":
            integer(self.milliseconds, "Delay", 0, 3_600_000)
        else:
            if self.axis not in {"REL_X", "REL_Y", "REL_WHEEL", "REL_HWHEEL"}:
                raise ConfigurationError("Unsupported relative axis")
            integer(self.value, "Relative value", -32767, 32767)

    @classmethod
    def parse(cls, data: Any) -> Step:
        fields = object_fields(data, {"kind", "key", "milliseconds", "axis", "value"}, "step")
        try:
            return cls(**fields)
        except TypeError as e:
            raise ConfigurationError("Malformed macro step") from e


@dataclass(frozen=True)
class Action:
    kind: str = "passthrough"
    keys: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()
    playback: str = "once"
    count: int = 1
    interval_ms: int = 100
    press_ms: int = 30
    target: str = ""
    argv: tuple[str, ...] = ()
    axis: str = "REL_WHEEL"
    value: int = 1
    desktop_id: str = ""

    def __post_init__(self):
        if self.kind not in ACTION_KINDS:
            raise ConfigurationError(f"Unknown action: {self.kind}")
        if not isinstance(self.desktop_id, str) or self.desktop_id and self.kind != 'launch':
            raise ConfigurationError('Desktop application IDs belong only to launch actions')
        if self.playback not in {"once", "count", "held", "toggle"}:
            raise ConfigurationError("Unknown playback mode")
        integer(self.count, "Repeat count", 1, 1_000_000)
        integer(self.interval_ms, "Interval", 0 if self.kind == 'macro' else 1, 3_600_000)
        integer(self.press_ms, "Press duration", 1, 60_000)
        if len(self.keys) > 32 or len(set(self.keys)) != len(self.keys):
            raise ConfigurationError("Keys must be distinct (maximum 32)")
        for key in self.keys:
            key_code(key)
        if self.kind in {"keys", "turbo"} and not self.keys:
            raise ConfigurationError("A key/chord is required")
        if self.kind == "turbo" and self.press_ms >= self.interval_ms:
            raise ConfigurationError("Turbo interval must exceed its press duration")
        if self.kind == "turbo" and self.playback not in {"held", "toggle"}:
            raise ConfigurationError("Turbo playback must be held or toggle")
        if self.kind == "hypershift" and self.playback not in {"held", "toggle"}:
            raise ConfigurationError("HyperShift must be held or toggle")
        if self.kind == "macro":
            if not 1 <= len(self.steps) <= 10000:
                raise ConfigurationError("Macros require 1..10000 steps")
            held: set[str] = set()
            for step in self.steps:
                if step.kind == "down":
                    if step.key in held:
                        raise ConfigurationError(f"Duplicate key-down: {step.key}")
                    held.add(step.key)
                elif step.kind == "up":
                    if step.key not in held:
                        raise ConfigurationError(f"Unmatched key-up: {step.key}")
                    held.remove(step.key)
            if held:
                raise ConfigurationError("A macro must release all of its keys")
        if self.kind == "profile" and (not isinstance(self.target, str) or not self.target):
            raise ConfigurationError("Choose a destination profile")
        if self.kind == "dpi" and self.target not in {"up", "down"}:
            raise ConfigurationError("Choose DPI up or down")
        if self.kind == "device" and self.target not in {"wheel_mode_cycle", "onboard_profile_cycle"}:
            raise ConfigurationError("Unknown native device action")
        if self.kind == "scroll":
            if self.axis not in {"REL_WHEEL", "REL_HWHEEL"}:
                raise ConfigurationError("Choose vertical or horizontal scrolling")
            integer(self.value, "Scroll amount", -120, 120)
            if not self.value:
                raise ConfigurationError("Scroll amount must be nonzero")
        if self.kind == "launch":
            if self.desktop_id:
                if (self.argv or not self.desktop_id.endswith('.desktop') or len(self.desktop_id) > 1024
                        or any(c in self.desktop_id for c in '/\\\0\r\n')):
                    raise ConfigurationError("Choose an installed application or an executable, not both")
            elif not self.argv or len(self.argv) > 128 or any(
                not isinstance(a, str) or "\0" in a or len(a) > 16384 for a in self.argv
            ) or not self.argv[0]:
                raise ConfigurationError("Launch needs an executable and valid arguments")

    @classmethod
    def parse(cls, data: Any) -> Action:
        fields = dict(object_fields(data, set(cls.__dataclass_fields__), "action"))
        for name in ("keys", "steps", "argv"):
            values = fields.get(name, [])
            if not isinstance(values, list):
                raise ConfigurationError(f"{name} must be an array")
            fields[name] = tuple(Step.parse(x) for x in values) if name == "steps" else tuple(values)
        try:
            return cls(**fields)
        except TypeError as e:
            raise ConfigurationError("Malformed action") from e

    def json(self) -> dict:
        data = asdict(self)
        data["keys"] = list(self.keys)
        data["argv"] = list(self.argv)
        data["steps"] = [asdict(s) for s in self.steps]
        return data


def bindings(data: Any) -> dict[str, Action]:
    if not isinstance(data, dict) or set(data) - CONTROLS:
        raise ConfigurationError("Unknown physical control")
    return {control: Action.parse(action) for control, action in data.items()}


@dataclass
class Layers:
    normal: dict[str, Action] = field(default_factory=dict)
    shifted: dict[str, Action] = field(default_factory=dict)

    @classmethod
    def parse(cls, data: Any) -> Layers:
        fields = object_fields(data, {"normal", "shifted"}, "layers")
        return cls(bindings(fields.get("normal", {})), bindings(fields.get("shifted", {})))

    def json(self) -> dict:
        return {name: {k: v.json() for k, v in getattr(self, name).items()}
                for name in ("normal", "shifted")}


@dataclass
class Profile:
    id: str
    name: str
    common: Layers = field(default_factory=Layers)
    overrides: dict[str, Layers] = field(default_factory=dict)
    standalone: dict[str, Layers] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id or len(self.id) > 128:
            raise ConfigurationError("Invalid profile ID")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 256:
            raise ConfigurationError("Invalid profile name")
        for choices in (self.overrides, self.standalone):
            if set(choices) - set(MODELS):
                raise ConfigurationError("Unknown model override")
            for model, layers in choices.items():
                if (set(layers.normal) | set(layers.shifted)) - set(MODEL_CONTROLS[model]):
                    raise ConfigurationError(f"Control absent on {model}")
        for layers in self.standalone.values():
            for action in (*layers.normal.values(), *layers.shifted.values()):
                if action.kind not in STANDALONE_KINDS or action.kind == 'hypershift' and action.playback != 'held':
                    raise ConfigurationError('This standalone alternative requires the Linux service')

    def resolve(self, model: str, control: str, shifted: bool = False) -> Action:
        if model not in MODELS or control not in MODEL_CONTROLS[model]:
            raise ConfigurationError(f"Control {control} absent on {model}")
        override = self.overrides.get(model, Layers())
        normal = override.normal.get(control, self.common.normal.get(control, Action()))
        if shifted and normal.kind != "hypershift":
            return override.shifted.get(control, self.common.shifted.get(control, normal))
        return normal

    @classmethod
    def parse(cls, data: Any) -> Profile:
        fields = object_fields(data, {"id", "name", "common", "overrides", "standalone"}, "profile")
        overrides = fields.get("overrides", {})
        standalone = fields.get('standalone', {})
        if not isinstance(overrides, dict) or not isinstance(standalone, dict):
            raise ConfigurationError("Overrides must be an object")
        return cls(fields.get("id", ""), fields.get("name", ""),
                   Layers.parse(fields.get("common", {})),
                   {model: Layers.parse(value) for model, value in overrides.items()},
                   {model: Layers.parse(value) for model, value in standalone.items()})

    def for_onboard(self, model: str) -> Profile:
        """Overlay alternatives for mouse memory; resolve() keeps Linux actions."""
        if model not in MODELS:
            raise ConfigurationError('Unknown mouse model')
        overrides = {m: Layers(dict(layer.normal), dict(layer.shifted)) for m, layer in self.overrides.items()}
        target = overrides.setdefault(model, Layers())
        alternative = self.standalone.get(model, Layers())
        target.normal.update(alternative.normal)
        target.shifted.update(alternative.shifted)
        return Profile(self.id, self.name, Layers(dict(self.common.normal), dict(self.common.shifted)), overrides)

    def json(self) -> dict:
        return {"id": self.id, "name": self.name, "common": self.common.json(),
                "overrides": {k: v.json() for k, v in self.overrides.items()},
                "standalone": {k: v.json() for k, v in self.standalone.items()}}


def sequence(*chords: tuple[str, ...], press_ms: int = 40, gap_ms: int = 100) -> Action:
    """Each chord is pressed, released in reverse order, then separated by a gap."""
    steps: list[Step] = []
    for i, chord in enumerate(chords):
        if i:
            steps.append(Step("wait", milliseconds=gap_ms))
        steps.extend(Step("down", key=k) for k in chord)
        steps.append(Step("wait", milliseconds=press_ms))
        steps.extend(Step("up", key=k) for k in reversed(chord))
    return Action("macro", steps=tuple(steps))
