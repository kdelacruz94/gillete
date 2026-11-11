"""Read-only service ownership preflight for explicit mouse-memory work.

An idle daemon or another enabled model is compatible. Starting, active,
stopping and pending startup sessions for the selected model are not. This
does not disable anything; transport exclusivity and device guards still
decide whether a subsequent hardware operation can proceed.
"""

import asyncio

from .model import MODELS
from .protocol import ProtocolError
from .service import request


def verify_status(status, model):
    try:
        if model not in MODELS or not isinstance(status, dict) or status.get('running') is not True:
            raise ValueError('Unknown service status')
        startup = status['startup_pending']
        state = status['devices'][model]
        if (not isinstance(startup, list) or any(item not in MODELS for item in startup)
                or not isinstance(state, dict) or type(state.get('requested')) is not bool
                or type(state.get('active')) is not bool or 'transport' not in state
                or state['transport'] is not None and not isinstance(state['transport'], dict)):
            raise ValueError('Service does not report complete ownership state')
    except (KeyError, TypeError, ValueError) as error:
        raise ProtocolError('Cannot verify mouse input ownership; stop the background service or refresh its status') from error
    if model in startup or state['requested'] or state['active'] or state['transport'] is not None:
        raise ProtocolError('Disable software control for this mouse and wait until its session is released before mouse-memory operations')


async def check(model, *, path=None):
    if model not in MODELS:
        raise ProtocolError('Unknown mouse model for memory operation')
    try:
        # No configuration identity is supplied: ownership is relevant even
        # when an already running daemon uses a different profile file.
        status = await asyncio.wait_for(request('status', path=path), 5)
    except (FileNotFoundError, ConnectionRefusedError):
        return  # No live listener; no socket is removed and nothing is started.
    except (OSError, ValueError, RuntimeError, asyncio.TimeoutError) as error:
        raise ProtocolError('Cannot verify mouse input ownership; stop the background service or retry: ' + str(error)) from error
    verify_status(status, model)


def require_idle(model, *, path=None):
    """Synchronous worker entry; use check directly from an async caller."""
    asyncio.run(check(model, path=path))
