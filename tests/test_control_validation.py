import asyncio
from copy import deepcopy

from evdev import ecodes as E
import pytest

from gillete import control_validation as coverage
from gillete.control_trace import ControlTrace
from gillete.engine import Engine
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODEL_CONTROLS, MODELS, Profile
from gillete.profiles import Window
from gillete.reports import Frame
from gillete.runtime import Router
from test_guided_service import snapshot


NONCE = 'a' * 32


class Clock:
    def __init__(self): self.t = 10.
    def __call__(self): return self.t
    def advance(self, seconds=.01): self.t += seconds


class DesktopOutput(RecordingOutput):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.modifiers, self.desktop = set(), []

    def key(self, code, value):
        super().key(code, value)
        self.clock.advance(.001)
        names = {E.KEY_LEFTSHIFT: 'Shift', E.KEY_LEFTCTRL: 'Ctrl', E.KEY_LEFTALT: 'Alt',
                 **{E.ecodes[f'KEY_F{i}']: f'F{i}' for i in range(13, 25)}}
        key = names[code]
        if key in ('Shift', 'Ctrl', 'Alt'):
            if value: self.modifiers.add(key)
            else: self.modifiers.discard(key)
        self.desktop.append({'key': key, 'direction': 'down' if value else 'up',
            't': self.clock(), 'modifiers': sorted(self.modifiers), 'repeat': False})


def packet(trace, engine, clock, model=MODELS[0]):
    return {'version': 1, 'model': model, 'nonce': NONCE, 't': clock(),
            'focused': True, 'active': True, 'focus_pending': False, 'trace': trace.document(engine)}


async def observe_step(step, engine, router, output, trace, clock, model):
    initial = packet(trace, engine, clock, model)
    trial = coverage.Trial(step, initial, now=clock())
    output.desktop.clear()
    held = {step['trigger']} if step['shifted'] else set()
    if step['shifted'] and step['trigger'] not in router.held:
        clock.advance()
        await router.feed(Frame('mouse', frozenset(held)))
    clock.advance()
    await router.feed(Frame('mouse', frozenset(held | {step['control']})))
    clock.advance()
    await router.feed(Frame('mouse', frozenset(held)))
    if step['release_trigger']:
        clock.advance()
        await router.feed(Frame('mouse'))
    for event in output.desktop: trial.key(event)
    clock.advance(.2)
    current = packet(trace, engine, clock, model)
    assert trial.update(current, now=clock()) == 'passed', trial.error
    return trial.receipt(), initial, current


def complete_report(model=MODELS[0]):
    async def check():
        clock = Clock()
        config, _ = coverage.build(snapshot(model))
        output = DesktopOutput(clock)
        engine = Engine(model, config.profiles['validation'], KeyLedger(output))
        trace = ControlTrace(clock=clock)
        router = Router(engine, trace=trace)
        results = []
        for step in coverage.recipe(model)['steps']:
            if engine.profile.id != step['profile']:
                await engine.change_profile(config.profiles[step['profile']])
            result, _, _ = await observe_step(step, engine, router, output, trace, clock, model)
            results.append(result)
        assert not engine.ledger.holders and not router.held
        return {'version': 1, 'model': model, 'nonce': NONCE, 'status': 'complete',
                'passed': results, 'failed_attempts': []}
    return asyncio.run(check())


