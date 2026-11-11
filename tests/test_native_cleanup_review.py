from types import SimpleNamespace

import pytest

from gillete import native_profile_review as review
from gillete.hardware import Snapshot
from gillete.model import MODELS
from gillete.onboard import Location
from gillete.protocol import ProtocolError
from test_native_cleanup import library


def inputs(tmp_path, monkeypatch):
    mouse, prepared = library(tmp_path)
    before = prepared['before']
    snapshot = Snapshot(0xE8, MODELS[1], before['serial'], 1, (1,), 1, set(before['controls']),
        {Location(e['bank'], e['control'], e['layer']): bytes.fromhex(e['raw'])
         for e in before['records'] if e['bank'] == 1}, before['settings'], {'firmware': '0101'})
    device = SimpleNamespace(model=MODELS[1], product_id=0xE8)
    monkeypatch.setattr(review.hardware, 'journal_directory', lambda: tmp_path)
    monkeypatch.setattr(review, '_transport', lambda selected: mouse)
    return mouse, prepared, snapshot, device


def test_desktop_storage_read_and_delete_use_the_selected_idle_model_and_exact_backend(tmp_path, monkeypatch):
    mouse, prepared, snapshot, device = inputs(tmp_path, monkeypatch)
    checks = []
    monkeypatch.setattr(review, 'require_idle', lambda model, **kwargs: checks.append(model))
    before = len(mouse.writes)
    result = review.prepare_library(device, snapshot)
    assert result['rows'] == prepared['rows'] and len(mouse.writes) == before
    result = review.cleanup_review(device, result, [2], mouse.journal, acknowledge_undo=True)
    assert result['unchanged_state_verified'] and result['deleted_ids'] == [2]
    assert checks == [MODELS[1], MODELS[1]]


@pytest.mark.parametrize('operation', ['read', 'delete'])
def test_busy_selected_model_blocks_storage_hardware_access(tmp_path, monkeypatch, operation):
    mouse, prepared, snapshot, device = inputs(tmp_path, monkeypatch)
    def active(*args, **kwargs): raise ProtocolError('Disable software control for this mouse')
    monkeypatch.setattr(review, 'require_idle', active)
    monkeypatch.setattr(review, '_transport', lambda *_: (_ for _ in ()).throw(AssertionError('Opened hardware')))
    before = len(mouse.writes)
    with pytest.raises(ProtocolError, match='Disable'):
        if operation == 'read': review.prepare_library(device, snapshot)
        else: review.cleanup_review(device, prepared, [2], mouse.journal, acknowledge_undo=True)
    assert len(mouse.writes) == before


def test_stale_loaded_state_cannot_be_used_for_storage_selection(tmp_path, monkeypatch):
    mouse, _, snapshot, device = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(review, 'require_idle', lambda *args, **kwargs: None)
    snapshot.serial = 'another-unit'
    before = len(mouse.writes)
    with pytest.raises(ProtocolError, match='changed since'): review.prepare_library(device, snapshot)
    assert len(mouse.writes) == before
