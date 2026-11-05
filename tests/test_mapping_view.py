from copy import deepcopy

import pytest

from gillete.mapping_view import editing_action, explicit_action, rows, view
from gillete.model import Action, Layers, MODEL_CONTROLS, MODELS, Profile


def key(name):
    return Action('keys', keys=('KEY_' + name,))


def test_shared_edit_starts_from_shared_value_even_when_an_override_is_effective():
    profile = Profile('p', 'Profile', Layers(normal={'side_1': key('A')}, shifted={'side_1': key('C')}),
                      {MODELS[0]: Layers(normal={'side_1': key('B')}, shifted={'side_1': key('D')})})
    original = deepcopy(profile.json())
    for shifted, shared, device in ((False, 'A', 'B'), (True, 'C', 'D')):
        assert editing_action(profile, MODELS[0], 'side_1', shifted, 'common') == key(shared)
        assert editing_action(profile, MODELS[0], 'side_1', shifted, 'device') == key(device)
        current = view(profile, MODELS[0], 'side_1', shifted)
        assert current.action == key(device) and current.source == 'This mouse’s override'
        assert view(profile, MODELS[1], 'side_1', shifted).source == 'Shared mapping'
    assert profile.json() == original


def test_shifted_shared_action_precedes_inherited_device_normal_and_remove_reveals_it():
    profile = Profile('p', 'P', Layers(normal={'side_1': key('A')}, shifted={'side_1': key('C')}),
                      {MODELS[0]: Layers(normal={'side_1': key('B')})})
    assert view(profile, MODELS[0], 'side_1', True).action == key('C')
    assert view(profile, MODELS[0], 'side_1', True).source == 'Shared mapping'
    del profile.common.shifted['side_1']
    current = view(profile, MODELS[0], 'side_1', True)
    assert current.action == key('B')
    assert current.source == 'This mouse’s override · inherited from Normal'
    assert editing_action(profile, MODELS[0], 'side_1', True, 'common') == key('A')
    assert editing_action(profile, MODELS[0], 'side_1', True, 'device') == key('B')
    assert explicit_action(profile, MODELS[0], 'side_1', True, 'device') is None


def test_stored_layers_unknowns_and_inherited_trigger_are_not_confused():
    profile = Profile('p', 'P')
    stored = {('side_1', False): key('A'), ('side_1', True): key('B')}
    assert view(profile, MODELS[0], 'side_1').description == 'Stored mouse assignment'
    assert 'not read' in view(profile, MODELS[0], 'side_1').source
    assert view(profile, MODELS[0], 'side_1', True, stored).description == 'Stored: B'
    assert 'HyperShift' in view(profile, MODELS[0], 'side_1', True, stored).source
    assert 'inherited from Normal' not in view(profile, MODELS[0], 'side_1', True, stored).source
    stored.pop(('side_1', True))
    assert view(profile, MODELS[0], 'side_1', True, stored).description == 'Stored action not decoded'
    stored['side_1', False] = Action('hypershift', playback='held')
    profile.common.shifted['side_1'] = key('C')
    current = view(profile, MODELS[0], 'side_1', True, stored)
    assert current.action.kind == 'hypershift' and current.description == 'Stored HyperShift trigger (hold)'
    assert 'Mouse memory · Normal' in current.source and 'Normal trigger stays active' in current.source
    profile.overrides[MODELS[0]] = Layers(normal={'side_1': Action('hypershift', playback='toggle')})
    current = view(profile, MODELS[0], 'side_1', True, stored)
    assert current.action.playback == 'toggle' and current.source == 'This mouse’s override · Normal trigger stays active'
    # Editing a shared shifted action is still possible when only the selected
    # mouse has an explicit normal trigger override.
    assert editing_action(profile, MODELS[0], 'side_1', True, 'common') == key('C')


def test_explicit_passthrough_identifies_the_override_that_requests_mouse_memory():
    profile = Profile('p', 'P', Layers(normal={'side_1': key('A')}),
                      {MODELS[0]: Layers(shifted={'side_1': Action()})})
    current = view(profile, MODELS[0], 'side_1', True, {('side_1', True): key('Z')})
    assert current.description == 'Stored: Z'
    assert 'This mouse’s override' in current.source
    assert explicit_action(profile, MODELS[0], 'side_1', True, 'device') == Action()
    with pytest.raises(ValueError, match='Unknown mapping scope'):
        editing_action(profile, MODELS[0], 'side_1', True, 'invalid')


def test_other_mouse_rows_include_shared_override_and_standalone_assignments_only():
    profile = Profile('p', 'P', Layers(normal={'ring_finger': Action('hypershift', playback='held')}),
                      {MODELS[1]: Layers(shifted={'top_rear': key('A')})},
                      {MODELS[1]: Layers(normal={'profile_button': key('B')})})
    actual = rows(profile, MODELS[0])
    assert actual[:21] == [(MODELS[0], c) for c in MODEL_CONTROLS[MODELS[0]]]
    assert actual[21:] == [(MODELS[1], c) for c in ('ring_finger', 'top_rear', 'profile_button')]
    assert rows(profile, MODELS[1]) == [(MODELS[1], c) for c in MODEL_CONTROLS[MODELS[1]]]
    assert rows(Profile('empty', 'Empty'), MODELS[0]) == actual[:21]
