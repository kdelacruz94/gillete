import asyncio
import json
from types import SimpleNamespace

from gillete.control_trace import ControlTrace
from gillete.device_session import DeviceSession
from gillete.devices import Device
from gillete.engine import Engine
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODELS, Profile
from gillete.profiles import ProfileStore
from gillete.reports import Frame
from gillete.runtime import Router
from gillete.service import Daemon


def test_trace_observes_combined_interfaces_shift_order_pulses_and_suppression():
    async def check():
        profile = Profile('test', 'Test', Layers(normal={'ring_finger': Action('hypershift', playback='held'),
            'side_1': Action('keys', keys=('KEY_F24',)), 'wheel_up': Action('keys', keys=('KEY_F13',))},
            shifted={'side_1': Action('keys', keys=('KEY_F23',))}))
        engine = Engine(MODELS[1], profile, KeyLedger(RecordingOutput()))
        trace = ControlTrace()
        router = Router(engine, trace=trace)
        await router.feed(Frame('vendor', frozenset({'ring_finger'})))
        await router.feed(Frame('side', frozenset({'side_1'})))
        await router.feed(Frame('side', frozenset({'side_1'})))  # Duplicate held report.
        await router.feed(Frame('side'))
        await router.feed(Frame('vendor'))
        assert [(e['control'], e['direction'], e['shifted']) for e in trace.entries] == [
            ('ring_finger', 'down', False), ('side_1', 'down', True),
            ('side_1', 'up', True), ('ring_finger', 'up', True)]
        await router.feed(Frame('wheel', pulses=(('wheel_up', 2),)))
        assert [e['direction'] for e in list(trace.entries)[4:]] == ['down', 'up'] * 2
        await router.feed(Frame('side', frozenset({'side_1'})), activate=False)
        assert trace.entries[-1]['activate'] is False
        await router.feed(Frame('side'))
        assert trace.entries[-1]['blocked'] is True
        await router.feed(Frame('side', frozenset({'side_1'})))
        assert trace.entries[-1]['activate'] and not trace.entries[-1]['blocked']
        await router.close()
    asyncio.run(check())


def test_ordinary_service_exposes_no_trace_and_opt_in_keeps_mice_independent(tmp_path):
    daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
    for model, product in zip(MODELS, (0xB4, 0xE8)):
        device = Device(model, 'Test', '2.4 GHz', product, f'/test/{product}', 'private-serial')
        session = DeviceSession(device, daemon.coordinator, tmp_path, None, trace_controls=True)
        session.engine = Engine(model, daemon.coordinator.config.profiles['default'], KeyLedger(RecordingOutput()))
        session.ready = True
        session.input_trace.record(session.engine, 'mouse', 'side_1', 'down', activate=True)
        daemon.sessions[model] = session
    assert all('input_trace' not in state for state in daemon.status()['devices'].values())
    daemon.trace_controls = True
    states = daemon.status()['devices']
    assert states[MODELS[0]]['input_trace']['epoch'] != states[MODELS[1]]['input_trace']['epoch']
    assert all(state['input_trace']['entries'][0]['control'] == 'side_1' for state in states.values())
    assert 'private-serial' not in json.dumps(states)
    plain = DeviceSession(SimpleNamespace(), daemon.coordinator, tmp_path, None)
    assert plain.input_trace is None
