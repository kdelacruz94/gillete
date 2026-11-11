"""Production native macro gates tied to the physically accepted route/firmware.

These gates are expanded as remaining playback families are accepted. The
experimental compiler remains broader; Linux service playback is unaffected.
"""

from .model import MODEL_CONTROLS, MODELS, Profile
from .native_profile_transaction import validate


def save_issues(prepared):
    preview = validate(prepared)
    issues = list(preview.issues)
    before = prepared['before']
    if before['product'] != 0xE8 or before['firmware'] != '0101':
        issues.append('Native macro saving is currently validated for the V3 receiver with firmware 1.1.')
    profile = Profile.parse(prepared['profile']).for_onboard(MODELS[1])
    for control in MODEL_CONTROLS[MODELS[1]]:
        for shifted in (False, True):
            action = profile.resolve(MODELS[1], control, shifted)
            if action.kind not in ('macro', 'turbo'): continue
            location = f'{control} ({"HyperShift" if shifted else "normal"})'
            if action.kind != 'macro' or action.playback != 'once':
                issues.append(f'{location}: native repeat/turbo playback and cancellation need validation; '
                              'use the Linux service or choose a standalone alternative.')
            elif (any(s.kind not in ('down', 'up', 'wait') or s.kind in ('down', 'up')
                      and not s.key.startswith('KEY_') for s in action.steps)
                  or sum(s.kind == 'down' for s in action.steps) != 1):
                issues.append(f'{location}: native multi-key, mouse and movement macros need validation; '
                              'use the Linux service or choose a standalone alternative.')
            elif any(s.key in {f'KEY_F{i}' for i in range(13, 24)} for s in action.steps if s.kind in ('down', 'up')):
                issues.append(f'{location}: native F13–F23 desktop mapping needs validation; '
                              'use the Linux service, whose virtual-keyboard mapping is corrected.')
    return issues
