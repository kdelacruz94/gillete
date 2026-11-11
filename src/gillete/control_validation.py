"""Complete receiver control/layer recipe and strict, inert evidence matching."""

from copy import deepcopy
import math

from .hypershift import resolve_action
from .model import Action, MODEL_CONTROLS, MODELS, Profile
from .onboard import Location
from .profiles import Rule, literal_pattern
from .stored_actions import from_snapshot
from . import validation_plan


VERSION = 1
QUIET_SECONDS = .15
ALTERNATE = 'validation-trigger'
TRIGGERS = {MODELS[0]: ('dpi_up', 'dpi_down'), MODELS[1]: ('ring_finger', 'top_rear')}
LABELS = {'left_click': 'left click', 'right_click': 'right click', 'wheel_click': 'wheel click',
          'wheel_up': 'wheel up (one detent)', 'wheel_down': 'wheel down (one detent)',
          'wheel_tilt_left': 'wheel tilt left', 'wheel_tilt_right': 'wheel tilt right',
          'dpi_up': 'front index-finger button', 'dpi_down': 'rear index-finger button',
          'top_front': 'front button behind the wheel', 'top_rear': 'rear button behind the wheel',
          'ring_finger': 'ring-finger button', 'profile_button': 'underside profile button',
          **{f'side_{i}': f'side button {i}' for i in range(1, 13)}}


