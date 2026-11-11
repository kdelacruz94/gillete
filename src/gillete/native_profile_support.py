"""Production native macro gates tied to the physically accepted route/firmware.

These gates are expanded as remaining playback families are accepted. The
experimental compiler remains broader; Linux service playback is unaffected.
"""

from .model import MODEL_CONTROLS, MODELS, Profile

def action_issue(action):
    """Accepted keyboard families; route/firmware and byte limits are separate."""
    if action.kind not in ('macro', 'turbo'):
        return None
    if action.kind != 'macro' or action.playback not in ('once', 'count'):
        return 'Native held/toggle/turbo playback and cancellation need validation'
    if (any(s.kind not in ('down', 'up', 'wait') or s.kind in ('down', 'up')
            and not s.key.startswith('KEY_') for s in action.steps)
            or not any(s.kind == 'down' for s in action.steps)):
        return 'Native mouse, movement and keyless macros need validation'
    if action.playback == 'count' and sum(s.kind == 'down' for s in action.steps) != 1:
        return 'Counted multi-key native sequences need validation'
    if any(s.key in {f'KEY_F{i}' for i in range(13, 24)} for s in action.steps if s.kind in ('down', 'up')):
        return 'Native F13–F23 desktop mapping needs validation; the Linux service corrects its virtual keyboard'
    return None


def save_issues(prepared):
    from .native_profile_transaction import validate
    preview = validate(prepared)
    issues = list(preview.issues)
    before = prepared['before']
    if before['product'] != 0xE8 or before['firmware'] != '0101':
        issues.append('Native macro saving is currently validated for the V3 receiver with firmware 1.1.')
    profile = Profile.parse(prepared['profile']).for_onboard(MODELS[1])
    for control in MODEL_CONTROLS[MODELS[1]]:
        for shifted in (False, True):
            action = profile.resolve(MODELS[1], control, shifted)
            location = f'{control} ({"HyperShift" if shifted else "normal"})'
            issue = action_issue(action)
            if issue:
                issues.append(f'{location}: {issue}; use the Linux service or choose a standalone alternative.')
    return issues