@pytest.mark.parametrize('model,count', [(MODELS[0], 42), (MODELS[1], 50)])
def test_recipe_covers_every_control_in_both_layers_and_the_trigger_itself(model, count):
    original = snapshot(model)
    before = deepcopy(original)
    config, rows = coverage.build(original)
    steps = coverage.recipe(model)['steps']
    assert original == before and len(steps) == count
    assert {(s['control'], s['shifted']) for s in steps} == {(c, shifted) for c in MODEL_CONTROLS[model] for shifted in (False, True)}
    assert len({(s['key'], tuple(s['modifiers'])) for s in steps}) == count
    assert len(rows) == count and all('inside_alternate' in row for row in rows)
    for step in steps:
        profile = config.profiles[step['profile']]
        assert profile.resolve(model, step['control'], step['shifted']).keys == tuple(step['keys'])
        assert profile.resolve(model, step['trigger']).kind == 'hypershift'
        assert step['control'] != step['trigger']
        assert all(action.kind in {'keys', 'hypershift'} for layer in (profile.overrides[model].normal, profile.overrides[model].shifted) for action in layer.values())
    assert steps[-1]['control'] == coverage.TRIGGERS[model][0] and steps[-1]['release_trigger']
    assert not config.pinned and not config.startup_models
    coverage.bind_window(config, model, 'test[?]*', 'Input[?]*')
    assert config.select(model, Window('1', 'test[?]*', 'Input[?]*')).id == 'validation'
    assert config.select(model, Window('1', 'test[?]*', coverage.title_for('Input[?]*', coverage.ALTERNATE))).id == coverage.ALTERNATE
    assert config.select(model, Window('1', 'testX', 'InputX')).id == 'default'
    assert config.select(MODELS[1] if model == MODELS[0] else MODELS[0], Window('1', 'test[?]*', 'Input[?]*')).id == 'default'


@pytest.mark.parametrize('model', MODELS)
def test_all_recipe_taps_route_balanced_keys_and_have_recomputable_mouse_and_desktop_evidence(model):
    document = complete_report(model)
    assert coverage.validate_results(document, model, NONCE)


@pytest.mark.parametrize('tamper', ['missing', 'duplicate', 'wrong-control', 'wrong-layer', 'no-mouse', 'no-desktop',
    'extra-key', 'wrong-modifier', 'stale-epoch', 'stale-generation', 'wrong-nonce', 'wrong-final-nonce', 'time-reversed', 'status'])
def test_complete_claim_is_recomputed_and_rejects_missing_or_misattributed_evidence(tamper):
    document = complete_report()
    result = document['passed'][0]
    if tamper == 'missing': document['passed'].pop()
    elif tamper == 'duplicate': document['passed'][1] = deepcopy(result)
    elif tamper == 'wrong-control': result['physical'][0]['control'] = 'side_12'
    elif tamper == 'wrong-layer': result['physical'][0]['shifted'] = True
    elif tamper == 'no-mouse': result['physical'].clear()
    elif tamper == 'no-desktop': result['qt'].clear()
    elif tamper == 'extra-key': result['qt'].append(deepcopy(result['qt'][0]))
    elif tamper == 'wrong-modifier': result['qt'][0]['modifiers'] = ['Meta']
    elif tamper == 'stale-epoch': result['epoch'] = 'b' * 32
    elif tamper == 'stale-generation': result['generation'] += 1
    elif tamper == 'wrong-nonce': document['nonce'] = 'b' * 32
    elif tamper == 'wrong-final-nonce': result['final_packet']['nonce'] = 'b' * 32
    elif tamper == 'time-reversed': result['qt'][0]['t'] = result['armed_at'] - 1
    else: document['status'] = 'incomplete'
    with pytest.raises(ValueError, match='Unverified control coverage'):
        coverage.validate_results(document, MODELS[0], NONCE)


@pytest.mark.parametrize('failure', ['focus', 'inactive', 'pending', 'epoch', 'generation', 'profile', 'stale', 'dropped', 'suppressed', 'blocked', 'rewound'])
def test_trial_rejects_context_loss_and_incomplete_physical_evidence(failure):
    result = complete_report()['passed'][0]
    final = deepcopy(result['final_packet'])
    initial = deepcopy(final)
    initial.update(t=result['armed_at'])
    initial['trace']['t'] = result['armed_at']
    initial['trace'].update(entries=[], sequence=result['after_seq'])
    trial = coverage.Trial(result['step'], initial, now=result['armed_at'])
    final['trace']['entries'] = deepcopy(result['physical'])
    for event in result['qt']: trial.key(event)
    now = final['t']
    if failure == 'focus': final['focused'] = False
    elif failure == 'inactive': final['active'] = False
    elif failure == 'pending': final['focus_pending'] = True
    elif failure == 'epoch': final['trace']['epoch'] = 'b' * 32
    elif failure == 'generation': final['trace']['generation'] += 1
    elif failure == 'profile': final['trace']['profile'] = 'default'
    elif failure == 'stale': now += 3
    elif failure == 'dropped': final['trace']['entries'].pop(0)
    elif failure == 'suppressed': final['trace']['entries'][0]['activate'] = False
    elif failure == 'blocked': final['trace']['entries'][0]['blocked'] = True
    else:
        assert trial.update(final, now=now) == 'passed'
        final['trace'].update(sequence=result['after_seq'], entries=[])
    assert trial.update(final, now=now) == 'failed'