def marker(model, control, shifted):
    index = MODEL_CONTROLS[model].index(control)
    modifiers = ((), ('KEY_LEFTSHIFT',), ('KEY_LEFTCTRL',))[index // 12]
    if shifted:
        modifiers += ('KEY_LEFTALT',)
    return Action('keys', keys=(*modifiers, f'KEY_F{13 + index % 12}'))


def recipe(model):
    first, second = TRIGGERS[model]
    steps = []
    for profile, trigger, controls in (('validation', first, [c for c in MODEL_CONTROLS[model] if c != first]),
                                       (ALTERNATE, second, [first])):
        for shifted in (False, True):
            for control in controls:
                action = marker(model, control, shifted)
                modifiers = [name for key, name in (('KEY_LEFTSHIFT', 'Shift'), ('KEY_LEFTCTRL', 'Ctrl'),
                                                    ('KEY_LEFTALT', 'Alt')) if key in action.keys]
                steps.append({'index': len(steps), 'control': control, 'shifted': shifted,
                    'profile': profile, 'trigger': trigger, 'key': action.keys[-1][4:],
                    'modifiers': modifiers, 'keys': list(action.keys), 'release_trigger': False})
        steps[-1]['release_trigger'] = True
    return {'version': VERSION, 'model': model, 'steps': steps}


def build(snapshot):
    config, _ = validation_plan.build(snapshot)
    model = snapshot.model
    original = Profile('original', 'Stored assignments')
    stored, _ = from_snapshot(snapshot)
    baseline = config.profiles['default']
    rows = []
    for identifier, trigger in zip(('validation', ALTERNATE), TRIGGERS[model]):
        profile = Profile.parse(baseline.json())
        profile.id = identifier
        profile.name = 'All controls' if identifier == 'validation' else 'Alternate HyperShift trigger'
        for shifted in (False, True):
            layer = profile.overrides[model].shifted if shifted else profile.overrides[model].normal
            for control in MODEL_CONTROLS[model]:
                layer[control] = (Action('hypershift', playback='held') if control == trigger else
                                  marker(model, control, shifted))
        config.profiles[identifier] = profile
    for shifted in (False, True):
        for control in MODEL_CONTROLS[model]:
            previous = resolve_action(original, model, control, shifted, stored)
            where = Location(snapshot.bank, validation_plan.CONTROL_IDS[model][control], int(shifted))
            rows.append({'control': control, 'shifted': shifted,
                'original_raw': snapshot.records[where].hex(),
                'original': previous.json() if previous else None,
                'outside': resolve_action(baseline, model, control, shifted, stored).json(),
                'inside': config.profiles['validation'].resolve(model, control, shifted).json(),
                'inside_alternate': config.profiles[ALTERNATE].resolve(model, control, shifted).json(),
                'reason': 'Complete software control/layer validation; no stored mapping changes'})
    config.validate()
    return config, rows


def title_for(base, profile):
    return base if profile == 'validation' else base + ' — alternate trigger'


def bind_window(config, model, app_class, title):
    config.rules = [Rule(identifier, app_class=literal_pattern(app_class),
                         title=literal_pattern(title_for(title, identifier)), model=model, priority=1000)
                    for identifier in ('validation', ALTERNATE)]


def describe(rows):
    return [f'{row["control"]} ({"HyperShift" if row["shifted"] else "normal"}): '
            f'first phase = {validation_plan.action_label(row["inside"])}; '
            f'alternate trigger phase = {validation_plan.action_label(row["inside_alternate"])}; '
            f'outside = {validation_plan.action_label(row["outside"])}.' for row in rows]


def qt_signature(step):
    modifiers = step['modifiers']
    return [(name, 'down') for name in modifiers] + [(step['key'], 'down'), (step['key'], 'up')] + [
            (name, 'up') for name in reversed(modifiers)]


def validate_packet(packet):
    try:
        trace = packet['trace']
        if (any(type(packet[name]) is not bool for name in ('active', 'focused', 'focus_pending'))
                or type(packet['t']) not in (int, float) or not math.isfinite(packet['t'])
                or trace['t'] != packet['t']
                or trace['version'] != VERSION or not isinstance(trace['epoch'], str) or len(trace['epoch']) != 32
                or any(type(trace[name]) is not int or trace[name] < 0 for name in ('sequence', 'generation'))
                or not isinstance(trace['profile'], str) or not isinstance(trace['held'], list)
                or not isinstance(trace['entries'], list) or len(trace['entries']) > 512):
            raise ValueError('Malformed control state')
        for entry in trace['entries']:
            if (type(entry['seq']) is not int or entry['seq'] < 1 or entry['seq'] > trace['sequence']
                    or type(entry['generation']) is not int or entry['generation'] < 0
                    or type(entry['t']) not in (int, float) or not math.isfinite(entry['t']) or entry['t'] > packet['t']
                    or not isinstance(entry['profile'], str) or not isinstance(entry['control'], str)
                    or entry['direction'] not in ('down', 'up')
                    or any(type(entry[name]) is not bool for name in ('activate', 'blocked', 'shifted'))):
                raise ValueError('Malformed mouse edge')
        if any(not isinstance(control, str) for control in trace['held']):
            raise ValueError('Malformed held controls')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Malformed control state') from error


class Trial:
    """One armed tap, corroborated by routed mouse edges and desktop keys.

    Results are observations, not simulated from the requested mapping. Focus,
    session and generation changes fail the attempt instead of being repaired.
    """
    def __init__(self, step, packet, *, now):
        validate_packet(packet)
        if type(now) not in (int, float) or not math.isfinite(now) or now < packet['t']:
            raise ValueError('Invalid trial arming time')
        self.step = deepcopy(step)
        self.armed_at = now
        trace = packet['trace']
        self.epoch, self.generation = trace['epoch'], trace['generation']
        self.after_seq = self.last_seq = trace['sequence']
        self.physical, self.qt = [], []
        self.error = ''
        self.final_packet = None

    def key(self, event):
        if len(self.qt) >= 128:
            self.error = 'Too many desktop events in one attempt'
            return
        self.qt.append(deepcopy(event))

    def update(self, packet, *, now):
        validate_packet(packet)
        if self.error:
            return 'failed'
        trace = packet['trace']
        if (not packet['focused'] or not packet['active'] or packet['focus_pending']
                or trace['epoch'] != self.epoch or trace['generation'] != self.generation
                or trace['profile'] != self.step['profile'] or not 0 <= now - packet['t'] <= 2):
            self.error = 'Focus, session or mapping context changed; retry with a fresh press'
            return 'failed'
        for entry in trace['entries']:
            if entry['seq'] <= self.last_seq:
                continue
            if entry['seq'] != self.last_seq + 1:
                self.error = 'Mouse evidence was dropped'
                return 'failed'
            self.last_seq = entry['seq']
            if (entry['t'] < self.armed_at or entry['generation'] != self.generation
                    or entry['profile'] != self.step['profile'] or not entry['activate'] or entry['blocked']):
                self.error = 'Mouse input crossed the arming or cancellation boundary'
                return 'failed'
            self.physical.append(deepcopy(entry))
        if self.last_seq != trace['sequence']:
            self.error = 'Mouse evidence was dropped or rewound'
            return 'failed'
        if len(self.physical) > 128:
            self.error = 'Too many mouse edges in one attempt'
            return 'failed'
        taps = []
        for entry in self.physical:
            if entry['control'] == self.step['trigger']:
                continue
            if entry['control'] != self.step['control']:
                self.error = f'Observed {entry["control"]}; expected {self.step["control"]}'
                return 'failed'
            if entry['direction'] == 'down' and entry['shifted'] != self.step['shifted']:
                self.error = 'The tap used the wrong HyperShift layer'
                return 'failed'
            taps.append(entry['direction'])
        if taps != ['down', 'up'][:len(taps)]:
            self.error = 'Expected one mouse press and release'
            return 'failed'
        expected = qt_signature(self.step)
        actual = []
        for event in self.qt:
            if (type(event['t']) not in (int, float) or not math.isfinite(event['t'])
                    or event['t'] < self.armed_at or not isinstance(event['modifiers'], list)):
                self.error = 'Invalid desktop event timing or modifiers'
                return 'failed'
            if event['key'] not in (*self.step['modifiers'], self.step['key']):
                self.error = f'Unexpected desktop key: {event["key"]}'
                return 'failed'
            if event.get('repeat'):
                continue
            actual.append((event['key'], event['direction']))
            if event['key'] == self.step['key'] and sorted(event['modifiers']) != sorted(self.step['modifiers']):
                self.error = 'Desktop modifiers did not match the mapping'
                return 'failed'
        if actual != expected[:len(actual)]:
            self.error = 'Desktop key order or count did not match the mapping'
            return 'failed'
        if taps != ['down', 'up'] or actual != expected:
            return 'waiting'
        physical_down = next(e for e in self.physical if e['control'] == self.step['control'])
        physical_up = [e for e in self.physical if e['control'] == self.step['control']][-1]
        marker = [e for e in self.qt if e['key'] == self.step['key'] and not e.get('repeat')]
        if marker[0]['t'] < physical_down['t'] or marker[-1]['t'] < physical_up['t']:
            self.error = 'Desktop keys preceded their mouse edges'
            return 'failed'
        held = set(trace['held'])
        if held - {self.step['trigger']} or self.step['release_trigger'] and held:
            return 'release-buttons'
        end = max([e['t'] for e in self.physical] + [e['t'] for e in self.qt])
        if packet['t'] < end + QUIET_SECONDS:
            return 'waiting'
        self.final_packet = {k: deepcopy(v) for k, v in packet.items() if k != 'trace'}
        self.final_packet['trace'] = {k: deepcopy(v) for k, v in trace.items() if k != 'entries'}
        return 'passed'

    def receipt(self):
        return {'step': self.step, 'armed_at': self.armed_at, 'after_seq': self.after_seq,
                'epoch': self.epoch, 'generation': self.generation, 'last_seq': self.last_seq,
                'physical': deepcopy(self.physical), 'qt': deepcopy(self.qt),
                'error': self.error, 'final_packet': deepcopy(self.final_packet)}


def validate_results(document, model, nonce, *, epoch=None, started_at=None, finished_by=None):
    """Recompute every claimed pass instead of trusting the window's tally."""
    try:
        steps = recipe(model)['steps']
        if (document['version'] != VERSION or document['model'] != model or document['nonce'] != nonce
                or document['status'] != 'complete' or len(document['passed']) != len(steps)):
            raise ValueError('Incomplete or unrelated control coverage report')
        previous_seq = -1
        for step, result in zip(steps, document['passed']):
            if result['step'] != step or result['error'] or result['after_seq'] < previous_seq:
                raise ValueError('Mismatched or overlapping control evidence')
            epoch = epoch or result['epoch']
            if result['epoch'] != epoch or not math.isfinite(result['armed_at']):
                raise ValueError('Control evidence changed sessions')
            if (not isinstance(result['qt'], list) or not isinstance(result['physical'], list)
                    or len(result['qt']) > 128 or len(result['physical']) > 128):
                raise ValueError('Oversized control attempt')
            final = result['final_packet']
            if (started_at is not None and result['armed_at'] < started_at
                    or finished_by is not None and final['t'] > finished_by):
                raise ValueError('Control evidence falls outside this test window')
            if (final.get('model') != model or final.get('nonce') != nonce
                    or final['trace']['epoch'] != result['epoch'] or final['trace']['generation'] != result['generation']):
                raise ValueError('Control receipt belongs to another test or mapping context')
            initial = deepcopy(final)
            initial['t'] = result['armed_at']
            initial['trace']['t'] = result['armed_at']
            initial['trace'].update(sequence=result['after_seq'], entries=[])
            trial = Trial(step, initial, now=result['armed_at'])
            trial.qt = deepcopy(result['qt'])
            final = deepcopy(final)
            final['trace']['entries'] = deepcopy(result['physical'])
            if trial.update(final, now=final['t']) != 'passed' or trial.last_seq != result['last_seq']:
                raise ValueError('Control receipt does not prove a complete tap')
            previous_seq = trial.last_seq
        return True
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        raise ValueError('Unverified control coverage: ' + str(error)) from error
