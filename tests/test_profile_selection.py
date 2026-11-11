import asyncio
import fcntl
import json
import os

import pytest

from gillete import profile_selection as selection
from gillete.model import ConfigurationError, MODELS, Profile
from gillete.profiles import ProfileStore
from gillete.service import Daemon


def store(tmp_path):
    result = ProfileStore(tmp_path / 'profiles.json')
    config = result.read()
    config.profiles['work'] = Profile('work', 'Work')
    config.profiles['automatic'] = Profile('automatic', 'Profile named automatic')
    result.save(config, expected_revision=0)
    return result


@pytest.mark.parametrize('error', [FileNotFoundError(), ConnectionRefusedError()])
def test_confirmed_offline_pin_is_per_mouse_persistent_and_preserves_fresh_edits(tmp_path, monkeypatch, error):
    saved = store(tmp_path)
    async def absent(*args, **kwargs): raise error
    monkeypatch.setattr(selection, 'request', absent)
    config = saved.read()
    config.profiles['work'].name = 'Renamed elsewhere'
    config.pinned[MODELS[0]] = 'default'
    saved.save(config, expected_revision=config.revision)
    path = tmp_path / 'runtime/control.sock'
    result = asyncio.run(selection.select(saved, MODELS[1], 'work', path=path))
    assert result.status is None
    assert saved.read().pinned == {MODELS[0]: 'default', MODELS[1]: 'work'}
    assert saved.read().profiles['work'].name == 'Renamed elsewhere'
    assert asyncio.run(selection.select(saved, MODELS[1], None, path=path)).status is None
    assert saved.read().pinned == {MODELS[0]: 'default'} and not path.exists()


def test_offline_preference_does_not_race_a_starting_or_stopping_daemon(tmp_path, monkeypatch):
    saved = store(tmp_path)
    path = tmp_path / 'runtime/control.sock'
    path.parent.mkdir(mode=0o700)
    descriptor = os.open(path.parent / 'service.lock', os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    async def refused(*args, **kwargs): raise ConnectionRefusedError()
    monkeypatch.setattr(selection, 'request', refused)
    before = saved.path.read_bytes()
    try:
        with pytest.raises(RuntimeError, match='starting, stopping or unreachable'):
            asyncio.run(selection.select(saved, MODELS[1], 'work', path=path))
        assert saved.path.read_bytes() == before
    finally: os.close(descriptor)


@pytest.mark.parametrize('error', [TimeoutError('acknowledgement lost'), PermissionError('no access'),
    RuntimeError('different profile file'), RuntimeError('Unknown service command'), ValueError('invalid response')])
def test_unknown_service_failure_never_falls_back_to_a_local_pin(tmp_path, monkeypatch, error):
    saved = store(tmp_path)
    before = saved.path.read_bytes()
    async def failed(*args, **kwargs): raise error
    monkeypatch.setattr(selection, 'request', failed)
    with pytest.raises(type(error)):
        asyncio.run(selection.select(saved, MODELS[1], 'work', path=tmp_path / 'runtime/control.sock'))
    assert saved.path.read_bytes() == before and not (tmp_path / 'runtime').exists()


def test_live_selection_uses_server_validation_with_literal_ids_and_explicit_automatic(tmp_path):
    async def check():
        saved = store(tmp_path)
        daemon = Daemon(saved)
        path = tmp_path / 'control.sock'
        received = []
        async def client(reader, writer):
            message = json.loads(await reader.readline())
            received.append(message)
            try: result = {'ok': True, 'result': await daemon.command(message)}
            except Exception as error: result = {'ok': False, 'error': str(error)}
            writer.write((json.dumps(result) + '\n').encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_unix_server(client, str(path))
        try:
            result = await selection.select(saved, MODELS[1], 'automatic', path=path)
            assert result.status['devices'][MODELS[1]]['mode'] == 'pinned'
            assert saved.read().pinned[MODELS[1]] == 'automatic'
            await selection.select(saved, MODELS[1], None, path=path)
            assert not saved.read().pinned
            assert [m['command'] for m in received] == ['select-profile', 'select-profile']
            assert received[0]['profile'] == 'automatic' and 'profile' not in received[1]
            assert all(m['config_path'] == str(saved.path.resolve()) for m in received)
            await daemon.command({'command': 'pin', 'model': MODELS[1], 'profile': 'automatic'})
            assert not saved.read().pinned  # Legacy CLI selector remains compatible.
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(check())


def test_live_preflight_rejection_preserves_the_saved_pin(tmp_path, monkeypatch):
    async def check():
        saved = store(tmp_path)
        daemon = Daemon(saved)
        def rejected(config): raise ConfigurationError('Selected profile has unresolved stored actions')
        monkeypatch.setattr(daemon, 'validate_config', rejected)
        async def routed(command, **kwargs):
            return await daemon.command({'command': command, 'model': kwargs['model'], 'profile': kwargs['profile'],
                                         'config_path': str(kwargs['config_path'].resolve())})
        monkeypatch.setattr(selection, 'request', routed)
        before = saved.path.read_bytes()
        with pytest.raises(ConfigurationError, match='unresolved stored'):
            await selection.select(saved, MODELS[1], 'work')
        assert saved.path.read_bytes() == before
    asyncio.run(check())


def test_offline_missing_profile_or_insecure_runtime_directory_cannot_mutate_preferences(tmp_path, monkeypatch):
    saved = store(tmp_path)
    async def absent(*args, **kwargs): raise FileNotFoundError()
    monkeypatch.setattr(selection, 'request', absent)
    before = saved.path.read_bytes()
    with pytest.raises(ConfigurationError, match='no longer exists'):
        asyncio.run(selection.select(saved, MODELS[1], 'deleted', path=tmp_path / 'private/control.sock'))
    (tmp_path / 'public').mkdir(mode=0o755)
    with pytest.raises(PermissionError):
        asyncio.run(selection.select(saved, MODELS[1], 'work', path=tmp_path / 'public/control.sock'))
    assert saved.path.read_bytes() == before


@pytest.mark.parametrize('status', [None, {}, {'running': True, 'config_path': '/wrong-file', 'devices': {}}])
def test_invalid_live_acknowledgement_is_not_misreported_as_an_offline_save(tmp_path, monkeypatch, status):
    saved = store(tmp_path)
    before = saved.path.read_bytes()
    async def malformed(*args, **kwargs): return status
    monkeypatch.setattr(selection, 'request', malformed)
    with pytest.raises(RuntimeError, match='did not acknowledge'):
        asyncio.run(selection.select(saved, MODELS[1], 'work', path=tmp_path / 'runtime/control.sock'))
    assert saved.path.read_bytes() == before and not (tmp_path / 'runtime').exists()
