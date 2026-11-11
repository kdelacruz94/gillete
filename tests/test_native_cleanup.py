from copy import deepcopy
import json

import pytest

from gillete import native_cleanup as cleanup, native_history
from gillete import native_profile_transaction as tx
from gillete.model import Action, Step
from gillete.protocol import ProtocolError, DeviceUnavailable
from test_native_macro_probe import Mouse
from test_native_profile_transaction import profile


def library(tmp_path, both=False):
    mouse = Mouse()
    mouse.firmware = b'\1\1'
    first = tmp_path / 'native-first/profile.json'
    mouse.journal = first
    tx.apply(mouse, tx.prepare(mouse, profile()), first)
    source = profile()
    controls = ('side_11', 'side_12') if both else ('side_12',)
    for control in controls:
        source.common.normal[control] = Action('macro', steps=(Step('down', 'KEY_A'),
                                                             Step('wait', milliseconds=80), Step('up', 'KEY_A')))
    second = tmp_path / 'native-second/profile.json'
    mouse.journal = second
    tx.apply(mouse, tx.prepare(mouse, source), second)
    mouse.journal = tmp_path / 'native-cleanup-test/cleanup.json'
    return mouse, cleanup.prepare(mouse, tmp_path)


def row(prepared, identifier):
    return next(r for r in prepared['rows'] if r['id'] == identifier)


def test_read_only_review_distinguishes_current_use_and_undo_dependencies(tmp_path):
    mouse, prepared = library(tmp_path)
    assert row(prepared, 1)['references'] and not row(prepared, 1)['deletable']
    assert row(prepared, 2)['deletable'] and not row(prepared, 2)['references']
    assert row(prepared, 2)['undo'] == [{'path': 'native-second/profile.json', 'profile': 'Native game', 'mapping_dependency': True}]
    assert row(prepared, 3)['references'] and not row(prepared, 3)['deletable']
    before = len(mouse.writes)
    cleanup.prepare(mouse, tmp_path)
    assert len(mouse.writes) == before


def test_explicit_acknowledged_cleanup_archives_exact_bytes_without_changing_mappings_or_history(tmp_path):
    mouse, prepared = library(tmp_path)
    original = deepcopy(mouse.macros[2])
    history_before = {p: p.read_bytes() for p in tmp_path.glob('native-*/profile.json')}
    before = len(mouse.writes)
    progress = []
    result = cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True, progress=progress.append)
    assert result['status'] == 'cleanup-readback-verified' and result['unchanged_state_verified']
    assert result['deleted_ids'] == [2] and set(mouse.macros) == {1, 3}
    assert tx.probe.normalized(tx.probe.snapshot(mouse)) == tx.probe.normalized(prepared['before'])
    saved = json.loads(mouse.journal.read_text())
    assert bytes.fromhex(saved['rows'][0]['asset']['data']) == original['data']
    assert bytes.fromhex(saved['rows'][0]['asset']['metadata']) == original['metadata']
    assert all(path.read_bytes() == data for path, data in history_before.items())
    assert [(c.category, c.operation) for c in mouse.writes[before:]] == [(6, 3)] and progress
    assert mouse.journal.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('selected,ack', [([2], False), ([1], True), ([3], True), ([17], True),
                                        ([2, 2], True), ([True], True), ([], True)])
def test_no_deletion_without_exact_unused_selection_and_required_undo_ack(tmp_path, selected, ack):
    mouse, prepared = library(tmp_path)
    before = len(mouse.writes)
    with pytest.raises(ProtocolError): cleanup.apply(mouse, prepared, selected, mouse.journal, tmp_path, acknowledge_undo=ack)
    assert len(mouse.writes) == before and not mouse.journal.exists()


@pytest.mark.parametrize('family', [3, 4, 5, 15])
def test_unknown_controls_unassigned_banks_and_all_macro_families_protect_objects(tmp_path, family):
    mouse, _ = library(tmp_path)
    mouse.functions[5, 0xFE, 1] = bytes((family, 3 if family == 3 else 2, 0, 2, 1 if family == 3 else 0, 0, 0))
    prepared = cleanup.prepare(mouse, tmp_path)
    assert not row(prepared, 2)['deletable']
    assert {'bank': 5, 'control': 0xFE, 'layer': 1} in row(prepared, 2)['references']


