"""Authoritative live pin selection with an interlocked offline preference path."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os

from .model import ConfigurationError, MODELS
from .service import request, socket_path


@dataclass(frozen=True)
class Selection:
    status: dict | None


@contextmanager
def offline_lock(path):
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError('Service directory must be private to this desktop user')
    descriptor = os.open(directory / 'service.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('The service is starting, stopping or unreachable; retry profile selection after it settles') from error
        yield
    finally:
        os.close(descriptor)


async def select(store, model, identifier, *, path=None):
    if model not in MODELS or identifier is not None and (not isinstance(identifier, str) or not identifier):
        raise ConfigurationError('Choose a mouse and a profile, or Automatic')
    path = path or socket_path()
    try:
        # The explicit command keeps a profile whose actual ID is "automatic"
        # distinct from choosing Automatic. A lost reply never permits a local
        # fallback: the live mutation may already have taken effect.
        status = await asyncio.wait_for(request('select-profile', model=model,
            profile=identifier, path=path, config_path=store.path), 5)
        try:
            if (status['running'] is not True or status['config_path'] != str(store.path.resolve())
                    or status['devices'][model]['mode'] != ('automatic' if identifier is None else 'pinned')):
                raise ValueError('Unexpected selection acknowledgement')
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError('The service did not acknowledge profile selection; refresh its status before retrying') from error
        return Selection(status)
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    except RuntimeError as error:
        if str(error) == 'Unknown service command':
            raise RuntimeError('Restart the running Gillete service to update profile-selection support') from error
        raise
    # The daemon holds this lock from before listening until all device cleanup
    # finishes. Keep it through the local revision-checked save, so a concurrent
    # daemon start cannot race an unvalidated offline pin into a live session.
    with offline_lock(path):
        config = store.read()
        if identifier is None:
            config.pinned.pop(model, None)
        else:
            if identifier not in config.profiles:
                raise ConfigurationError('The selected profile no longer exists; reload profiles')
            config.pinned[model] = identifier
        store.save(config, expected_revision=config.revision)
    return Selection(None)
