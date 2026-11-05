"""Candidate read-only macro protocol, not yet established for these Nagas.

Wire shapes follow the pinned OpenSynapse protocol-25 source documented in
docs/remaining-protocol-research.md; first-party Synapse source establishes
the 15-bit ID range and inert event inspection. This module has no allocation/write/delete
commands and never converts captured bytes to executable mappings.
"""

from .protocol import Command, ProtocolError
from .macro_inspection import MAX_BYTES as MAX_MACRO_BYTES, inspect


MAX_IDS = 128
MAX_ID = 0x7FFF  # First-party createMacroId uses random u16 & 32767; zero stays unresolved.
MAX_TOTAL_BYTES = 8192
CHUNK_SIZE = 72


class MacroRead(Command):
    def matches(self, report):
        if not super().matches(report):
            return False
        echo = {0x8B: 2, 0x88: 2, 0x89: 6}.get(self.operation, 0)
        return report[0] != 2 or report[8:8 + echo] == self.payload[:echo]


def request(operation, payload):
    command = MacroRead(6, operation, payload)
    validate_request(command)
    return command


def validate_request(command):
    data, op = command.payload, command.operation
    valid = False
    if command.category == 6 and command.transaction == 0x1F:
        if op in (0x8E, 0x80):
            valid = data == bytes(14 if op == 0x8E else 2)
        elif op == 0x8B:
            valid = (6 <= len(data) <= 68 and len(data) % 2 == 0
                     and int.from_bytes(data[:2], 'big') < MAX_IDS and not any(data[2:]))
        elif op == 0x88:
            valid = len(data) == 6 and 1 <= int.from_bytes(data[:2], 'big') <= MAX_ID and not any(data[2:])
        elif op == 0x89:
            valid = (8 <= len(data) <= 79 and 1 <= int.from_bytes(data[:2], 'big') <= MAX_ID
                     and 1 <= data[6] <= CHUNK_SIZE and len(data) == 7 + data[6]
                     and int.from_bytes(data[2:6], 'big') + data[6] <= MAX_MACRO_BYTES
                     and not any(data[7:]))
    if not valid:
        raise ProtocolError('Only bounded candidate macro read requests are permitted')


def require_length(raw, size):
    if len(raw) != size:
        raise ProtocolError('Unexpected macro response length')


def catalog(io, *, include_data=False):
    info = io.execute(request(0x8E, bytes(14)))
    require_length(info, 14)
    slots = int.from_bytes(info[:2], 'big')
    maximum, available, recyclable = (int.from_bytes(info[i:i + 4], 'big') for i in (2, 6, 10))
    if maximum > 64 * 1024 * 1024 or available > maximum or recyclable > maximum:
        raise ProtocolError('Implausible macro storage counters')
    raw_count = io.execute(request(0x80, bytes(2)))
    require_length(raw_count, 2)
    count = int.from_bytes(raw_count, 'big')
    if count > min(slots, MAX_IDS):
        raise ProtocolError('Macro count exceeds reported capacity or the diagnostic limit')
    ids, pages = [], []
    while len(ids) < count:
        offset, amount = len(ids), min(32, count - len(ids))
        raw = io.execute(request(0x8B, offset.to_bytes(2, 'big') + bytes(2 + 2 * amount)))
        require_length(raw, 4 + 2 * amount)
        if int.from_bytes(raw[:2], 'big') != offset:
            raise ProtocolError('Macro ID page offset mismatch')
        page = [int.from_bytes(raw[i:i + 2], 'big') for i in range(4, len(raw), 2)]
        if any(not 1 <= identifier <= MAX_ID for identifier in page) or len(set(ids + page)) != len(ids) + len(page):
            raise ProtocolError('Zero, unsupported or duplicate macro ID; no memory read attempted for that page')
        pages.append({'offset': offset, 'size_field': raw[2:4].hex(), 'ids': page})
        ids.extend(page)
    result = {'status': 'catalog-read', 'slots': slots, 'maximum_bytes': maximum,
              'available_bytes': available, 'recyclable_bytes': recyclable,
              'count': count, 'ids': ids, 'pages': pages, 'macros': [],
              'zero_reference_resolved': False, 'firmware_playback_verified': False}
    if not include_data:
        return result
    total = 0
    for identifier in ids:
        prefix = identifier.to_bytes(2, 'big')
        size_reply = io.execute(request(0x88, prefix + bytes(4)))
        require_length(size_reply, 6)
        if size_reply[:2] != prefix:
            raise ProtocolError('Macro size reply belongs to another ID')
        size = int.from_bytes(size_reply[2:], 'big')
        if size < 1 or size > min(maximum, MAX_MACRO_BYTES) or total + size > MAX_TOTAL_BYTES:
            result['macros'].append({'id': identifier, 'size': size, 'status': 'outside-diagnostic-limit'})
            continue
        memory = bytearray()
        while len(memory) < size:
            offset, amount = len(memory), min(CHUNK_SIZE, size - len(memory))
            header = prefix + offset.to_bytes(4, 'big') + bytes((amount,))
            raw = io.execute(request(0x89, header + bytes(amount)))
            require_length(raw, 7 + amount)
            if raw[:7] != header:
                raise ProtocolError('Macro memory ID, offset or length mismatch')
            memory.extend(raw[7:])
        total += size
        result['macros'].append({'id': identifier, 'size': size, 'status': 'raw-bytes-read',
                                'raw': memory.hex(), 'interpretation': inspect(bytes(memory))})
    return result
