from copy import deepcopy
import json

import pytest

from gillete.compile_onboard import CONTROL_IDS, encode_action
from gillete.hypershift import availability, resolve_action
from gillete.model import Action, MODELS, Profile
from gillete.onboard import Location
from gillete.profile_from_mouse import MouseProfileDraft
from gillete.stored_actions import from_snapshot, unresolved
from test_guided_service import snapshot


@pytest.mark.parametrize('model', MODELS)
def test_mouse_read_becomes_explicit_per_mouse_intent_without_factory_guesses_or_other_mouse_changes(model):
    source = snapshot(model)
    before = deepcopy(source)
    draft = MouseProfileDraft(source)
    profile = draft.profile('copied', 'Copied from my mouse')
    stored, _ = from_snapshot(source)
    original = Profile('original', 'Original')
    assert source == before and not profile.common.normal and not profile.common.shifted
    assert not profile.standalone and set(profile.overrides) == {model}
    for control, shifted in draft.rows:
        expected = resolve_action(original, model, control, shifted, stored)
        actual = profile.resolve(model, control, shifted)
        assert actual == expected if expected is not None else actual.kind == 'passthrough'
    other = MODELS[1] if model == MODELS[0] else MODELS[0]
    assert all(profile.resolve(other, control, False).kind == 'passthrough'
               for control in CONTROL_IDS[other])
    assert 'private-test-identity' not in json.dumps(profile.json())
    assert availability(profile, model, stored).triggers
    assert set(unresolved(profile, model, stored)) == set(draft.unknown)


def test_unknowns_stay_unresolved_until_each_disabled_choice_is_explicit():
    source = snapshot(MODELS[0])
    draft = MouseProfileDraft(source)
    stored, _ = from_snapshot(source)
    first = next(iter(draft.unknown))
    profile = draft.profile('copied', 'Copied', disabled={first})
    assert set(unresolved(profile, source.model, stored)) == set(draft.unknown) - {first}
    assert profile.resolve(source.model, *first).kind == 'disabled'
    with pytest.raises(ValueError, match='reviewed assignments'):
        draft.profile('copied', 'Copied', disabled={('ring_finger', False)})
    assert source == snapshot(MODELS[0])


def test_recognized_actions_can_be_explicitly_disabled_locally_without_altering_firmware_intent():
    source = snapshot(MODELS[1])
    draft = MouseProfileDraft(source)
    before = deepcopy(source)
    profile = draft.profile('copied', 'Copied', disabled={('profile_button', False), ('right_click', True)})
    assert profile.resolve(source.model, 'profile_button').kind == 'disabled'
    assert profile.resolve(source.model, 'right_click', True).kind == 'disabled'
    assert source == before
    with pytest.raises(ValueError, match='normal HyperShift trigger'):
        draft.profile('copied', 'Copied', disabled={('ring_finger', True)})


def test_inherited_normal_trigger_is_kept_usable_in_both_layers_even_if_raw_shifted_slot_is_opaque():
    source = snapshot(MODELS[1])
    where = Location(1, CONTROL_IDS[source.model]['ring_finger'], 1)
    source.records[where] = bytes((1, where.control, 0)) + bytes.fromhex('0d04004b008e00')
    draft = MouseProfileDraft(source)
    assert ('ring_finger', True) not in draft.unknown
    profile = draft.profile('copied', 'Copied')
    assert profile.resolve(source.model, 'ring_finger', True) == Action('hypershift', playback='held')


def test_supported_native_body_is_copied_as_editable_steps_without_a_unit_specific_reference():
    source = snapshot(MODELS[1])
    source.metadata['firmware'] = '0101'
    source.native_macros[7] = '017311500273'
    where = Location(1, CONTROL_IDS[source.model]['side_12'], 0)
    source.records[where] = bytes((1, where.control, 0)) + bytes.fromhex('03030007010000')
    draft = MouseProfileDraft(source)
    profile = draft.profile('copied', 'Copied')
    action = profile.resolve(source.model, 'side_12')
    assert action.kind == 'macro' and action.playback == 'once'
    assert [step.key for step in action.steps if step.kind in ('down', 'up')] == ['KEY_F24', 'KEY_F24']
    assert source.native_macros == {7: '017311500273'}
    assert 'native_macros' not in profile.json()


def test_inactive_assigned_slot_can_become_a_draft_without_claiming_it_is_active():
    source = snapshot(MODELS[1])
    source.bank, source.assigned = 2, (1, 2)
    source.records = {Location(2, where.control, where.layer): bytes((2, where.control)) + raw[2:]
                      for where, raw in source.records.items()}
    draft = MouseProfileDraft(source)
    assert draft.bank == 2 and draft.snapshot.active == 1
    assert draft.profile('copied', 'Slot 2').overrides[source.model].normal


@pytest.mark.parametrize('change', ['product', 'missing', 'raw', 'bank', 'inventory'])
def test_incomplete_or_mismatched_source_is_not_misrepresented_as_an_importable_mouse_read(change):
    source = snapshot(MODELS[0])
    if change == 'product': source.product = 0xE8
    elif change == 'missing': source.records.pop(next(iter(source.records)))
    elif change == 'raw': source.records[next(iter(source.records))] = b'bad'
    elif change == 'bank': source.bank = 2
    else: source.controls.clear()
    with pytest.raises(ValueError, match='Cannot copy this mouse read'): MouseProfileDraft(source)


def test_draft_is_frozen_at_review_and_does_not_follow_later_snapshot_mutations():
    source = snapshot(MODELS[0])
    draft = MouseProfileDraft(source)
    where = Location(1, CONTROL_IDS[source.model]['side_12'], 0)
    source.records[where] = bytes((1, where.control, 0)) + encode_action(Action('keys', keys=('KEY_F24',)), source.model)
    assert draft.profile('copied', 'Copied').resolve(source.model, 'side_12').keys == ('KEY_1',)
