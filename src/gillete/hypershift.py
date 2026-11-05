"""Resolve inherited triggers and explain whether a profile's layer is reachable."""

from dataclasses import dataclass

from .model import MODEL_CONTROLS


PULSE_CONTROLS = frozenset({'wheel_up', 'wheel_down'})


def resolve_action(profile, model, control, shifted=False, stored=None):
    normal = profile.resolve(model, control)
    if normal.kind == 'passthrough' and stored is not None:
        normal = stored.get((control, False))
    # A trigger inherited from mouse memory has the same priority as an
    # explicitly assigned trigger, including when another trigger is held.
    if shifted and normal is not None and normal.kind == 'hypershift':
        return normal
    action = profile.resolve(model, control, shifted)
    if action.kind == 'passthrough' and stored is not None:
        return stored.get((control, shifted))
    return action


def shifted_controls(profile, model):
    controls = set(profile.common.shifted)
    override = profile.overrides.get(model)
    if override:
        controls.update(override.shifted)
    return tuple(c for c in MODEL_CONTROLS[model] if c in controls)


@dataclass(frozen=True)
class Trigger:
    control: str
    playback: str
    inherited: bool


@dataclass(frozen=True)
class Availability:
    triggers: tuple[Trigger, ...]
    unknown: tuple[str, ...]
    shifted: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def message(self):
        if self.triggers:
            labels = [f'{t.control.replace("_", " ").title()} ({"hold" if t.playback == "held" else "toggle"}'
                      + (', stored at last read)' if t.inherited else ')') for t in self.triggers]
            text = 'HyperShift trigger: ' + ', '.join(labels) + '.'
        elif self.unknown:
            text = ('HyperShift trigger unverified. It may be inherited from mouse memory. '
                    'Assign a normal-layer HyperShift button, or read the active mouse slot to check.')
        elif self.shifted:
            text = 'HyperShift layer is unreachable on this mouse.'
        else:
            text = 'No HyperShift trigger or custom shifted assignments on this mouse.'
        return '\n'.join((text, *self.issues))


def availability(profile, model, stored=None):
    triggers, unknown, issues = [], [], []
    for control in MODEL_CONTROLS[model]:
        action = resolve_action(profile, model, control, stored=stored)
        if action is None or action.kind == 'passthrough':
            unknown.append(control)
        elif action.kind == 'hypershift':
            if control in PULSE_CONTROLS and action.playback == 'held':
                issues.append(f'{control.replace("_", " ").title()}: held HyperShift ends with each scroll event. '
                              'Choose Toggle on/off or assign a button that can be held.')
            else:
                triggers.append(Trigger(control, action.playback,
                                        profile.resolve(model, control).kind == 'passthrough'))
    shifted = shifted_controls(profile, model)
    if shifted and not triggers and not unknown:
        issues.append('Assign HyperShift to a normal-layer button to use this mouse\'s shifted mappings.')
    return Availability(tuple(triggers), tuple(unknown), shifted, tuple(issues))
