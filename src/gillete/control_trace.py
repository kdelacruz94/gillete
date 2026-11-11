"""Opt-in, bounded mouse-control evidence for isolated software acceptance.

No raw reports, pointer coordinates, keyboard input, key assignments or launch
arguments are retained. Normal service runs never construct this trace.
"""

from collections import deque
import time
from uuid import uuid4


class ControlTrace:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.epoch = uuid4().hex
        self.sequence = 0
        self.entries = deque(maxlen=512)
        self.held = frozenset()

    def record(self, engine, source, control, direction, *, activate):
        self.sequence += 1
        self.entries.append({'seq': self.sequence, 't': self.clock(), 'source': source,
            'control': control, 'direction': direction, 'shifted': engine.shifted,
            'activate': bool(activate), 'blocked': control in engine.disarmed,
            'profile': engine.profile.id, 'generation': engine.generation})

    def document(self, engine):
        return {'version': 1, 'epoch': self.epoch, 'sequence': self.sequence,
                'entries': list(self.entries), 'held': sorted(self.held),
                't': self.clock(), 'generation': engine.generation,
                'profile': engine.profile.id, 'shifted': engine.shifted}
