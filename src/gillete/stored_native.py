"""Read checked keyboard sequences and counted-key bodies for software playback.

This does not infer sequences from a reference or enable firmware setters.
V2, missing objects, counted multi-key/held/toggled actions and opaque streams
remain unresolved. Ordinary hardware transport keeps its existing allowlist.
"""

import time
from copy import copy
from dataclasses import replace

from .compile_onboard import CONTROL_IDS, USAGES
from .macro_inspection import inspect
from . import macro_memory as memory
from .macro_reads import MAX_TOTAL_BYTES, MacroRead, catalog, validate_request
from .model import Action, MODELS, Step
from .onboard import Location
from .protocol import ProtocolError


def eligible(snapshot):
    return (snapshot.product == 0xE8 and snapshot.model == MODELS[1]
            and snapshot.metadata.get('firmware') == '0101')


def reference(function):
    if (len(function) != 7 or function[:2] != b'\3\3'
            or not 1 <= function[4] <= 255 or function[5:] != bytes(2)):
        return None
    identifier = int.from_bytes(function[2:4], 'big')
    return identifier if 1 <= identifier <= 32767 else None


def decode_once(data):
    """A balanced known keyboard sequence with bounded delays, played once."""
    try:
        parsed = inspect(data)
        if (parsed['status'] != 'decoded' or parsed['warnings']
                or parsed['held_at_boundary'] != {'keys': [], 'mouse_buttons': []}):
            return None
        steps = []
        names = {usage: key for key, usage in USAGES.items()}
        for record in parsed['records']:
            if record['kind'] == 'delay':
                steps.append(Step('wait', milliseconds=record['milliseconds']))
            elif record['kind'] == 'key' and record['hid_usage'] in names:
                steps.append(Step('down' if record['pressed'] else 'up', names[record['hid_usage']]))
            else:
                return None
        if not any(s.kind == 'down' for s in steps):
            return None
        return Action('macro', steps=tuple(steps))
    except (TypeError, ValueError):
        return None


class Reads:
    """A bounded getter-only adapter, separate from normal transport execute."""
    def __init__(self, io):
        self.io = io
        self.remaining = 384
        self.deadline = time.monotonic() + 40

    def checkpoint(self):
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            raise ProtocolError('Stored macro read/time limit reached')
        self.remaining -= 1

    def execute(self, command):
        validate_request(command)
        if not isinstance(command, MacroRead):
            raise ProtocolError('Stored macro queries require reply identity validation')
        self.checkpoint()
        return self.io._exchange(command)


def read(io, snapshot):
    """Capture supported bodies twice and recheck their referencing bindings.

    No object is dereferenced until it appears in the bounded catalog. A
    caller must discard the entire result on communication or consistency
    failure. Independent getters establish body identity, not NVM technology.
    """
    if not eligible(snapshot):
        return {}
    if io.product != snapshot.product:
        raise ProtocolError('Stored macro inspection belongs to another transport')
    wanted = {where: identifier for where, raw in snapshot.records.items()
              if (identifier := reference(raw[3:])) is not None}
    if not wanted:
        return {}
    reads = Reads(io)
    inventory = catalog(reads)
    bodies, total = {}, 0
    for identifier in sorted(set(wanted.values()) & set(inventory['ids'])):
        size = memory.data_size(reads, identifier)
        if total + size > MAX_TOTAL_BYTES:
            raise ProtocolError('Stored macro bodies exceed the total read limit')
        data = memory.read_data(reads, identifier, size)
        total += size
        if decode_once(data) is not None:
            bodies[identifier] = data.hex()
    for identifier, encoded in bodies.items():
        size = memory.data_size(reads, identifier)
        if size != len(bytes.fromhex(encoded)) or memory.read_data(reads, identifier, size).hex() != encoded:
            raise ProtocolError('Stored native macro changed during inspection')
    for where, identifier in wanted.items():
        if identifier in bodies:
            reads.checkpoint()
            if io.read_binding_record(where.bank, where.control, where.layer) != snapshot.records[where]:
                raise ProtocolError('Stored native macro assignment changed during inspection')
    return bodies


def required_ids(snapshot, profiles):
    """Only Keep stored actions reachable in the selected activation mode."""
    result = set()
    for profile in profiles:
        for control, code in CONTROL_IDS[snapshot.model].items():
            for shifted in (False, True):
                if profile.resolve(snapshot.model, control, shifted).kind == 'passthrough':
                    identifier = reference(snapshot.baseline[Location(snapshot.bank, code, int(shifted))])
                    if identifier in snapshot.native_macros:
                        result.add(identifier)
    return result


def verify(io, snapshot, required=None):
    if required is not None:
        selected = copy(snapshot)
        selected.native_macros = {i: raw for i, raw in snapshot.native_macros.items() if i in required}
        selected.records = {where: raw for where, raw in snapshot.records.items() if reference(raw[3:]) in required}
        snapshot = selected
    if snapshot.native_macros:
        io.require_normal_mode()
        if read(io, snapshot) != snapshot.native_macros:
            raise ProtocolError('Stored native macros changed after inspection; read the mouse again')


def load_bodies(values):
    """Validate the optional private snapshot extension, including JSON keys."""
    try:
        if not isinstance(values, dict) or len(values) > 50:
            raise ValueError('Invalid stored native body collection')
        result, total = {}, 0
        for identifier, encoded in values.items():
            if (not isinstance(identifier, str) or str(int(identifier)) != identifier
                    or not 1 <= int(identifier) <= 32767 or not isinstance(encoded, str)
                    or len(encoded) > 8192):
                raise ValueError('Invalid stored native body')
            raw = bytes.fromhex(encoded)
            total += len(raw)
            if not raw or len(raw) > 4096 or total > MAX_TOTAL_BYTES:
                raise ValueError('Stored native body size exceeds the bounded limit')
            result[int(identifier)] = raw.hex()
        return result
    except (ValueError, TypeError, AttributeError) as error:
        raise ProtocolError('Invalid stored native macro snapshot: ' + str(error)) from error


def action(snapshot, function):
    if not eligible(snapshot) or (identifier := reference(function)) is None:
        return None
    try:
        result = decode_once(bytes.fromhex(snapshot.native_macros[identifier]))
        if result is None or function[4] == 1:
            return result
        if sum(s.kind == 'down' for s in result.steps) != 1:
            return None
        # The object already contains its per-iteration trailing delay, including
        # the final iteration. Do not add the host runner's default gap again.
        return replace(result, playback='count', count=function[4], interval_ms=0)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
