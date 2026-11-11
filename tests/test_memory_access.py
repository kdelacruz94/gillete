import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from gillete import memory_access as access
from gillete.model import MODELS
from gillete.protocol import ProtocolError
from gillete.profiles import ProfileStore
from gillete.service import Daemon


def status(tmp_path):
    return Daemon(ProfileStore(tmp_path / 'profiles.json')).status()


@pytest.mark.parametrize('model', MODELS)
def test_idle_daemon_or_other_enabled_model_does_not_block_selected_mouse(tmp_path, model):
    daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
    other = next(m for m in MODELS if m != model)
    daemon.requested.add(other)
    daemon.startup_pending.add(other)
    daemon.sessions[other] = SimpleNamespace(ready=True, engine=None,
        device=SimpleNamespace(product_id=0xB4 if other == MODELS[0] else 0xE8,
                               usb_path='/other-mouse', transport='2.4 GHz'))
    before = deepcopy(daemon.status())
    access.verify_status(before, model)
    assert before == daemon.status() and other in daemon.requested


@pytest.mark.parametrize('phase', ['requested', 'active', 'starting', 'stopping', 'pending-startup'])
def test_all_selected_ownership_phases_block_before_opening_hardware(tmp_path, phase):
    value = status(tmp_path)
    state = value['devices'][MODELS[1]]
    if phase in ('requested', 'active'): state[phase] = True
    elif phase in ('starting', 'stopping'):
        state['transport'] = {'product': 0xE8, 'usb_path': '/selected-mouse', 'transport': '2.4 GHz'}
    else: value['startup_pending'] = [MODELS[1]]
    with pytest.raises(ProtocolError, match='Disable software control'): access.verify_status(value, MODELS[1])


@pytest.mark.parametrize('change', ['missing-model', 'old-status', 'missing-request', 'nonbool-active',
                                  'missing-startup', 'invalid-startup', 'wrong-transport', 'stopped'])
def test_incomplete_or_old_reports_do_not_prove_release(tmp_path, change):
    value = status(tmp_path)
    if change == 'missing-model': value['devices'].pop(MODELS[1])
    elif change == 'old-status': value['devices'][MODELS[1]].pop('transport')
    elif change == 'missing-request': value['devices'][MODELS[1]].pop('requested')
    elif change == 'nonbool-active': value['devices'][MODELS[1]]['active'] = 0
    elif change == 'missing-startup': value.pop('startup_pending')
    elif change == 'invalid-startup': value['startup_pending'] = ['unknown-mouse']
    elif change == 'wrong-transport': value['devices'][MODELS[1]]['transport'] = 'none'
    else: value['running'] = False
    with pytest.raises(ProtocolError, match='Cannot verify'): access.verify_status(value, MODELS[1])


@pytest.mark.parametrize('error', [FileNotFoundError(), ConnectionRefusedError()])
def test_absent_or_stale_listener_does_not_start_or_unlink_anything(tmp_path, monkeypatch, error):
    path = tmp_path / 'control.sock'
    path.write_text('stale placeholder')
    calls = []
    async def missing(command, **kwargs):
        calls.append((command, kwargs))
        raise error
    monkeypatch.setattr(access, 'request', missing)
    access.require_idle(MODELS[1], path=path)
    assert calls == [('status', {'path': path})] and path.read_text() == 'stale placeholder'


@pytest.mark.parametrize('error', [PermissionError('no access'), TimeoutError('status timed out'),
                                 RuntimeError('service unavailable'), ValueError('bad JSON')])
def test_status_failures_do_not_authorize_hardware_work(monkeypatch, error):
    async def failed(*args, **kwargs): raise error
    monkeypatch.setattr(access, 'request', failed)
    with pytest.raises(ProtocolError, match='Cannot verify'): access.require_idle(MODELS[1])


def test_real_private_socket_receives_status_only_and_preserves_configuration_identity(tmp_path):
    async def check():
        path = tmp_path / 'control.sock'
        value = status(tmp_path)
        value['config_path'] = '/another/private/profiles.json'
        received = []
        async def client(reader, writer):
            received.append(json.loads(await reader.readline()))
            writer.write((json.dumps({'ok': True, 'result': value}) + '\n').encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_unix_server(client, str(path))
        try:
            await access.check(MODELS[1], path=path)
            assert received == [{'command': 'status'}] and path.exists()
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(check())


def test_unknown_model_is_rejected_before_any_service_query(monkeypatch):
    async def forbidden(*args, **kwargs): raise AssertionError('Unexpected service query')
    monkeypatch.setattr(access, 'request', forbidden)
    with pytest.raises(ProtocolError, match='Unknown mouse'): access.require_idle('unknown')
