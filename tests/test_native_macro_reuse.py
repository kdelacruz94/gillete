from copy import deepcopy

import pytest

from gillete import native_profile_transaction as tx
from gillete.protocol import ProtocolError
from gillete.model import Action, Step
from test_native_profile_transaction import setup, profile


def first_save(tmp_path):
    mouse, prepared = setup(tmp_path)
    first = tx.apply(mouse, prepared, mouse.journal)
    return mouse, first


def second_save(mouse, tmp_path, changed=False):
    source = profile()
    if changed:
        source.common.normal['side_12'] = Action('macro', steps=(Step('down', 'KEY_F22'),
                                                  Step('wait', milliseconds=80), Step('up', 'KEY_F22')))
    prepared = tx.prepare(mouse, source)
    path = tmp_path / 'second/profile.json'
    mouse.journal = path
    return prepared, path


def test_unchanged_save_reuses_every_object_without_any_setting_command(tmp_path):
    mouse, first = first_save(tmp_path)
    prepared, path = second_save(mouse, tmp_path)
    preview = tx.validate(prepared)
    assert len(preview.assets) == 2 and not preview.uploads and preview.required_bytes == 0
    assert all(a['reused'] for a in prepared['artifacts']['assets'])
    writes = len(mouse.writes)
    tx.apply(mouse, prepared, path)
    assert len(mouse.writes) == writes and set(mouse.macros) == {1, 2}
    tx.undo(mouse, path)
    assert len(mouse.writes) == writes and set(mouse.macros) == {1, 2}
    tx.undo(mouse, tmp_path / 'profile.json')
    assert not mouse.macros


def test_changed_macro_uploads_only_new_data_and_undo_preserves_original_objects(tmp_path):
    mouse, first = first_save(tmp_path)
    old = deepcopy(mouse.macros)
    prepared, path = second_save(mouse, tmp_path, changed=True)
    preview = tx.validate(prepared)
    assert len(preview.uploads) == 1 and preview.required_bytes == 512
    assert {e['id'] for e in prepared['library_before']} == {1, 2}
    tx.apply(mouse, prepared, path)
    assert set(mouse.macros) == {1, 2, 3}
    tx.undo(mouse, path)
    assert mouse.macros == old
    assert tx.probe.normalized(tx.probe.snapshot(mouse)) == tx.probe.normalized(first['saved_state'])


@pytest.mark.parametrize('field', ['data', 'metadata'])
def test_existing_dependency_edit_between_prepare_and_apply_blocks_all_setters(tmp_path, field):
    mouse, _ = first_save(tmp_path)
    prepared, path = second_save(mouse, tmp_path, changed=True)
    mouse.macros[2][field][-1] ^= 1
    count = len(mouse.writes)
    with pytest.raises(ProtocolError, match='changed'): tx.apply(mouse, prepared, path)
    assert len(mouse.writes) == count and not path.exists()


@pytest.mark.parametrize('change', ['delete', 'data', 'metadata'])
def test_undo_checks_original_macro_dependencies_before_restoring_references(tmp_path, change):
    mouse, _ = first_save(tmp_path)
    prepared, path = second_save(mouse, tmp_path, changed=True)
    tx.apply(mouse, prepared, path)
    if change == 'delete': mouse.macros.pop(2)
    else: mouse.macros[2][change][-1] ^= 1
    count = len(mouse.writes)
    with pytest.raises(ProtocolError): tx.undo(mouse, path)
    assert len(mouse.writes) == count and 3 in mouse.macros
    assert mouse.read_binding(1, 0x4B, 0)[2:4] == b'\0\3'


def test_byte_identical_reuse_needs_no_free_storage_or_spare_slot(tmp_path):
    mouse, _ = first_save(tmp_path)
    original = mouse.execute
    def full(command):
        raw = original(command)
        return b'\0\2' + raw[2:6] + bytes(4) + raw[10:] if command.category == 6 and command.operation == 0x8E else raw
    mouse.execute = full
    prepared, path = second_save(mouse, tmp_path)
    assert not tx.validate(prepared).issues and tx.validate(prepared).required_bytes == 0
    count = len(mouse.writes)
    tx.apply(mouse, prepared, path)
    assert len(mouse.writes) == count


def test_missing_dependency_fingerprint_cannot_be_admitted(tmp_path):
    mouse, _ = first_save(tmp_path)
    prepared, path = second_save(mouse, tmp_path, changed=True)
    prepared['library_before'] = [e for e in prepared['library_before'] if e['id'] != 2]
    with pytest.raises(ProtocolError, match='Incomplete existing'): tx.apply(mouse, prepared, path)


def test_new_journal_cannot_drop_library_snapshot_or_downgrade_reuse(tmp_path):
    mouse, _ = first_save(tmp_path)
    prepared, _ = second_save(mouse, tmp_path)
    missing = deepcopy(prepared)
    missing.pop('library_before')
    with pytest.raises(ProtocolError, match='Missing version-2'): tx.validate(missing)
    prepared['version'] = 1
    with pytest.raises(ProtocolError, match='Legacy'): tx.validate(prepared)


def test_existing_version_one_receipts_remain_recoverable(tmp_path):
    mouse, prepared = setup(tmp_path)
    prepared['version'] = 1
    prepared.pop('library_before')
    tx.apply(mouse, prepared, mouse.journal)
    assert tx.undo(mouse, mouse.journal)['original_state_restored']
    assert not mouse.macros
