import asyncio

from evdev import ecodes

from gillete.engine import Engine
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODELS, Profile
from gillete.reports import Frame, decode
from gillete.runtime import Router
from gillete.stored_actions import decode as decode_stored


def test_cross_interface_shift_chord_and_wheel_have_balanced_outputs():
    async def check():
        profile = Profile('p', 'P', Layers(normal={
            'ring_finger': Action('hypershift', playback='held'),
            'side_1': Action('keys', keys=('KEY_A',)),
            'wheel_down': Action('keys', keys=('KEY_1',))},
            shifted={'side_1': Action('keys', keys=('KEY_LEFTCTRL', 'KEY_K'))}))
        sink = RecordingOutput()
        engine = Engine(MODELS[1], profile, KeyLedger(sink))
        router = Router(engine)
        await router.feed(decode(MODELS[1], '01', b'\4\x59' + bytes(14)))
        await router.feed(decode(MODELS[1], '02', b'\0\0\x1e' + bytes(5)))
        await router.feed(decode(MODELS[1], '01', b'\4' + bytes(15)))
        await router.feed(decode(MODELS[1], '02', bytes(8)))
        await router.feed(Frame('00:pointer', motion=(('REL_X', 5),), pulses=(('wheel_down', 2),)))
        assert sink.events[:4] == [('key', ecodes.KEY_LEFTCTRL, 1), ('key', ecodes.KEY_K, 1),
                                  ('key', ecodes.KEY_K, 0), ('key', ecodes.KEY_LEFTCTRL, 0)]
        assert sink.events[4:] == [('relative', ecodes.REL_X, 5), ('key', ecodes.KEY_1, 1),
                                  ('key', ecodes.KEY_1, 0), ('key', ecodes.KEY_1, 1), ('key', ecodes.KEY_1, 0)]
        await router.close()
        assert not engine.ledger.holders
    asyncio.run(check())


def test_duplicate_reports_and_focus_cancellation_require_a_fresh_press():
    async def check():
        profile = Profile('p', 'P', Layers(normal={'side_1': Action('turbo', keys=('KEY_1',), playback='toggle')}))
        sink = RecordingOutput()
        engine = Engine(MODELS[1], profile, KeyLedger(sink))
        router = Router(engine)
        frame = Frame('02:keyboard', frozenset({'side_1'}))
        await router.feed(frame)
        await asyncio.sleep(.01)
        await router.feed(frame)
        assert engine.macros.jobs
        await engine.cancel()
        count = len(sink.events)
        await router.feed(frame)
        await asyncio.sleep(.12)
        assert len(sink.events) == count and not engine.macros.jobs
        await router.feed(Frame('02:keyboard'))
        await router.feed(frame)
        await asyncio.sleep(.01)
        assert engine.macros.jobs
        await router.close()
        assert not engine.ledger.holders
    asyncio.run(check())


def test_exact_saved_assignments_decode_and_unknown_synapse_actions_stay_unknown():
    assert decode_stored(bytes.fromhex('020200e0000000'), MODELS[0]) == Action('keys', keys=('KEY_LEFTCTRL',))
    assert decode_stored(bytes.fromhex('02020222000000'), MODELS[0]) == Action('keys', keys=('KEY_LEFTSHIFT', 'KEY_5'))
    assert decode_stored(bytes.fromhex('0201001e000000'), MODELS[1]) == Action('keys', keys=('KEY_1',))
    assert decode_stored(bytes.fromhex('0d04004b008e00'), MODELS[0]) is None
    assert decode_stored(bytes.fromhex('05020000000000'), MODELS[0]) is None


def test_describing_synapse_families_does_not_claim_known_timing_or_executable_macros():
    from gillete.compile_onboard import describe_function
    for raw, name in (('0d04004b008e00', 'Pageup'), ('0d04004e008e00', 'Pagedown'),
                      ('0d04001c008e00', 'Y'), ('0e0301008e0000', 'LeftClick')):
        function = bytes.fromhex(raw)
        description = describe_function(function)
        assert name in description and '0x008e' in description and 'unverified' in description
        assert decode_stored(function, MODELS[0]) is None
    function = bytes.fromhex('05020000000000')
    assert 'reference 0x0000' in describe_function(function) and 'unresolved' in describe_function(function)
    assert decode_stored(function, MODELS[0]) is None


def test_default_mouse_drag_survives_focus_change_but_not_emergency_stop():
    async def check():
        output = RecordingOutput()
        stored = {('left_click', False): Action('keys', keys=('BTN_LEFT',))}
        engine = Engine(MODELS[1], Profile('p', 'P'), KeyLedger(output), stored=stored)
        await engine.press('left_click')
        await engine.change_profile(Profile('next', 'Next'))
        assert output.events == [('key', ecodes.BTN_LEFT, 1)]
        await engine.release('left_click')
        assert output.events[-1] == ('key', ecodes.BTN_LEFT, 0)
        await engine.press('left_click')
        await engine.cancel(preserve_pointer=False)
        assert output.events[-1] == ('key', ecodes.BTN_LEFT, 0)
        assert not engine.ledger.holders
    asyncio.run(check())
