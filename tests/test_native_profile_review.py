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
    running = tmp_path / 'service.sock'
    running.touch()
    monkeypatch.setattr(review, 'socket_path', lambda: running)
    with pytest.raises(ProtocolError, match='Disable'): review.prepare_review(device, snapshot, review.tx.Profile.parse(prepared['profile']))
    assert not mouse.reads or not mouse.writes
