from copy import deepcopy
from types import SimpleNamespace

import pytest

from gillete import native_profile_review as review
from gillete.hardware import Snapshot
from gillete.model import MODELS
from gillete.onboard import Location
from gillete.protocol import ProtocolError
from test_native_profile_probe import prepared_mouse


def inputs():
    mouse, prepared = prepared_mouse()
    before = prepared['before']
    snapshot = Snapshot(0xE8, MODELS[1], before['serial'], 1, (1,), 1, set(before['controls']),
        {Location(e['bank'], e['control'], e['layer']): bytes.fromhex(e['raw']) for e in before['records'] if e['bank'] == 1},
        before['settings'], {'firmware': before['firmware']})
    device = SimpleNamespace(product_id=0xE8, model=MODELS[1])
    return mouse, prepared, snapshot, device


def test_desktop_review_reads_exact_transport_without_mutating_profile_snapshot_or_mouse(tmp_path, monkeypatch):
    mouse, prepared, snapshot, device = inputs()
    profile = review.tx.Profile.parse(prepared['profile'])
    previous = deepcopy(profile.json())
    monkeypatch.setattr(review, 'socket_path', lambda: tmp_path / 'not-running')
    monkeypatch.setattr(review.hardware, 'transport', lambda selected: SimpleNamespace(path='verified-path', product=0xE8))
    def opened(path, product):
        assert path == 'verified-path' and product == 0xE8
        return mouse
    monkeypatch.setattr(review, 'MacroHID', opened)
    result = review.prepare_review(device, snapshot, profile)
    assert len(result['artifacts']['assets']) == 2 and not mouse.writes
    assert profile.json() == previous


@pytest.mark.parametrize('change', ['identity', 'firmware', 'settings', 'records'])
def test_stale_inspection_blocks_native_review(tmp_path, monkeypatch, change):
    mouse, prepared, snapshot, device = inputs()
    monkeypatch.setattr(review, 'socket_path', lambda: tmp_path / 'not-running')
    monkeypatch.setattr(review.hardware, 'transport', lambda _: SimpleNamespace(path='verified', product=0xE8))
    monkeypatch.setattr(review, 'MacroHID', lambda *_: mouse)
    if change == 'identity': snapshot.serial = 'other'
    elif change == 'firmware': snapshot.metadata['firmware'] = 'ffff'
    elif change == 'settings': snapshot.settings = {}
    else: snapshot.records = {}
    with pytest.raises(ProtocolError, match='changed since'):
        review.prepare_review(device, snapshot, review.tx.Profile.parse(prepared['profile']))
    assert not mouse.writes


def test_unverified_route_or_running_service_cannot_open_hardware(tmp_path, monkeypatch):
    mouse, prepared, snapshot, device = inputs()
    snapshot.product = 0xE7
    assert not review.eligible(snapshot)
    with pytest.raises(ProtocolError): review.prepare_review(device, snapshot, review.tx.Profile.parse(prepared['profile']))
    snapshot.product = 0xE8
    def active(*args, **kwargs): raise ProtocolError('Disable software control for this mouse')
    monkeypatch.setattr(review, 'require_idle', active)
    monkeypatch.setattr(review, '_transport', lambda _: (_ for _ in ()).throw(AssertionError('Transport opened')))
    with pytest.raises(ProtocolError, match='Disable'): review.prepare_review(device, snapshot, review.tx.Profile.parse(prepared['profile']))
    assert not mouse.reads or not mouse.writes


@pytest.mark.parametrize('operation', ['prepare', 'save', 'restore'])
def test_selected_service_ownership_is_checked_before_all_desktop_native_operations(tmp_path, monkeypatch, operation):
    from gillete import memory_access
    from gillete.profiles import ProfileStore
    from gillete.service import Daemon
    from test_native_profile_support import fixture
    mouse, prepared, device = fixture()
    _, _, snapshot, _ = inputs()
    snapshot.metadata['firmware'] = prepared['before']['firmware']
    daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
    daemon.requested.add(MODELS[0])  # Other mouse stays enabled throughout.
    replies = []
    async def status(command, **kwargs):
        replies.append(command)
        return daemon.status()
    monkeypatch.setattr(memory_access, 'request', status)
    monkeypatch.setattr(review, '_transport', lambda _: mouse)
    path = tmp_path / 'native/profile.json'
    if operation == 'restore': review.tx.apply(mouse, prepared, path)
    daemon.requested.add(MODELS[1])
    writes = len(mouse.writes)
    opened = []
    def transport(selected):
        opened.append(selected)
        return mouse
    monkeypatch.setattr(review, '_transport', transport)
    def execute():
        if operation == 'prepare': return review.prepare_review(device, snapshot, review.tx.Profile.parse(prepared['profile']))
        if operation == 'save': return review.save_review(device, prepared, path)
        return review.restore_review(device, path)
    with pytest.raises(ProtocolError, match='Disable software control'): execute()
    assert not opened and len(mouse.writes) == writes and replies == ['status']
    daemon.requested.discard(MODELS[1])
    result = execute()
    assert result and len(opened) == 1 and replies == ['status', 'status']
    assert MODELS[0] in daemon.requested
