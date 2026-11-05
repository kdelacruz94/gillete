import asyncio
from copy import deepcopy
import json

from evdev import ecodes as E
import pytest

from gillete.compile_onboard import CONTROL_IDS, compile_profile, encode_action
from gillete.engine import Engine
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, ConfigurationError, Layers, MODELS, Profile, sequence
from gillete.onboard import Location
from gillete.profiles import ProfileStore


def baseline(model):
    values = {Location(1, identifier, layer): bytes.fromhex('0202001e000000')
              for identifier in CONTROL_IDS[model].values() for layer in (0, 1)}
    trigger = 'dpi_up' if model == MODELS[0] else 'ring_finger'
    for layer in (0, 1):
        values[Location(1, CONTROL_IDS[model][trigger], layer)] = encode_action(Action('hypershift', playback='held'), model)
    return values


def macro_profile():
    return Profile('work', 'Work', Layers(normal={'side_12': sequence(('KEY_LEFTCTRL', 'KEY_K'), ('KEY_M',),
                                                                  press_ms=1, gap_ms=1)}))


def test_alternatives_are_model_specific_and_never_replace_linux_macro_playback():
    async def check():
        profile = macro_profile()
        profile.standalone[MODELS[0]] = Layers(normal={'side_12': Action('keys', keys=('KEY_F24',))})
        original = deepcopy(profile.json())
        plan = compile_profile(profile, MODELS[0], 1, baseline(MODELS[0]))
        assert plan.writable
        assert plan.targets[Location(1, 0x4b, 0)] == plan.targets[Location(1, 0x4b, 1)] == bytes.fromhex('02020073000000')
        assert not compile_profile(profile, MODELS[1], 1, baseline(MODELS[1])).writable
        sink = RecordingOutput()
        engine = Engine(MODELS[0], profile, KeyLedger(sink))
        await engine.press('side_12')
        await engine.release('side_12')
        await asyncio.wait_for(asyncio.gather(*engine.macros.jobs.values()), 1)
        assert sink.events == [('key', code, value) for code, value in (
            (E.KEY_LEFTCTRL, 1), (E.KEY_K, 1), (E.KEY_K, 0), (E.KEY_LEFTCTRL, 0), (E.KEY_M, 1), (E.KEY_M, 0))]
        assert profile.json() == original
    asyncio.run(check())


def test_explicit_shifted_macro_needs_its_own_alternative_and_keep_stored_preserves_opaque_bytes():
    profile = macro_profile()
    profile.common.shifted['side_12'] = sequence(('KEY_LEFTALT', 'KEY_H'), ('KEY_O',), ('KEY_A',))
    profile.standalone[MODELS[0]] = Layers(normal={'side_12': Action('keys', keys=('KEY_F24',))})
    values = baseline(MODELS[0])
    values[Location(1, 0x4b, 1)] = bytes.fromhex('05020000000000')
    assert not compile_profile(profile, MODELS[0], 1, values).writable
    profile.standalone[MODELS[0]].shifted['side_12'] = Action()
    plan = compile_profile(profile, MODELS[0], 1, values)
    assert plan.writable and plan.targets[Location(1, 0x4b, 1)] == values[Location(1, 0x4b, 1)]
    assert profile.resolve(MODELS[0], 'side_12', True).kind == 'macro'


def test_alternative_trigger_is_checked_separately_from_software_trigger_and_not_silently_overridden():
    profile = Profile('p', 'P', Layers(normal={'ring_finger': Action('hypershift', playback='toggle')},
                                      shifted={'side_1': Action('keys', keys=('KEY_F23',))}))
    profile.standalone[MODELS[1]] = Layers(normal={'ring_finger': Action('hypershift', playback='held')})
    values = baseline(MODELS[1])
    assert compile_profile(profile, MODELS[1], 1, values).writable
    profile.standalone[MODELS[1]].normal['ring_finger'] = Action('disabled')
    assert any('no HyperShift trigger' in issue for issue in compile_profile(profile, MODELS[1], 1, values).issues)
    profile.standalone[MODELS[1]].normal['ring_finger'] = Action()
    profile.standalone[MODELS[1]].shifted['ring_finger'] = Action('keys', keys=('KEY_A',))
    plan = compile_profile(profile, MODELS[1], 1, values)
    assert not plan.writable and any('remove the shifted standalone alternative' in issue for issue in plan.issues)


def test_standalone_choices_roundtrip_with_profiles_and_legacy_profiles_have_no_implicit_alternatives(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    config = store.read()
    profile = macro_profile()
    legacy = profile.json()
    legacy.pop('standalone')
    assert Profile.parse(legacy).standalone == {}
    profile.standalone[MODELS[0]] = Layers(normal={'side_12': Action('keys', keys=('KEY_F24',))})
    profile.standalone[MODELS[1]] = Layers(normal={'side_12': Action('disabled')})
    config.profiles[profile.id] = profile
    store.save(config, expected_revision=0)
    restored = store.read().profiles[profile.id]
    exported = json.loads(json.dumps({'version': 1, 'profile': restored.json()}))
    assert Profile.parse(exported['profile']).json() == profile.json()
    effective = restored.for_onboard(MODELS[0])
    effective.common.normal.clear()
    effective.overrides[MODELS[0]].normal.clear()
    assert restored.json() == profile.json()


@pytest.mark.parametrize('alternatives', [
    [], {'unknown_mouse': {}}, {MODELS[0]: {'normal': {'ring_finger': Action().json()}}},
    {MODELS[0]: {'normal': {'side_1': Action('launch', argv=('app',)).json()}}},
    {MODELS[0]: {'normal': {'side_1': Action('hypershift', playback='toggle').json()}}},
])
def test_invalid_standalone_imports_are_rejected(alternatives):
    value = Profile('p', 'P').json()
    value['standalone'] = alternatives
    with pytest.raises(ConfigurationError):
        Profile.parse(value)
