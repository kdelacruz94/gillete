from copy import deepcopy
from types import SimpleNamespace

import pytest
from evdev import ecodes

from gillete import native_sequence_probe as seq
from gillete.protocol import ProtocolError
from test_native_profile_probe import prepared_mouse
from test_native_macro_observer import setup, event


def prepared():
    mouse, _ = prepared_mouse()
    mouse.reply_health = {'setting_commands': 0}
    original_exchange, original_binding = mouse._exchange, mouse.write_binding
    def exchange(command):
        mouse.reply_health['setting_commands'] += 1
        return original_exchange(command)
    def binding(*args):
        mouse.reply_health['setting_commands'] += 1
        return original_binding(*args)
    mouse._exchange, mouse.write_binding = exchange, binding
    return mouse, seq.tx.prepare(mouse, seq.test_profile())


def observation():
    raw = [{'key': key, 'down': down, 't': 20. + i * .02} for i, (key, down) in enumerate(seq.EDGES)]
    desktop = [{**e, 'repeat': False, 'modifiers': seq.CONTROL_MODIFIER if e['key'] == 'K' else 0} for e in raw]
    return {'raw': raw, 'desktop': desktop, 'power_cycled': True, 'sequence_completed': True}


def test_combined_case_reuses_without_settings_and_restores_all_three_objects(tmp_path):
    mouse, before = prepared()
    assert len(seq.validate(before).assets) == 3
    result = seq.exercise(mouse, before, tmp_path, lambda _: observation())
    assert result['status'] == 'native-combined-restored' and result['native_sequence_observed']
    assert result['original_state_restored'] and not mouse.macros
    assert result['reused_objects'] == 3 and result['repeated_save_setting_commands'] == 0
    assert len(result['timing_ms']['count_holds']) == 3
    again, _ = seq.recover_all(mouse, tmp_path)
    assert again['original_state_restored'] and not mouse.macros


@pytest.mark.parametrize('failure', ['timeout', 'ctrl-leak', 'missing-count', 'not-cycled', 'wrong-qt-modifier'])
def test_failed_keyboard_or_human_evidence_always_restores(tmp_path, failure):
    mouse, before = prepared()
    def observe(_):
        if failure == 'timeout': raise ProtocolError('timed out')
        result = observation()
        if failure == 'ctrl-leak': result['desktop'][4]['modifiers'] = seq.CONTROL_MODIFIER
        elif failure == 'missing-count': result['raw'].pop()
        elif failure == 'not-cycled': result['power_cycled'] = False
        else: result['desktop'][1]['modifiers'] = 0
        return result
    result = seq.exercise(mouse, before, tmp_path, observe)
    assert result['status'] == 'test-failed-restored' and result['original_state_restored']
    assert not result['native_sequence_observed'] and not mouse.macros


def test_apply_failure_before_pad_ready_restores_without_accepting_keys(tmp_path):
    mouse, before = prepared()
    mouse.fail_write = 6  # Complete first object but lose its ACK.
    result = seq.exercise(mouse, before, tmp_path, lambda _: (_ for _ in ()).throw(AssertionError('Observed before READY')))
    assert result['status'] == 'test-failed-restored' and not mouse.macros


def test_edge_observer_requires_chord_release_order_and_exact_f24_count(monkeypatch):
    events = [event(int(down), 10.1 + i * .03, seq.NAMES[name]) for i, (name, down) in enumerate(seq.EDGES)]
    watcher, _ = setup(monkeypatch, events)
    observer = seq.EdgeObserver(watcher.device)
    observer.sources = watcher.sources
    observer.arm()
    observed = observer.observe(lambda: False)
    seq.validate_edges(observed)
    assert len(observed) == 16


def test_extra_native_key_is_not_silently_ignored(monkeypatch):
    watcher, _ = setup(monkeypatch, [event(1, 10.1, ecodes.KEY_A)])
    observer = seq.EdgeObserver(watcher.device)
    observer.sources = watcher.sources
    observer.arm()
    with pytest.raises(ProtocolError, match='additional'): observer.observe(lambda: False)


def test_extra_native_key_in_last_batch_or_quiet_tail_is_rejected(monkeypatch):
    events = [event(int(down), 10.1 + i * .03, seq.NAMES[name]) for i, (name, down) in enumerate(seq.EDGES)]
    events.append(event(1, 10.8, ecodes.KEY_F24))
    watcher, _ = setup(monkeypatch, events)
    observer = seq.EdgeObserver(watcher.device)
    observer.sources = watcher.sources
    observer.arm()
    with pytest.raises(ProtocolError, match='Extra native'): observer.observe(lambda: False)
    with pytest.raises(ProtocolError, match='after sequence completion'): observer.assert_quiet(lambda: False)


def test_missing_telemetry_or_modified_profile_cannot_claim_acceptance():
    mouse, before = prepared()
    mouse.reply_health = {}
    with pytest.raises(ProtocolError): seq.setting_count(mouse)
    before['profile']['name'] = 'other'
    with pytest.raises(ProtocolError): seq.validate(before)


def test_rejected_native_edge_retains_the_actual_event_and_expected_position(monkeypatch):
    watcher, _ = setup(monkeypatch, [event(1, 10.1, ecodes.KEY_F24)])
    observer = seq.EdgeObserver(watcher.device)
    observer.sources = watcher.sources
    observer.arm()
    with pytest.raises(ProtocolError, match='Unexpected native chord/count'):
        observer.observe(lambda: False)
    trace = observer.trace_document()
    assert trace['expected_edge'] == 0
    assert trace['events'] == [{'source': 0, 'type': ecodes.EV_KEY,
        'code': ecodes.KEY_F24, 'value': 1, 't': 10.1}]
    assert trace['failure'] == 'Unexpected native chord/count key sequence'


def test_failure_trace_is_bounded_keeps_offending_edge_and_survives_transaction_cleanup(monkeypatch, tmp_path):
    import json
    mouse, before = prepared()
    events = [event(1, 10.01 + i * .0001, ecodes.BTN_LEFT) for i in range(200)]
    events.append(event(1, 10.1, ecodes.KEY_F24))
    watcher, _ = setup(monkeypatch, events)
    observer = seq.EdgeObserver(watcher.device)
    observer.sources = watcher.sources
    observer.arm()
    result = seq.exercise(mouse, before, tmp_path, lambda _: observer.observe(lambda: False))
    assert result['status'] == 'test-failed-restored' and result['original_state_restored']
    assert not mouse.macros
    seq.save_input_trace(tmp_path, observer)
    trace = json.loads((tmp_path / 'raw-input.json').read_text())
    assert trace['capped'] and len(trace['events']) == 128
    assert trace['events'][-1]['code'] == ecodes.KEY_F24 and trace['expected_edge'] == 0
    assert 'Unexpected native chord/count' in trace['failure']
    assert (tmp_path / 'raw-input.json').stat().st_mode & 0o777 == 0o600
