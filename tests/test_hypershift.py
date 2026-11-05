import asyncio

from evdev import ecodes as E

from gillete.engine import Engine
from gillete.hypershift import availability
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODEL_CONTROLS, MODELS, Profile
from gillete.reports import Frame
from gillete.runtime import Router
from gillete.stored_actions import unresolved


def saved_defaults(model):
    return {(control, shifted): Action('disabled')
            for control in MODEL_CONTROLS[model] for shifted in (False, True)}


def test_missing_trigger_is_distinct_from_unread_or_unresolved_mouse_memory():
    profile = Profile('p', 'P', Layers(shifted={'side_1': Action('keys', keys=('KEY_F23',))}))
    assert not availability(profile, MODELS[0]).issues
    assert 'unverified' in availability(profile, MODELS[0]).message
    stored = saved_defaults(MODELS[0])
    checked = availability(profile, MODELS[0], stored)
    assert checked.issues and 'unreachable' in checked.message
    del stored['dpi_up', False]
    assert not availability(profile, MODELS[0], stored).issues
    stored['dpi_up', False] = Action('hypershift', playback='held')
    checked = availability(profile, MODELS[0], stored)
    assert not checked.issues and checked.triggers[0].inherited
    assert 'stored at last read' in checked.message
    profile.overrides[MODELS[0]] = Layers(normal={'dpi_up': Action('disabled')})
    assert availability(profile, MODELS[0], stored).issues


def test_shared_profiles_respect_model_specific_controls_and_trigger_overrides():
    profile = Profile('p', 'P', Layers(normal={'ring_finger': Action('hypershift', playback='held')},
                                      shifted={'side_1': Action('keys', keys=('KEY_1',))}))
    assert availability(profile, MODELS[0], saved_defaults(MODELS[0])).issues
    assert not availability(profile, MODELS[1], saved_defaults(MODELS[1])).issues
    profile.overrides[MODELS[0]] = Layers(normal={'dpi_up': Action('hypershift', playback='toggle')})
    assert not availability(profile, MODELS[0], saved_defaults(MODELS[0])).issues
    only_v3 = Profile('v3', 'V3', Layers(shifted={'ring_finger': Action('keys', keys=('KEY_A',))}))
    assert not availability(only_v3, MODELS[0], saved_defaults(MODELS[0])).issues
    assert availability(only_v3, MODELS[1], saved_defaults(MODELS[1])).issues


def test_held_scroll_cannot_activate_layer_but_software_toggle_can_and_cancel_resets_it():
    async def check():
        profile = Profile('p', 'P', Layers(normal={'wheel_up': Action('hypershift', playback='held')},
                                          shifted={'side_1': Action('keys', keys=('KEY_F23',))}))
        stored = saved_defaults(MODELS[1])
        assert 'each scroll event' in availability(profile, MODELS[1], stored).message
        profile.common.normal['wheel_up'] = Action('hypershift', playback='toggle')
        assert not availability(profile, MODELS[1], stored).issues
        output = RecordingOutput()
        engine = Engine(MODELS[1], profile, KeyLedger(output), stored=stored)
        router = Router(engine)
        pulse = Frame('pointer', pulses=(('wheel_up', 1),))
        await router.feed(pulse)
        await router.feed(Frame('side', frozenset({'side_1'})))
        assert engine.shifted and output.events == [('key', E.KEY_F23, 1)]
        await router.feed(pulse)
        assert not engine.shifted
        await router.feed(Frame('side'))
        assert output.events[-1] == ('key', E.KEY_F23, 0)
        await router.feed(pulse)
        assert engine.shifted
        await engine.cancel()
        assert not engine.shifted and not engine.ledger.holders
        await router.close()
    asyncio.run(check())


def test_inherited_trigger_remains_usable_under_another_shift_without_overwriting_stored_actions():
    async def check():
        profile = Profile('p', 'P', Layers(normal={'top_front': Action('hypershift', playback='held')},
                            shifted={'ring_finger': Action('keys', keys=('KEY_X',)),
                                     'side_12': Action('keys', keys=('KEY_F23',))}))
        stored = saved_defaults(MODELS[1])
        stored['ring_finger', False] = Action('hypershift', playback='held')
        del stored['ring_finger', True]  # Opaque shifted descriptor is never executed for a trigger.
        assert not unresolved(profile, MODELS[1], stored)
        output = RecordingOutput()
        engine = Engine(MODELS[1], profile, KeyLedger(output), stored=stored)
        router = Router(engine)
        for controls in ({'top_front'}, {'top_front', 'ring_finger'}, {'ring_finger'}):
            await router.feed(Frame('vendor', frozenset(controls)))
        await router.feed(Frame('side', frozenset({'side_12'})))
        await router.feed(Frame('vendor'))
        assert not engine.shifted
        await router.feed(Frame('side'))
        assert output.events == [('key', E.KEY_F23, 1), ('key', E.KEY_F23, 0)]
        assert ('ring_finger', True) not in stored
        assert profile.common.shifted['ring_finger'].keys == ('KEY_X',)
        await router.close()
    asyncio.run(check())
