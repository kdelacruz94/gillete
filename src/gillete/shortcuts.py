"""User-facing shortcut notation; commas separate chords, + joins held keys."""

from .model import ConfigurationError, key_code

ALIASES = {"ctrl": "KEY_LEFTCTRL", "control": "KEY_LEFTCTRL", "alt": "KEY_LEFTALT",
           "shift": "KEY_LEFTSHIFT", "super": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA",
           "win": "KEY_LEFTMETA", "enter": "KEY_ENTER", "return": "KEY_ENTER",
           "esc": "KEY_ESC", "escape": "KEY_ESC", "space": "KEY_SPACE", "tab": "KEY_TAB",
           "backspace": "KEY_BACKSPACE", "delete": "KEY_DELETE", "insert": "KEY_INSERT",
           "home": "KEY_HOME", "end": "KEY_END", "pageup": "KEY_PAGEUP", "pagedown": "KEY_PAGEDOWN",
           "left": "KEY_LEFT", "right": "KEY_RIGHT", "up": "KEY_UP", "down": "KEY_DOWN",
           "comma": "KEY_COMMA", "period": "KEY_DOT", "minus": "KEY_MINUS", "equal": "KEY_EQUAL",
           "slash": "KEY_SLASH", "semicolon": "KEY_SEMICOLON", "apostrophe": "KEY_APOSTROPHE",
           "backslash": "KEY_BACKSLASH", "grave": "KEY_GRAVE",
           "leftbrace": "KEY_LEFTBRACE", "rightbrace": "KEY_RIGHTBRACE",
           "leftclick": "BTN_LEFT", "rightclick": "BTN_RIGHT", "middleclick": "BTN_MIDDLE",
           "back": "BTN_SIDE", "forward": "BTN_EXTRA", "volumeup": "KEY_VOLUMEUP",
           "volumedown": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE", "playpause": "KEY_PLAYPAUSE"}


def parse_key(text: str) -> str:
    token = text.strip()
    key = ALIASES.get(token.lower(), token.upper() if token.upper().startswith(("KEY_", "BTN_"))
                      else "KEY_" + token.upper())
    key_code(key)
    return key


def parse_chord(text: str) -> tuple[str, ...]:
    keys = tuple(parse_key(k) for k in text.split("+"))
    if not keys or len(set(keys)) != len(keys):
        raise ConfigurationError("A chord needs distinct keys")
    return keys


def parse_sequence(text: str) -> tuple[tuple[str, ...], ...]:
    return tuple(parse_chord(chord) for chord in text.split(","))


def friendly_key(key: str) -> str:
    common = {"KEY_LEFTCTRL": "Ctrl", "KEY_LEFTALT": "Alt", "KEY_LEFTSHIFT": "Shift",
              "KEY_LEFTMETA": "Super", "BTN_LEFT": "LeftClick", "BTN_RIGHT": "RightClick",
              "BTN_MIDDLE": "MiddleClick"}
    return common.get(key, key.removeprefix("KEY_").removeprefix("BTN_").title())


def describe(action) -> str:
    if action.kind == 'device':
        return {'wheel_mode_cycle': 'Cycle wheel mode', 'onboard_profile_cycle': 'Cycle onboard profile'}[action.target]
    if action.kind == "scroll":
        direction = ("up" if action.value > 0 else "down") if action.axis == "REL_WHEEL" else ("right" if action.value > 0 else "left")
        return f"Scroll {direction} · {abs(action.value)}"
    if action.kind == "dpi":
        return "DPI " + action.target
    if action.kind in {"keys", "turbo"}:
        chord = "+".join(friendly_key(k) for k in action.keys)
        return chord if action.kind == "keys" else f"Turbo {chord} · {action.playback} · {action.interval_ms} ms"
    if action.kind == "macro":
        return f"Macro · {len(action.steps)} steps · {action.playback}"
    if action.kind == "hypershift":
        return f"HyperShift · {action.playback}"
    if action.kind == "launch":
        return "Launch " + (action.desktop_id.removesuffix('.desktop') or action.argv[0])
    if action.kind == "profile":
        return "Profile: " + action.target
    return {"passthrough": "Stored mouse assignment", "disabled": "Disabled"}.get(action.kind, action.kind)