@pytest.mark.parametrize('change', ['metadata', 'data', 'foreign', 'other-unit'])
def test_changed_or_unmanaged_objects_are_not_admitted_for_deletion(tmp_path, change):
    mouse, _ = library(tmp_path)
    if change in ('metadata', 'data'): mouse.macros[2][change][-1] ^= 1
    elif change == 'foreign': mouse.macros[9] = {'data': bytearray(b'foreign'), 'metadata': bytearray(250)}
    else:
        for path in tmp_path.glob('native-*/profile.json'):
            document = json.loads(path.read_text())
            document['before']['serial'] = 'another-unit'
            tx.durable_json(path, document)
    before = len(mouse.writes)
    prepared = cleanup.prepare(mouse, tmp_path)
    assert not row(prepared, 9 if change == 'foreign' else 2)['deletable']
    assert len(mouse.writes) == before


@pytest.mark.parametrize('change', ['dpi', 'binding', 'data', 'new-catalog-entry', 'history-edit', 'new-history', 'forged-preview'])
def test_fresh_admission_detects_state_library_or_history_changes_before_any_delete(tmp_path, change):
    mouse, prepared = library(tmp_path)
    if change == 'dpi': mouse.zero = bytes.fromhex('0004b004b00000')
    elif change == 'binding': mouse.functions[5, 0xFE, 1] = bytes.fromhex('03030002010000')
    elif change == 'data': mouse.macros[2]['data'][-1] ^= 1
    elif change == 'new-catalog-entry': mouse.macros[9] = {'data': bytearray(b'foreign'), 'metadata': bytearray(250)}
    elif change in ('history-edit', 'new-history'):
        path = tmp_path / ('native-first' if change == 'history-edit' else 'native-third') / 'profile.json'
        raw = json.loads((tmp_path / 'native-first/profile.json').read_text())
        raw['note'] = 'changed externally'
        tx.durable_json(path, raw)
    else: row(prepared, 2)['asset']['data'] = '00'
    before = len(mouse.writes)
    with pytest.raises(ProtocolError): cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True)
    assert len(mouse.writes) == before and not mouse.journal.exists()


def test_each_deletion_rescans_references_and_stops_before_newly_referenced_second_object(tmp_path):
    mouse, prepared = library(tmp_path, both=True)
    original = mouse._exchange
    def change_after_first(command):
        result = original(command)
        if command.operation == 3:
            mouse.functions[5, 0xFE, 1] = bytes.fromhex('03030002010000')
        return result
    mouse._exchange = change_after_first
    before = len(mouse.writes)
    with pytest.raises(ProtocolError, match='mappings/settings changed'):
        cleanup.apply(mouse, prepared, [1, 2], mouse.journal, tmp_path, acknowledge_undo=True)
    assert 1 not in mouse.macros and 2 in mouse.macros
    assert len(mouse.writes) == before + 1
    assert json.loads(mouse.journal.read_text())['status'] == 'cleanup-incomplete'


def test_delete_reply_loss_is_observed_without_resending_and_fresh_review_remains_available(tmp_path):
    mouse, prepared = library(tmp_path)
    original = mouse._exchange
    def lost(command):
        original(command)
        if command.operation == 3: raise DeviceUnavailable('Delete applied, reply lost')
    mouse._exchange = lost
    before = len(mouse.writes)
    with pytest.raises(DeviceUnavailable): cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True)
    receipt = json.loads(mouse.journal.read_text())
    assert receipt['absent_selected_ids'] == [2] and receipt['status'] == 'cleanup-incomplete'
    assert len(mouse.writes) == before + 1
    fresh = cleanup.prepare(mouse, tmp_path)
    assert 2 not in [r['id'] for r in fresh['rows']]


