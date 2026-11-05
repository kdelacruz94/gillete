"""Profiles a mouse can select in its current automatic or pinned mode."""

from .hypershift import resolve_action
from .model import ConfigurationError, MODEL_CONTROLS


def reachable_profiles(config, model, stored):
    """Include all effective button destinations, including cycles and layers.

    A pin replaces automatic selection until Automatic is chosen again. In
    automatic mode, any enabled rule for this model may match a future window,
    even if it does not match the current one. Hardware preflight must therefore
    cover those roots and every profile reachable from their button actions.
    Other structurally valid profiles can remain unfinished in the library.
    """
    config.validate()
    if model not in MODEL_CONTROLS:
        raise ConfigurationError('Unknown mouse model')
    if model in config.pinned:
        pending = [config.pinned[model]]
    else:
        pending = [config.defaults[model], *(rule.profile for rule in config.rules
                   if rule.enabled and (not rule.model or rule.model == model))]
    included = set()
    while pending:
        identifier = pending.pop()
        if identifier in included:
            continue
        included.add(identifier)
        profile = config.profiles[identifier]
        for control in MODEL_CONTROLS[model]:
            for shifted in (False, True):
                action = resolve_action(profile, model, control, shifted, stored)
                if action is not None and action.kind == 'profile' and action.target not in included:
                    pending.append(action.target)
    return tuple(profile for identifier, profile in config.profiles.items() if identifier in included)
