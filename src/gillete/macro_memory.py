"""Bounded first-party macro memory packets; callers own journaling/identity."""

from .macro_reads import MAX_ID, MAX_MACRO_BYTES, CHUNK_SIZE, request, require_length
from .protocol import Command, ProtocolError


METADATA_SIZE = 250
NAME_CHUNK = 64


def identifier_bytes(identifier):
    if type(identifier) is not int or not 1 <= identifier <= MAX_ID:
        raise ProtocolError('Expected a nonzero first-party 15-bit macro ID')
    return identifier.to_bytes(2, 'big')


def allocate(identifier, size):
    if type(size) is not int or not 1 <= size <= MAX_MACRO_BYTES:
        raise ProtocolError('Invalid native macro event-data size')
    return Command(6, 8, identifier_bytes(identifier) + size.to_bytes(4, 'big'))


def delete(identifier):
    return Command(6, 3, identifier_bytes(identifier))


def memory_chunk(identifier, offset, data):
    if (type(offset) is not int or offset < 0 or not isinstance(data, bytes)
            or not 1 <= len(data) <= CHUNK_SIZE or offset + len(data) > MAX_MACRO_BYTES):
        raise ProtocolError('Invalid native macro event chunk')
    return Command(6, 9, identifier_bytes(identifier) + offset.to_bytes(4, 'big') + bytes((len(data),)) + data)


def name_chunk(identifier, offset, data):
    if (type(offset) is not int or offset < 0 or not isinstance(data, bytes)
            or not 1 <= len(data) <= NAME_CHUNK or offset + len(data) > METADATA_SIZE):
        raise ProtocolError('Invalid native macro name chunk')
    return Command(6, 12, identifier_bytes(identifier) + offset.to_bytes(2, 'big') + METADATA_SIZE.to_bytes(2, 'big') + data)


def data_size(io, identifier):
    prefix = identifier_bytes(identifier)
    raw = io.execute(request(0x88, prefix + bytes(4)))
    require_length(raw, 6)
    if raw[:2] != prefix:
        raise ProtocolError('Macro size belongs to another ID')
    size = int.from_bytes(raw[2:], 'big')
    if not 1 <= size <= MAX_MACRO_BYTES:
        raise ProtocolError('Macro event-data size is outside the bounded limit')
    return size


def read_data(io, identifier, size):
    allocate(identifier, size)  # Pure validation only; no allocation is sent.
    data = bytearray()
    while len(data) < size:
        offset, amount = len(data), min(CHUNK_SIZE, size - len(data))
        header = identifier_bytes(identifier) + offset.to_bytes(4, 'big') + bytes((amount,))
        raw = io.execute(request(0x89, header + bytes(amount)))
        require_length(raw, len(header) + amount)
        if raw[:7] != header:
            raise ProtocolError('Macro memory response ID/offset/length mismatch')
        data.extend(raw[7:])
    return bytes(data)


def read_name(io, identifier):
    data = bytearray()
    while len(data) < METADATA_SIZE:
        offset, amount = len(data), min(NAME_CHUNK, METADATA_SIZE - len(data))
        prefix = identifier_bytes(identifier) + offset.to_bytes(2, 'big')
        raw = io.execute(request(0x8C, prefix + bytes(2 + amount)))
        require_length(raw, 6 + amount)
        if raw[:4] != prefix:
            raise ProtocolError('Macro metadata response ID/offset mismatch')
        data.extend(raw[6:])  # Preserve, rather than guess, the response size field.
    return bytes(data)
