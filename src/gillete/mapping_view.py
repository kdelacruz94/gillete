"""Explain profile inheritance and choose the value an editing scope owns."""

from dataclasses import dataclass

from .hypershift import resolve_action
from .device_action_support import support
from .model import Action, Layers, MODEL_CONTROLS, MODELS, Profile
from .shortcuts import describe


MODEL_NAMES = {MODELS[0]: 'Naga V2 HyperSpeed', MODELS[1]: 'Naga V3 Pro'}


@dataclass(frozen=True)
class MappingView:
    action: Action | None
    description: str
    source: str
    notice: str = ''

    @property
    def text(self):
        return '\n'.join(part for part in (self.description, self.source, self.notice) if part)


def view(profile, model, control, shifted=False, stored=None, snapshot=None):
    """Use the engine's effective action, including inherited mouse triggers.

    A passthrough normal action delegates to the mouse's shifted assignment on
    HyperShift; it must not be described as replaying the mouse's normal key.
    """
    override = profile.overrides.get(model, Layers())
    normal = resolve_action(profile, model, control, stored=stored)
    trigger = normal is not None and normal.kind == 'hypershift'
    layer = 'shifted' if shifted and not trigger else 'normal'
    if control in getattr(override, layer):
        origin = 'This mouse’s override'
    elif control in getattr(profile.common, layer):
        origin = 'Shared mapping'
    elif layer == 'shifted':
        layer = 'normal'
        origin = 'This mouse’s override' if control in override.normal else 'Shared mapping' if control in profile.common.normal else ''
    else:
        origin = ''
    configured = profile.resolve(model, control, shifted)
    resolved = resolve_action(profile, model, control, shifted, stored)
    # A stored normal trigger can outrank an explicit shifted assignment.
    inherited_trigger = trigger and profile.resolve(model, control).kind == 'passthrough'
    if inherited_trigger or configured.kind == 'passthrough':
        actual_layer = 'Normal' if trigger else 'HyperShift' if shifted else 'Normal'
        source = f'Mouse memory · {actual_layer}'
        if origin:
            source += f' · {origin}'
        source += ' · last read' if stored is not None else ' · not read'
        if inherited_trigger:
            description = 'Stored HyperShift trigger (hold)'
        elif resolved is None:
            description = 'Stored action not decoded'
        elif stored is None:
            description = 'Stored mouse assignment'
        else:
            description = 'Stored: ' + describe(resolved)
    else:
        description = describe(resolved)
        source = origin
    if shifted and trigger:
        source += ' · Normal trigger stays active'
    elif shifted and layer == 'normal' and configured.kind != 'passthrough':
        source += ' · inherited from Normal'
    state = support(resolved, model, snapshot)
    return MappingView(resolved, description, source, state.text if state else '')


def scoped_profile(profile, scope):
    if scope == 'common':
        return Profile(profile.id, profile.name, profile.common)
    if scope != 'device':
        raise ValueError('Unknown mapping scope')
    return profile


def editing_action(profile, model, control, shifted, scope):
    # Shared edits must not start from a mouse override. Device edits can start
    # from the effective shared/inherited value when no override exists yet.
    return scoped_profile(profile, scope).resolve(model, control, shifted)


def explicit_action(profile, model, control, shifted, scope):
    scoped_profile(profile, scope)  # Validate the scope without mutating it.
    layers = profile.common if scope == 'common' else profile.overrides.get(model, Layers())
    return (layers.shifted if shifted else layers.normal).get(control)


def rows(profile, model):
    """Include assigned controls that physically belong to the other mouse."""
    result = [(model, control) for control in MODEL_CONTROLS[model]]
    for other in MODELS:
        if other == model:
            continue
        layers = (profile.common, profile.overrides.get(other, Layers()), profile.standalone.get(other, Layers()))
        assigned = {control for layer in layers for control in (*layer.normal, *layer.shifted)}
        result.extend((other, control) for control in MODEL_CONTROLS[other]
                      if control not in MODEL_CONTROLS[model] and control in assigned)
    return result
