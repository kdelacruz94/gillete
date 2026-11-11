import json

import pytest

from gillete import native_profile_transaction as tx
from gillete.model import Action, Layers, Profile, Step
from gillete.protocol import ProtocolError
from test_native_macro_probe import Mouse


def profile():
    def macro(key):
        return Action('macro', steps=(Step('down', key), Step('wait', milliseconds=80), Step('up', key)))
    return Profile('native-game', 'Native game', Layers(normal={'side_11': macro('KEY_F23'),
        'side_12': macro('KEY_F24'), 'ring_finger': Action('hypershift', playback='held')}))


def setup(tmp_path, mouse=None):
    mouse = mouse or Mouse()
    prepared = tx.prepare(mouse, profile())
    mouse.journal = tmp_path / 'profile.json'
    return mouse, prepared


def test_multiple_asset_profile_save_leaves_verified_bindings_and_explicit_undo(tmp_path):
    mouse, prepared = setup(tmp_path)
    assert not mouse.writes and len(prepared['artifacts']['assets']) == 2
    result = tx.apply(mouse, prepared, mouse.journal)
    assert result['status'] == 'saved-readback-verified' and len(mouse.macros) == 2
    assert json.loads(mouse.journal.read_text()) == result
    first_binding = next(i for i, c in enumerate(mouse.writes) if c.category == 2)
    assert sum(c.operation == 9 for c in mouse.writes[:first_binding]) == 2
    tx.restore(mouse, result, mouse.journal)
    assert result['original_state_restored'] and not mouse.macros
    assert tx.probe.normalized(tx.probe.snapshot(mouse)) == tx.probe.normalized(prepared['before'])


@pytest.mark.parametrize('write', [1, 2, 7, 12, 13])
def test_lost_ack_never_repeats_upload_and_rollback_preserves_unknown_partial_objects(tmp_path, write):
    mouse, prepared = setup(tmp_path)
    mouse.fail_write = write
    with pytest.raises(Exception): tx.apply(mouse, prepared, mouse.journal)
    result = json.loads(mouse.journal.read_text())
    assert result['status'] in ('failed-restored', 'recovery-required')
    allocations = [int.from_bytes(c.payload[:2], 'big') for c in mouse.writes if c.category == 6 and c.operation == 8]
    assert len(allocations) == len(set(allocations))
    assert tx.probe.normalized(tx.probe.snapshot(mouse)) == tx.probe.normalized(prepared['before'])
    if write in (1, 2, 7): assert result['status'] == 'recovery-required'
    else: assert result['original_state_restored'] and not mouse.macros


def test_existing_macro_data_and_sequence_references_are_preserved(tmp_path):
    mouse = Mouse()
    mouse.macros[1] = {'data': bytearray(b'original'), 'metadata': bytearray(250)}
    mouse.functions[5, 0xFE, 1] = bytes.fromhex('0f020002000000')
    mouse, prepared = setup(tmp_path, mouse)
    assert tx.referenced_ids(prepared['before']) == [0, 2]
    assert [a['identifier'] for a in prepared['artifacts']['assets']] == [3, 4]
    result = tx.apply(mouse, prepared, mouse.journal)
    tx.restore(mouse, result, mouse.journal)
    assert set(mouse.macros) == {1} and mouse.macros[1]['data'] == b'original'


def test_stale_preparation_and_forged_artifacts_cannot_submit_setters(tmp_path):
    mouse, prepared = setup(tmp_path)
    prepared['artifacts']['assets'][0]['data'] = 'ffff'
    with pytest.raises(ProtocolError): tx.apply(mouse, prepared, mouse.journal)
    assert not mouse.writes
    prepared = tx.prepare(mouse, profile())
    mouse.zero = bytes.fromhex('00064006400000')
    with pytest.raises(ProtocolError, match='changed since'): tx.apply(mouse, prepared, mouse.journal)
    assert not mouse.writes


def test_external_binding_change_blocks_undo_and_never_deletes_shared_assets(tmp_path):
    mouse, prepared = setup(tmp_path)
    result = tx.apply(mouse, prepared, mouse.journal)
    mouse.functions[1, 0x4B, 0] = bytes.fromhex('02020004000000')
    with pytest.raises(ProtocolError, match='externally'): tx.restore(mouse, result, mouse.journal)
    assert len(mouse.macros) == 2


def test_cancel_after_assets_upload_restores_without_binding_any_macro(tmp_path):
    mouse, prepared = setup(tmp_path)
    def stopped(): return len(mouse.writes) >= 12
    with pytest.raises(InterruptedError): tx.apply(mouse, prepared, mouse.journal, stopped=stopped)
    assert not mouse.macros
    assert not any(c.category == 2 for c in mouse.writes)


def test_undo_reloads_parent_and_is_repeatable_without_redeleting_assets(tmp_path):
    mouse, prepared = setup(tmp_path)
    tx.apply(mouse, prepared, mouse.journal)
    result = tx.undo(mouse, mouse.journal)
    assert result['status'] == 'restored-readback-verified'
    writes = len(mouse.writes)
    assert tx.undo(mouse, mouse.journal)['original_state_restored']
    assert len(mouse.writes) == writes


def test_disk_full_after_binding_restores_buttons_and_retains_unbound_assets(tmp_path, monkeypatch):
    import gillete.onboard as onboard
    mouse, prepared = setup(tmp_path)
    original = mouse.write_binding
    def full(*_): raise OSError('disk full')
    def write(*args):
        original(*args)
        monkeypatch.setattr(tx, 'durable_json', full)
        monkeypatch.setattr(onboard, 'durable_json', full)
    mouse.write_binding = write
    with pytest.raises(OSError): tx.apply(mouse, prepared, mouse.journal)
    assert len(mouse.macros) == 2
    assert tx.probe.normalized(tx.probe.snapshot(mouse)) == tx.probe.normalized(prepared['before'])


def test_transport_counters_are_copied_into_durable_save_and_undo_receipts(tmp_path):
    mouse, prepared = setup(tmp_path)
    mouse.reply_health = {'malformed_reports': 1, 'exchanges_with_malformed_reports': 1}
    saved = tx.apply(mouse, prepared, mouse.journal)
    mouse.reply_health['malformed_reports'] = 2
    assert saved['transport_health']['malformed_reports'] == 1
    assert json.loads(mouse.journal.read_text())['transport_health']['malformed_reports'] == 1
    restored = tx.undo(mouse, mouse.journal)
    assert restored['transport_health']['malformed_reports'] == 2


def test_oversized_receipt_cannot_replace_readable_originals_or_submit_setters(tmp_path):
    mouse, prepared = setup(tmp_path)
    prepared['oversized_context'] = 'x' * tx.MAX_JOURNAL_BYTES
    with pytest.raises(ProtocolError, match='too large'): tx.apply(mouse, prepared, mouse.journal)
    assert not mouse.writes and not mouse.journal.exists()
    tx.durable_json(mouse.journal, {'version': 1, 'originals': 'preserved'})
    original = mouse.journal.read_bytes()
    with pytest.raises(ProtocolError, match='readable size limit'): tx.durable_json(mouse.journal, prepared)
    assert mouse.journal.read_bytes() == original
