import pytest

from gillete import native_profile_transaction as tx
from gillete.protocol import ProtocolError
from test_native_macro_reuse import first_save, second_save


def test_scoped_undo_preserves_later_dpi_and_unrelated_mapping(tmp_path):
    mouse, _ = first_save(tmp_path)
    mouse.zero = bytes.fromhex('00064006400000')
    mouse.values['dpi'] = bytes.fromhex('01064006400000')
    mouse.functions[1, 1, 0] = bytes.fromhex('02020004000000')
    result = tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert result['status'] == 'affected-bindings-restored'
    assert result['affected_assignments_restored'] and result['unrelated_state_preserved']
    assert not result['original_state_restored'] and not mouse.macros
    assert mouse.zero.hex() == '00064006400000' and mouse.values['dpi'].hex() == '01064006400000'
    assert mouse.read_binding(1, 1, 0).hex() == '02020004000000'
    writes = len(mouse.writes)
    tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert len(mouse.writes) == writes


@pytest.mark.parametrize('family', [3, 5, 15])
def test_objects_shared_by_another_bank_or_unknown_control_are_retained(tmp_path, family):
    mouse, _ = first_save(tmp_path)
    mouse.functions[5, 0xFE, 1] = bytes((family, 3 if family == 3 else 2, 0, 1, 1 if family == 3 else 0, 0, 0))
    result = tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert result['status'] == 'affected-bindings-restored' and set(mouse.macros) == {1}
    assert result['retained_macros'][0]['id'] == 1
    assert 'Referenced' in result['retained_macros'][0]['reason']


@pytest.mark.parametrize('field', ['data', 'metadata'])
def test_modified_owned_objects_are_preserved_without_overwriting_external_data(tmp_path, field):
    mouse, _ = first_save(tmp_path)
    mouse.macros[1][field][-1] ^= 1
    changed = bytes(mouse.macros[1][field])
    result = tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert set(mouse.macros) == {1} and bytes(mouse.macros[1][field]) == changed
    assert result['affected_assignments_restored'] and 'match' in result['retained_macros'][0]['reason']


def test_unrelated_external_catalog_entries_are_not_deleted(tmp_path):
    mouse, _ = first_save(tmp_path)
    mouse.macros[17] = {'data': bytearray(b'external'), 'metadata': bytearray(250)}
    result = tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert result['affected_assignments_restored'] and set(mouse.macros) == {17}


@pytest.mark.parametrize('change', ['missing', 'edited'])
def test_original_dependencies_are_still_checked_before_any_inverse_write(tmp_path, change):
    mouse, _ = first_save(tmp_path)
    prepared, path = second_save(mouse, tmp_path, changed=True)
    tx.apply(mouse, prepared, path)
    if change == 'missing': mouse.macros.pop(2)
    else: mouse.macros[2]['data'][-1] ^= 1
    writes = len(mouse.writes)
    with pytest.raises(ProtocolError): tx.undo(mouse, path, preserve_unrelated=True)
    assert len(mouse.writes) == writes and 3 in mouse.macros


def test_unrelated_reused_macro_edit_does_not_prevent_restoring_other_groups(tmp_path):
    mouse, _ = first_save(tmp_path)
    prepared, path = second_save(mouse, tmp_path, changed=True)
    tx.apply(mouse, prepared, path)
    mouse.macros[1]['data'][-1] ^= 1
    changed = bytes(mouse.macros[1]['data'])
    result = tx.undo(mouse, path, preserve_unrelated=True)
    assert result['affected_assignments_restored'] and not result['original_state_restored']
    assert set(mouse.macros) == {1, 2} and bytes(mouse.macros[1]['data']) == changed
    assert mouse.read_binding(1, 0x4B, 0)[2:4] == b'\0\2'


def test_external_edit_of_affected_mapping_blocks_scoped_overwrite(tmp_path):
    mouse, _ = first_save(tmp_path)
    mouse.functions[1, 0x4B, 0] = bytes.fromhex('02020004000000')
    writes = len(mouse.writes)
    with pytest.raises(ProtocolError, match='affected mapping changed'): tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert len(mouse.writes) == writes and len(mouse.macros) == 2


def test_external_active_edit_of_affected_mapping_blocks_scoped_overwrite(tmp_path):
    mouse, _ = first_save(tmp_path)
    original_read = mouse.read_binding_record
    def active_override(bank, control, layer):
        raw = original_read(bank, control, layer)
        return raw[:3] + bytes.fromhex('02020004000000') if (bank, control, layer) == (0, 0x4B, 0) else raw
    mouse.read_binding_record = active_override
    writes = len(mouse.writes)
    with pytest.raises(ProtocolError, match='affected active mapping changed'):
        tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert len(mouse.writes) == writes and len(mouse.macros) == 2


def test_active_stored_mismatch_is_rejected_before_native_save_writes(tmp_path):
    from test_native_profile_transaction import setup
    mouse, prepared = setup(tmp_path)
    for name in ('records', 'all_records'):
        for entry in prepared['before'][name]:
            if (entry['bank'], entry['control'], entry['layer']) == (0, 0x4B, 0):
                entry['raw'] = entry['raw'][:6] + '02020004000000'
    with pytest.raises(ProtocolError, match='Active and stored'): tx.apply(mouse, prepared, mouse.journal)
    assert not mouse.writes


def test_communication_failure_is_not_reported_as_successful_shared_object_retention(tmp_path):
    mouse, _ = first_save(tmp_path)
    original = mouse.execute
    def fail_read(command):
        if command.category == 6 and command.operation == 0x89:
            raise ProtocolError('Invalid report length or checksum')
        return original(command)
    mouse.execute = fail_read
    with pytest.raises(ProtocolError, match='checksum'): tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert set(mouse.macros) == {1, 2}
    mouse.execute = original
    assert tx.undo(mouse, mouse.journal, preserve_unrelated=True)['original_state_restored']


@pytest.mark.parametrize('change', ['controls', 'storage'])
def test_geometry_changes_are_not_treated_as_unrelated_user_edits(tmp_path, change):
    mouse, _ = first_save(tmp_path)
    if change == 'controls': mouse.controls += (0xFD,)
    else:
        original = mouse.execute
        def smaller(command):
            raw = original(command)
            return b'\0\x7f' + raw[2:] if command.category == 6 and command.operation == 0x8E else raw
        mouse.execute = smaller
    writes = len(mouse.writes)
    with pytest.raises(ProtocolError, match='changed'): tx.undo(mouse, mouse.journal, preserve_unrelated=True)
    assert len(mouse.writes) == writes
