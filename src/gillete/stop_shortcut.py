"""Validated emergency-key preferences, independent of compositor access."""

from dataclasses import dataclass

from evdev import ecodes

from .model import ConfigurationError


DEFAULT = 'Ctrl+Alt+Pause'
MODIFIERS = {'Ctrl': ('CTRL', 4), 'Alt': ('ALT', 8), 'Shift': ('SHIFT', 1), 'Super': ('SUPER', 64)}
KEYS = ('Pause', 'Escape', *(f'F{i}' for i in range(1, 13)))
# Keys a bare press would take from every application on the desktop.
NEEDS_MODIFIER = frozenset({'Escape'})
EVDEV_NAMES = {'Escape': 'KEY_ESC'}
MESSAGE = 'Emergency shortcut must be Pause, Escape or F1–F12 with optional Ctrl, Alt, Shift or Super'


@dataclass(frozen=True)
class StopShortcut:
    modifiers: tuple[str, ...]
    key: str

    @classmethod
    def parse(cls, value):
        if not isinstance(value, str) or len(value) > 80:
            raise ConfigurationError(MESSAGE)
        parts = [part.strip() for part in value.split('+')]
        names = {name.casefold(): name for name in (*MODIFIERS, *KEYS)}
        try:
            parts = [names[part.casefold()] for part in parts]
        except KeyError as error:
            raise ConfigurationError(MESSAGE) from error
        if (parts[-1] not in KEYS or any(part not in MODIFIERS for part in parts[:-1])
                or len(parts) != len(set(parts))):
            raise ConfigurationError('Choose one emergency key, after distinct modifiers')
        if parts[-1] in NEEDS_MODIFIER and len(parts) == 1:
            raise ConfigurationError(f'{parts[-1]} needs at least one modifier, such as Ctrl+Alt+{parts[-1]}')
        return cls(tuple(mod for mod in MODIFIERS if mod in parts[:-1]), parts[-1])

    @property
    def label(self):
        return '+'.join((*self.modifiers, self.key))

    @property
    def mask(self):
        return sum(MODIFIERS[modifier][1] for modifier in self.modifiers)

    @property
    def lua(self):
        return ' + '.join((*[MODIFIERS[mod][0] for mod in self.modifiers], self.key))

    @property
    def legacy(self):
        return ' '.join(MODIFIERS[mod][0] for mod in self.modifiers) + ', ' + self.key

    @property
    def keycodes(self):
        # Hyprland keycodes use the XKB offset. Retain the earlier Pause
        # compatibility check too; never unbind by a guessed reported code.
        code = ecodes.ecodes[EVDEV_NAMES.get(self.key, 'KEY_' + self.key.upper())]
        return {code + 8, code} if self.key == 'Pause' else {code + 8}

    def matches(self, binding):
        return ((binding.get('modmask') == self.mask or binding.get('ignoreMods') is True)
                and (str(binding.get('key', '')).casefold() == self.key.casefold()
                     or binding.get('keycode') in self.keycodes))