def test_marker_keys_alone_never_pass_and_quiet_tail_retains_extras():
    result = complete_report()['passed'][0]
    final = deepcopy(result['final_packet'])
    initial = deepcopy(final)
    initial['t'] = result['armed_at']
    initial['trace']['t'] = result['armed_at']
    initial['trace'].update(entries=[], sequence=result['after_seq'])
    trial = coverage.Trial(result['step'], initial, now=result['armed_at'])
    for event in result['qt']: trial.key(event)
    initial['t'] = final['t']
    initial['trace']['t'] = final['t']
    assert trial.update(initial, now=final['t']) == 'waiting'
    final['trace']['entries'] = result['physical']
    final['t'] = result['qt'][-1]['t'] + .01
    final['trace']['t'] = final['t']
    assert trial.update(final, now=final['t']) == 'waiting'
    trial.key(result['qt'][0])
    final['t'] += .2
    final['trace']['t'] = final['t']
    assert trial.update(final, now=final['t']) == 'failed'


def test_trace_omits_motion_and_actions_and_is_bounded_and_optional():
    async def check():
        engine = Engine(MODELS[0], Profile('p', 'P', Layers(normal={'side_1': Action('keys', keys=('KEY_F24',))})), KeyLedger(RecordingOutput()))
        trace = ControlTrace()
        router = Router(engine, trace=trace)
        for _ in range(600): await router.feed(Frame('mouse', motion=(('REL_X', 999),)))
        assert not trace.entries and not trace.held
        for _ in range(300):
            await router.feed(Frame('mouse', frozenset({'side_1'})))
            await router.feed(Frame('mouse'))
        doc = trace.document(engine)
        assert doc['sequence'] == 600 and len(doc['entries']) == 512
        assert doc['entries'][0]['seq'] == 89 and not doc['held']
        assert all(set(e) == {'seq', 't', 'source', 'control', 'direction', 'shifted', 'activate', 'blocked', 'profile', 'generation'} for e in doc['entries'])
        ordinary = Router(engine)
        await ordinary.feed(Frame('mouse', frozenset({'side_1'})))
        await ordinary.feed(Frame('mouse'))
        assert ordinary.trace is None and trace.sequence == 600
    asyncio.run(check())


@pytest.mark.parametrize('control', ['wheel_up', 'wheel_down'])
@pytest.mark.parametrize('shifted', [False, True])
def test_wheel_pulse_taps_have_immediate_complete_edges_and_desktop_pairs(control, shifted):
    async def check():
        model = MODELS[1]
        config, _ = coverage.build(snapshot(model))
        clock = Clock()
        output = DesktopOutput(clock)
        engine = Engine(model, config.profiles['validation'], KeyLedger(output))
        trace = ControlTrace(clock=clock)
        router = Router(engine, trace=trace)
        step = next(s for s in coverage.recipe(model)['steps'] if s['control'] == control and s['shifted'] == shifted)
        trial = coverage.Trial(step, packet(trace, engine, clock, model), now=clock())
        if shifted:
            clock.advance()
            await router.feed(Frame('vendor', frozenset({step['trigger']})))
        clock.advance()
        await router.feed(Frame('pointer', pulses=((control, 1),)))
        for event in output.desktop: trial.key(event)
        clock.advance(.2)
        assert trial.update(packet(trace, engine, clock, model), now=clock()) == 'passed'
        assert [e['direction'] for e in trial.physical if e['control'] == control] == ['down', 'up']
        await router.close()
    asyncio.run(check())
