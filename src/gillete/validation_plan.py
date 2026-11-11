"""Offline, reviewable software acceptance profiles; never firmware writes."""

from .compile_onboard import CONTROL_IDS
from .hypershift import availability, resolve_action
from .model import Action, Layers, MODEL_CONTROLS, MODELS, Profile, sequence
from .onboard import Location
from .profiles import Configuration, Rule, literal_pattern
from .stored_actions import from_snapshot, unresolved
from .shortcuts import friendly_key


RETIRED_V2_MACROS = frozenset({'side_1', 'side_2', 'side_4', 'side_10'})
PRODUCT_MODELS = {0xB4: MODELS[0], 0xE8: MODELS[1]}


def controls(model):
    return ('dpi_up', 'dpi_down') if model == MODELS[0] else ('ring_finger', 'top_rear')


def instructions(model):
    trigger, turbo = (('front small index-finger/DPI-up button', 'rear small index-finger/DPI-down button')
                      if model == MODELS[0] else ('ring-finger button', 'rear button behind the wheel'))
    return (f'1. Tap side 12: F24. Hold the {trigger} and tap side 12: F23.\n'
            '2. Tap side 11: Ctrl+K, then M.\n'
            f'3. Tap the {turbo}: toggle repeated 1 on, then off.\n'
            '4. Start repeating 1 again, then click another window: repetition must stop.\n'
            '5. Return here: repetition must stay stopped until a fresh button press.\n\n'
            'Emergency stop: Ctrl+Alt+Pause. Close this test window when finished.')


def build(snapshot):
    """Preserve known original actions and list every temporary effective change.

    Retiring the four MapleStory macros is a user choice for this test only.
    Other unknown functions stay unknown: disabling them here never changes
    the firmware decoder or the user's regular configuration.
    """
    model = snapshot.model
    if PRODUCT_MODELS.get(snapshot.product) != model or snapshot.bank != snapshot.active:
        raise ValueError('Software validation requires an active slot on a verified receiver')
    expected = {Location(snapshot.bank, c, layer) for c in CONTROL_IDS[model].values() for layer in (0, 1)}
    if (set(snapshot.records) != expected or not set(CONTROL_IDS[model].values()) <= snapshot.controls
            or any(len(raw) != 10 or raw[:2] != bytes((where.bank, where.control)) or raw[2] not in (0, 1)
                   for where, raw in snapshot.records.items())):
        raise ValueError('Incomplete or malformed saved binding snapshot')
    stored, _ = from_snapshot(snapshot)
    original = Profile('original', 'Stored assignments')
    base, reasons = Layers(), {}
    for shifted, layer in ((False, base.normal), (True, base.shifted)):
        for control in MODEL_CONTROLS[model]:
            action = resolve_action(original, model, control, shifted, stored)
            reason = ''
            if model == MODELS[0] and shifted and control in RETIRED_V2_MACROS:
                reason = 'Old MapleStory macro retired by user for validation'
            elif action is None:
                reason = 'Unknown firmware function disabled temporarily; behavior is not inferred'
            elif action.kind in {'dpi', 'device'}:
                reason = 'Device-setting action disabled temporarily to keep saved settings unchanged'
            # Explicit shifted passthrough prevents a masked normal action from
            # also masking a known shifted binding. Native pointer passthrough
            # also retains drag ownership across focus changes in the engine.
            layer[control] = Action('disabled') if reason else Action()
            if reason:
                reasons[control, shifted] = reason
    trigger, turbo = controls(model)
    base.normal[trigger] = base.shifted[trigger] = Action('hypershift', playback='held')
    for shifted in (False, True):
        reasons[trigger, shifted] = 'Held HyperShift trigger for this validation'
    default = Profile('default', 'Outside the test window', overrides={model: base})
    test = Profile.parse(default.json())
    test.id, test.name = 'validation', 'Software acceptance'
    test.overrides[model].normal.update({
        'side_12': Action('keys', keys=('KEY_F24',)),
        'side_11': sequence(('KEY_LEFTCTRL', 'KEY_K'), ('KEY_M',)),
        turbo: Action('turbo', keys=('KEY_1',), playback='toggle', interval_ms=200)})
    test.overrides[model].shifted['side_12'] = Action('keys', keys=('KEY_F23',))
    overrides = []
    for shifted in (False, True):
        for control in MODEL_CONTROLS[model]:
            previous = resolve_action(original, model, control, shifted, stored)
            outside = resolve_action(default, model, control, shifted, stored)
            inside = resolve_action(test, model, control, shifted, stored)
            if previous == outside == inside:
                continue
            where = Location(snapshot.bank, CONTROL_IDS[model][control], int(shifted))
            overrides.append({'control': control, 'shifted': shifted,
                              'original_raw': snapshot.records[where].hex(),
                              'original': previous.json() if previous is not None else None,
                              'outside': outside.json(), 'inside': inside.json(),
                              'reason': reasons.get((control, shifted), 'Test key or timed shortcut')})
    config = Configuration(profiles={p.id: p for p in (default, test)})
    config.validate()
    for profile in config.profiles.values():
        if unresolved(profile, model, stored) or availability(profile, model, stored).issues:
            raise ValueError('Validation profile has unresolved actions or an unreachable HyperShift layer')
    return config, overrides


def bind_window(config, model, app_class, title):
    config.rules = [Rule('validation', app_class=literal_pattern(app_class), title=literal_pattern(title),
                         model=model, priority=1000)]


def assert_unchanged(before, after):
    for field in ('product', 'model', 'serial', 'bank', 'assigned', 'active', 'controls', 'records', 'settings', 'native_macros'):
        if getattr(before, field) != getattr(after, field):
            raise RuntimeError(f'Mouse {field} changed since the saved snapshot')
    for name in ('firmware', 'wheel_mode'):
        if name in before.metadata and after.metadata.get(name) != before.metadata[name]:
            raise RuntimeError(f'Mouse {name} changed or could not be verified after the test')


def action_label(value):
    action = Action.parse(value)
    if action.kind in {'keys', 'turbo'}:
        label = '+'.join(friendly_key(k) for k in action.keys)
        return label if action.kind == 'keys' else f'Toggle {label}, {action.interval_ms} ms interval'
    if action.kind == 'macro':
        events = [f'{step.kind} {friendly_key(step.key)}' if step.kind in ('down', 'up') else
                  f'wait {step.milliseconds} ms' if step.kind == 'wait' else f'{step.axis} {step.value}'
                  for step in action.steps[:12]]
        suffix = f'; {len(action.steps) - 12} more steps in prepared.json' if len(action.steps) > 12 else ''
        return f'Macro {action.playback}: ' + ', '.join(events) + suffix
    if action.kind == 'hypershift':
        return 'Hold HyperShift'
    return action.kind + (f' ({action.target})' if action.target else '')


def describe(overrides):
    return [f'{row["control"]} ({"HyperShift" if row["shifted"] else "normal"}): '
            f'in test = {action_label(row["inside"])}; outside = {action_label(row["outside"])}. {row["reason"]}'
            for row in overrides]
