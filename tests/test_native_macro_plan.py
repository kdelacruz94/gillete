from copy import deepcopy

import pytest

from gillete.compile_onboard import CONTROL_IDS, compile_profile
from gillete.model import Action, Layers, MODELS, Profile, Step
from gillete.native_macro_plan import preview_profile
from gillete.onboard import Location
from gillete.protocol import ProtocolError


MODEL = MODELS[1]


def macro(key='KEY_F24', **kwargs):
    return Action('macro', steps=(Step('down', key), Step('wait', milliseconds=80), Step('up', key)), **kwargs)


def baseline():
    return {Location(1, control, layer): bytes.fromhex('02020004000000')
            for control in CONTROL_IDS[MODEL].values() for layer in (0, 1)}


def preview(profile, **kwargs):
    parameters = dict(catalog_ids=[1, 4], referenced_ids=[0, 2, 8], available_bytes=307200, slot_capacity=128)
    parameters.update(kwargs)
    return preview_profile(profile, 0xE8, 1, baseline(), **parameters)


def test_profile_asset_dedup_avoids_catalog_and_dangling_references_without_mutating_inputs():
    profile = Profile('game', 'Game', Layers(normal={'side_12': macro(), 'side_11': macro(),
                                                   'ring_finger': Action('hypershift', playback='held')}))
    original = deepcopy(profile.json())
    result = preview(profile)
    assert not result.issues and len(result.assets) == 1
    asset = result.assets[0]
    assert asset.identifier == 3 and asset.data.hex() == '017311500273'
    assert asset.items == 3 and len(asset.metadata) == 250 and result.required_bytes == 512
    for control in ('side_12', 'side_11'):
        for layer in (0, 1):
            assert result.bindings[Location(1, CONTROL_IDS[MODEL][control], layer)].hex() == '03030003010000'
    assert profile.json() == original
    assert any('HyperShift' in item for item in result.validation_pending)
    assert not hasattr(result, 'writable') and not hasattr(result, 'apply')
    assert compile_profile(profile, MODEL, 1, baseline()).issues  # Production gate remains intact.


def test_different_events_create_separate_objects_but_keep_unknown_stored_layers():
    profile = Profile('game', 'Game', Layers(normal={'side_12': macro(), 'side_11': macro('KEY_F23'),
                                                   'ring_finger': Action('hypershift', playback='held')}))
    result = preview(profile)
    assert [asset.identifier for asset in result.assets] == [3, 5]
    assert len({asset.guid for asset in result.assets}) == 2 and result.required_bytes == 1024
    assert result.bindings[Location(1, CONTROL_IDS[MODEL]['left_click'], 0)] == baseline()[Location(1, CONTROL_IDS[MODEL]['left_click'], 0)]
    assert any('Multiple' in item for item in result.validation_pending)
    assert preview(profile).assets == result.assets  # Review bytes are deterministic.


def test_standalone_alternative_replaces_macro_only_for_onboard_and_inherited_shift():
    profile = Profile('game', 'Game', Layers(normal={'side_12': macro()}),
                      standalone={MODEL: Layers(normal={'side_12': Action('keys', keys=('KEY_F23',))})})
    result = preview(profile)
    assert not result.assets and not result.issues
    assert profile.resolve(MODEL, 'side_12').kind == 'macro'
    assert result.bindings[Location(1, CONTROL_IDS[MODEL]['side_12'], 0)].hex() == '02020072000000'


def test_capacity_checks_never_count_reclaimable_space_or_propose_defragmenting():
    profile = Profile('game', 'Game', Layers(normal={'side_12': macro()}))
    result = preview(profile, available_bytes=511, slot_capacity=2)
    assert any('already-free' in issue for issue in result.issues)
    assert any('slot capacity' in issue for issue in result.issues)
    assert preview(profile, available_bytes=512).required_bytes == 512


def test_repeat_timing_difference_and_long_unicode_names_are_explicit():
    profile = Profile('game', '猫' * 100, Layers(normal={'side_12': macro(playback='count', count=3, interval_ms=100)}))
    result = preview(profile)
    assert any('final iteration' in warning for warning in result.warnings)
    assert any('count/held/toggle' in item for item in result.validation_pending)
    assert len(result.assets[0].name.encode('utf-8')) <= 99
    assert result.assets[0].metadata[20:120].split(b'\0')[0].decode('utf-8') == result.assets[0].name


def test_shared_native_body_keeps_each_bindings_own_repeat_count():
    profile = Profile('game', 'Game', Layers(normal={'side_11': macro(playback='count', count=2),
        'side_12': macro(playback='count', count=5), 'ring_finger': Action('hypershift', playback='held')}))
    result = preview(profile)
    assert len(result.assets) == 1
    for control, count in [('side_11', 2), ('side_12', 5)]:
        for layer in (0, 1):
            function = result.bindings[Location(1, CONTROL_IDS[MODEL][control], layer)]
            assert function[:4] == bytes.fromhex('03030003') and function[4] == count


def test_unencodable_action_blocks_preview_without_silently_remapping_it():
    profile = Profile('game', 'Game', Layers(normal={'side_12': Action('launch', argv=('example-program',))}))
    result = preview(profile)
    assert not result.assets and any('launch' in issue for issue in result.issues)
    assert Location(1, CONTROL_IDS[MODEL]['side_12'], 0) not in result.bindings


@pytest.mark.parametrize('parameters', [dict(catalog_ids=[1, 1]), dict(catalog_ids=[0]),
    dict(referenced_ids=[True]), dict(available_bytes=True), dict(slot_capacity=1),
    dict(referenced_ids=[32768]), dict(slot_capacity=0)])
def test_invalid_snapshot_inputs_are_rejected(parameters):
    with pytest.raises(ProtocolError): preview(Profile('game', 'Game'), **parameters)


@pytest.mark.parametrize('product', [0xB4, 0xE7, True])
def test_unverified_native_storage_transports_are_not_silently_substituted(product):
    with pytest.raises(ProtocolError):
        preview_profile(Profile('game', 'Game'), product, 1, baseline(), catalog_ids=[],
                        referenced_ids=[], available_bytes=307200, slot_capacity=128)
