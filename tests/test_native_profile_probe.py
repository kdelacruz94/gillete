from types import SimpleNamespace

import pytest
from evdev import ecodes

from gillete import native_profile_probe as probe
from gillete.native_macro_observer import SequenceObserver
from gillete.protocol import ProtocolError
from test_native_macro_probe import Mouse
from test_native_macro_observer import setup, event


def prepared_mouse():
    mouse = Mouse()
    for layer in (0, 1): mouse.functions[1, 0x39, layer] = bytes.fromhex('0c013900000000')
    return mouse, probe.tx.prepare(mouse, probe.test_profile())


def observation():
    return {'sequence': [{'key': key, 'hold_ms': 81.} for key in probe.EXPECTED], 'sequence_completed': True}


def test_fixed_shared_assets_and_hypershift_sequence_restore_complete_state(tmp_path):
    mouse, prepared = prepared_mouse()
    assert len(probe.validate(prepared).assets) == 2
    result = probe.exercise(mouse, prepared, tmp_path, lambda _: observation())
    assert result['status'] == 'native-profile-test-restored' and result['native_sequence_observed']
    assert result['original_state_restored'] and not mouse.macros
    assert probe.probe.normalized(probe.probe.snapshot(mouse)) == probe.probe.normalized(prepared['before'])


@pytest.mark.parametrize('failure', ['timeout', 'wrong-order', 'unconfirmed'])
def test_missing_or_wrong_observations_restore_without_claiming_acceptance(tmp_path, failure):
    mouse, prepared = prepared_mouse()
    def observe(_):
        if failure == 'timeout': raise ProtocolError('timed out')
        result = observation()
        if failure == 'wrong-order': result['sequence'][1]['key'] = 'F24'
        else: result['sequence_completed'] = False
        return result
    result = probe.exercise(mouse, prepared, tmp_path, observe)
    assert result['status'] == 'test-failed-restored'
    assert not result['native_sequence_observed'] and result['original_state_restored'] and not mouse.macros


def test_incomplete_apply_uses_same_recovery_path_and_retains_unknown_allocation(tmp_path):
    mouse, prepared = prepared_mouse()
    mouse.fail_write = 1
    result = probe.exercise(mouse, prepared, tmp_path, lambda _: observation())
    assert result['status'] == 'recovery-required' and not result['native_sequence_observed']
    assert not any(c.category == 2 for c in mouse.writes)


def test_sequence_observer_requires_actual_ordered_pairs_and_records_timing(monkeypatch):
    watcher, _ = setup(monkeypatch, [event(value, 10.01 + i * .2 + value_offset, code)
                         for i, code in enumerate(SequenceObserver.expected)
                         for value, value_offset in ((1, 0), (0, .08))])
    observed = SequenceObserver(watcher.device)
    observed.sources = watcher.sources
    observed.arm()
    result = observed.observe(lambda: False)
    assert [e['key'] for e in result['sequence']] == list(probe.EXPECTED)
    assert all(e['hold_ms'] == pytest.approx(80.) for e in result['sequence'])


def test_sequence_observer_rejects_wrong_order_and_requires_user_report(monkeypatch, tmp_path):
    watcher, _ = setup(monkeypatch, [event(1, 10.1, ecodes.KEY_F23)])
    observed = SequenceObserver(watcher.device)
    observed.sources = watcher.sources
    observed.arm()
    with pytest.raises(ProtocolError, match='order'): observed.observe(lambda: False)
    observed = SimpleNamespace(armed_at=10., observe=lambda _: {'sequence': observation()['sequence']})
    report = tmp_path / 'report.json'
    report.write_text('{"sequence_completed": true}')
    assert probe.observe_sequence(observed, report, lambda: False, now=lambda: 10.) == observation()
    report.write_text('{"sequence_completed": 1}')
    with pytest.raises(ProtocolError, match='explicit'): probe.observe_sequence(observed, report, lambda: False, now=lambda: 10.)


def test_test_profile_and_existing_trigger_cannot_be_substituted():
    mouse, prepared = prepared_mouse()
    prepared['profile']['name'] = 'different'
    with pytest.raises(ProtocolError): probe.validate(prepared)
    mouse.functions[1, 0x39, 0] = bytes(7)
    with pytest.raises(ProtocolError): probe.validate(probe.tx.prepare(mouse, probe.test_profile()))