def test_cancellation_between_objects_keeps_remaining_data_and_never_changes_bindings(tmp_path):
    mouse, prepared = library(tmp_path, both=True)
    before = len(mouse.writes)
    with pytest.raises(InterruptedError):
        cleanup.apply(mouse, prepared, [1, 2], mouse.journal, tmp_path, acknowledge_undo=True,
                      stopped=lambda: len(mouse.writes) > before)
    assert 1 not in mouse.macros and 2 in mouse.macros
    assert tx.probe.normalized(tx.probe.snapshot(mouse)) == tx.probe.normalized(prepared['before'])


@pytest.mark.parametrize('problem', ['corrupt', 'unfinished', 'symlink'])
def test_unreadable_or_unfinished_local_history_cannot_establish_ownership(tmp_path, problem):
    mouse, _ = library(tmp_path)
    path = tmp_path / 'native-first/profile.json'
    if problem == 'corrupt': path.write_text('{invalid')
    elif problem == 'unfinished':
        doc = json.loads(path.read_text())
        doc['status'] = 'recovery-required'
        tx.durable_json(path, doc)
    else:
        path.rename(path.with_name('original.json'))
        path.symlink_to('original.json')
    before = len(mouse.writes)
    with pytest.raises(ValueError): cleanup.prepare(mouse, tmp_path)
    assert len(mouse.writes) == before


def test_nonmatching_firmware_and_reused_cleanup_paths_are_blocked(tmp_path):
    mouse, prepared = library(tmp_path)
    before = len(mouse.writes)
    mouse.firmware = b'\1\2'
    with pytest.raises(ProtocolError, match='firmware'): cleanup.prepare(mouse, tmp_path)
    mouse.firmware = b'\1\1'
    tx.durable_json(mouse.journal, {'version': 1, 'original': 'preserved'})
    with pytest.raises(ProtocolError, match='fresh cleanup'): cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True)
    assert json.loads(mouse.journal.read_text())['original'] == 'preserved' and len(mouse.writes) == before


@pytest.mark.parametrize('failure', [1, 2, 3])
def test_receipt_write_failure_never_loses_archived_bytes_or_retries_a_delete(tmp_path, monkeypatch, failure):
    mouse, prepared = library(tmp_path)
    writer = tx.durable_json
    calls = 0
    def fail_once(path, document):
        nonlocal calls
        calls += 1
        if calls == failure: raise OSError('disk full')
        writer(path, document)
    monkeypatch.setattr(tx, 'durable_json', fail_once)
    before = len(mouse.writes)
    with pytest.raises(OSError, match='disk full'):
        cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True)
    assert len(mouse.writes) - before == (1 if failure == 3 else 0)
    if mouse.journal.exists():
        saved = json.loads(mouse.journal.read_text())
        assert saved['rows'][0]['asset']['data'] == row(prepared, 2)['asset']['data']


def test_history_count_and_cleanup_receipt_admission_limits_precede_deletion(tmp_path, monkeypatch):
    mouse, prepared = library(tmp_path)
    row(prepared, 2)['asset']['data'] = '00' * tx.MAX_JOURNAL_BYTES
    before = len(mouse.writes)
    with pytest.raises(ProtocolError, match='too large'):
        cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True)
    monkeypatch.setattr(native_history, 'MAX_RECEIPTS', 1)
    with pytest.raises(ProtocolError, match='Too many'): cleanup.prepare(mouse, tmp_path)
    assert len(mouse.writes) == before


def test_cancellation_during_durable_intent_write_still_precedes_the_setter(tmp_path, monkeypatch):
    mouse, prepared = library(tmp_path)
    writer = tx.durable_json
    cancelled = False
    def cancel_after_intent(path, document):
        nonlocal cancelled
        writer(path, document)
        if document['status'] == 'deleting-managed-macro': cancelled = True
    monkeypatch.setattr(tx, 'durable_json', cancel_after_intent)
    before = len(mouse.writes)
    with pytest.raises(InterruptedError, match='before deletion'):
        cleanup.apply(mouse, prepared, [2], mouse.journal, tmp_path, acknowledge_undo=True, stopped=lambda: cancelled)
    assert len(mouse.writes) == before and 2 in mouse.macros
