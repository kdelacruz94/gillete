from copy import deepcopy

import pytest

from gillete import native_profile_review as review
from gillete.native_profile_support import save_issues
from gillete.protocol import ProtocolError
from gillete.model import Action, Layers, Profile, Step
from test_native_profile_review import inputs


def fixture():
    mouse, prepared, snapshot, device = inputs()
    mouse.firmware = b'\1\1'
    source = Profile.parse(prepared['profile'])
    for control in ('side_11', 'side_12'):
        source.common.shifted[control] = Action('macro', steps=(Step('down', 'KEY_A'),
                                         Step('wait', milliseconds=80), Step('up', 'KEY_A')))
    return mouse, review.tx.prepare(mouse, source), device


def test_verified_receiver_firmware_and_single_key_once_profile_pass_save_gate():
    _, prepared, _ = fixture()
    assert save_issues(prepared) == []
    altered = deepcopy(prepared)
    altered['before']['firmware'] = '0102'
    assert any('firmware 1.1' in issue for issue in save_issues(altered))


@pytest.mark.parametrize('action', [Action('turbo', keys=('KEY_1',), playback='toggle'),
    Action('macro', steps=(Step('down', 'KEY_F23'), Step('up', 'KEY_F23'))),
    Action('macro', steps=(Step('down', 'KEY_F24'), Step('up', 'KEY_F24')), playback='held'),
    Action('macro', steps=(Step('down', 'KEY_LEFTCTRL'), Step('down', 'KEY_K'), Step('up', 'KEY_K'), Step('up', 'KEY_LEFTCTRL')), playback='count', count=3),
    Action('macro', steps=(Step('down', 'BTN_LEFT'), Step('up', 'BTN_LEFT')))])
def test_unaccepted_native_modes_remain_blocked_but_linux_action_is_preserved(action):
    mouse, _, _ = fixture()
    profile = Profile('unaccepted', 'Unaccepted', Layers(normal={'side_12': action}))
    prepared = review.tx.prepare(mouse, profile)
    assert save_issues(prepared)
    assert Profile.parse(prepared['profile']).resolve('naga_v3_pro', 'side_12') == action


def test_accepted_combined_keyboard_cases_pass_native_save_gate():
    from gillete.native_sequence_probe import test_profile
    mouse, _, _ = fixture()
    prepared = review.tx.prepare(mouse, test_profile())
    assert save_issues(prepared) == []
    assert prepared['validation_pending'] == []
    assert any('completion' in warning for warning in prepared['warnings'])


@pytest.mark.parametrize('count', [1, 2, 3, 255])
def test_native_single_key_count_uses_source_backed_byte_limit(count):
    mouse, _, _ = fixture()
    profile = Profile('count', 'Count', Layers(normal={'side_12': Action('macro',
        steps=(Step('down', 'KEY_F24'), Step('wait', milliseconds=40), Step('up', 'KEY_F24')),
        playback='count', count=count, interval_ms=150)}))
    assert save_issues(review.tx.prepare(mouse, profile)) == []


def test_more_than_one_byte_repeat_count_cannot_reach_a_native_save():
    mouse, _, _ = fixture()
    profile = Profile('too-many', 'Too many', Layers(normal={'side_12': Action('macro',
        steps=(Step('down', 'KEY_F24'), Step('up', 'KEY_F24')), playback='count', count=256)}))
    with pytest.raises(ProtocolError, match='255'):
        review.tx.prepare(mouse, profile)
    assert not mouse.writes


def test_desktop_explicit_save_and_hardware_restore_route_share_asset_aware_backend(tmp_path, monkeypatch):
    mouse, prepared, device = fixture()
    monkeypatch.setattr(review, 'socket_path', lambda: tmp_path / 'service-not-running')
    monkeypatch.setattr(review, '_transport', lambda _: mouse)
    path = tmp_path / 'native-save/profile.json'
    result = review.save_review(device, prepared, path)
    assert result['status'] == 'saved-readback-verified' and len(mouse.macros) == 2
    result = review.hardware.restore(device, path)
    assert result['original_state_restored'] and not mouse.macros


def test_unaccepted_save_or_wrong_device_never_opens_transport(tmp_path, monkeypatch):
    mouse, prepared, device = fixture()
    monkeypatch.setattr(review, '_transport', lambda _: (_ for _ in ()).throw(AssertionError('Transport opened')))
    prepared['before']['firmware'] = '0200'
    with pytest.raises(ProtocolError, match='blocked'): review.save_review(device, prepared, tmp_path / 'profile.json')
    prepared['before']['firmware'] = '0101'
    device.product_id = 0xB4
    monkeypatch.setattr(review, 'socket_path', lambda: tmp_path / 'none')
    with pytest.raises(ProtocolError, match='differs'): review.save_review(device, prepared, tmp_path / 'profile.json')
    assert not mouse.writes
