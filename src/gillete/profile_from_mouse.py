"""Copy decoded snapshot intent into an inactive, mouse-specific Linux draft.

Unknown functions are kept as stored assignments. Any row can be explicitly
disabled locally. This creates no firmware backup or device operation.
"""

from copy import deepcopy

from .compile_onboard import CONTROL_IDS
from .hypershift import resolve_action
from .model import Action, ConfigurationError, Layers, MODEL_CONTROLS, MODELS, Profile
from .onboard import Location
from .stored_actions import from_snapshot


class MouseProfileDraft:
    def __init__(self, snapshot):
        try:
            self.snapshot = deepcopy(snapshot)
            snapshot = self.snapshot
            model = snapshot.model
            if {0xB4: MODELS[0], 0xE8: MODELS[1]}.get(snapshot.product) != model:
                raise ValueError('Use a snapshot from a supported receiver')
            maximum = 1 if snapshot.product == 0xB4 else 5
            if (type(snapshot.bank) is not int or snapshot.bank not in snapshot.assigned
                    or snapshot.active not in snapshot.assigned
                    or not 1 <= snapshot.bank <= maximum
                    or not 1 <= len(snapshot.assigned) <= maximum
                    or any(type(bank) is not int or not 1 <= bank <= maximum for bank in snapshot.assigned)
                    or len(set(snapshot.assigned)) != len(snapshot.assigned)
                    or not set(CONTROL_IDS[model].values()) <= snapshot.controls):
                raise ValueError('Invalid source slot or control inventory')
            expected = {Location(snapshot.bank, control, layer) for control in CONTROL_IDS[model].values() for layer in (0, 1)}
            if set(snapshot.records) != expected or any(
                    not isinstance(raw, bytes) or len(raw) != 10
                    or raw[:2] != bytes((where.bank, where.control)) or raw[2] not in (0, 1)
                    for where, raw in snapshot.records.items()):
                raise ValueError('Incomplete source assignments')
            self.model, self.bank = model, snapshot.bank
            stored, unknown = from_snapshot(snapshot)
            original = Profile('mouse-read', 'Stored assignments')
            self.actions, self.unknown = {}, {}
            for control, shifted in self.rows:
                action = resolve_action(original, model, control, shifted, stored)
                if action is None:
                    self.unknown[control, shifted] = unknown[control, shifted]
                else:
                    self.actions[control, shifted] = action
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ConfigurationError('Cannot copy this mouse read: ' + str(error)) from error

    @property
    def rows(self):
        return tuple((control, shifted) for control in MODEL_CONTROLS[self.model] for shifted in (False, True))

    def profile(self, identifier, name, *, disabled=()):
        disabled = set(disabled)
        if disabled - set(self.rows):
            raise ConfigurationError('Only reviewed assignments for this mouse can be disabled during this copy')
        for control, shifted in disabled:
            normal = self.actions.get((control, False))
            if (shifted and normal is not None and normal.kind == 'hypershift'
                    and (control, False) not in disabled):
                raise ConfigurationError('The normal HyperShift trigger applies on both layers; change its normal assignment first')
        layers = Layers()
        for control, shifted in self.rows:
            layer = layers.shifted if shifted else layers.normal
            where = control, shifted
            layer[control] = (Action('disabled') if where in disabled else
                              self.actions.get(where, Action('passthrough')))
        return Profile(identifier, name, overrides={self.model: layers})
