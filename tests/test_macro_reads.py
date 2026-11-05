import pytest

from gillete.hid import ReadOnlyHID
from gillete.firmware_probe import FirmwareQueryHID
from gillete.macro_reads import catalog, request
from gillete.protocol import Command, DeviceStatusError, ProtocolError, checksum


def response(command, payload, status=2):
    frame = bytearray(command.encode())
    frame[0] = status
    frame[5] = len(payload)
    frame[8:8 + len(payload)] = payload
    frame[88] = checksum(frame)
    return bytes(frame)


class CatalogDevice:
    def __init__(self, ids=(2, 7)):
        self.ids = ids
        self.data = {identifier: bytes(range(130)) for identifier in ids}
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        op, data = command.operation, command.payload
        if op == 0x8E:
            result = (128).to_bytes(2, 'big') + (65536).to_bytes(4, 'big') + (32768).to_bytes(4, 'big') + bytes(4)
        elif op == 0x80:
            result = len(self.ids).to_bytes(2, 'big')
        elif op == 0x8B:
            offset, amount = int.from_bytes(data[:2], 'big'), (len(data) - 4) // 2
            result = data[:2] + b'\x12\x34' + b''.join(identifier.to_bytes(2, 'big') for identifier in self.ids[offset:offset + amount])
        elif op == 0x88:
            result = data[:2] + len(self.data[int.from_bytes(data[:2], 'big')]).to_bytes(4, 'big')
        elif op == 0x89:
            offset = int.from_bytes(data[2:6], 'big')
            result = data[:7] + self.data[int.from_bytes(data[:2], 'big')][offset:offset + data[6]]
        else:
            raise AssertionError('Unexpected command')
        return command.decode(response(command, result))


def test_catalog_uses_dynamic_page_and_chunk_sizes_and_only_enumerated_ids():
    io = CatalogDevice()
    result = catalog(io, include_data=True)
    assert result['ids'] == [2, 7] and not result['zero_reference_resolved']
    assert all(bytes.fromhex(macro['raw']) == bytes(range(130)) for macro in result['macros'])
    assert [(c.operation, len(c.payload)) for c in io.commands] == [
        (0x8E, 14), (0x80, 2), (0x8B, 8), (0x88, 6), (0x89, 79), (0x89, 65),
        (0x88, 6), (0x89, 79), (0x89, 65)]
    assert result['pages'][0]['size_field'] == '1234'  # Preserved, not guessed.
    io = CatalogDevice(tuple(range(1, 34)))
    assert len(catalog(io)['ids']) == 33
    pages = [c for c in io.commands if c.operation == 0x8B]
    assert [(int.from_bytes(c.payload[:2], 'big'), len(c.payload)) for c in pages] == [(0, 68), (32, 6)]


@pytest.mark.parametrize('ids', [(0,), (2, 2), (256,), tuple(range(1, 130))])
def test_invalid_catalog_never_dereferences_zero_duplicates_or_unbounded_counts(ids):
    io = CatalogDevice(ids)
    with pytest.raises(ProtocolError):
        catalog(io, include_data=True)
    assert not any(c.operation in (0x88, 0x89) for c in io.commands)


def test_empty_catalog_and_oversized_macros_are_not_treated_as_recovered_actions():
    io = CatalogDevice(())
    result = catalog(io, include_data=True)
    assert not result['macros'] and not result['zero_reference_resolved']
    assert [c.operation for c in io.commands] == [0x8E, 0x80]
    io = CatalogDevice()
    io.data[2] = bytes(4097)
    result = catalog(io, include_data=True)
    assert result['macros'][0]['status'] == 'outside-diagnostic-limit'
    assert not any(c.operation == 0x89 and c.payload[:2] == b'\0\2' for c in io.commands)


def test_wrong_macro_id_offset_length_and_status_replies_are_rejected():
    command = request(0x89, b'\0\7' + bytes(4) + b'\x02' + bytes(2))
    correct = command.payload[:7] + b'ab'
    assert command.decode(response(command, correct)) == correct
    for bad in (b'\0\2' + correct[2:], correct[:5] + b'\x01' + correct[6:]):
        assert not command.matches(response(command, bad))
        with pytest.raises(ProtocolError):
            command.decode(response(command, bad))
    with pytest.raises(ProtocolError, match='size'):
        command.decode(response(command, correct[:-1]))
    with pytest.raises(DeviceStatusError):
        command.decode(response(command, command.payload, status=5))


def test_candidate_transport_rejects_setters_and_malformed_reads_without_enabling_them_globally(monkeypatch):
    regular = ReadOnlyHID('/dev/hidraw999', 0xB4)
    candidate = FirmwareQueryHID('/dev/hidraw999', 0xB4)
    calls = []
    monkeypatch.setattr(regular, '_exchange', lambda command: calls.append(command))
    monkeypatch.setattr(candidate, '_exchange', lambda command: calls.append(command))
    with pytest.raises(ProtocolError, match='read-only'):
        regular.execute(request(0x8E, bytes(14)))
    for command in (Command(6, 3, bytes(2)), Command(6, 8, bytes(6)), Command(6, 9, bytes(80)),
                    Command(0, 4, b'\3\0'), Command(4, 5, bytes(7)), Command(2, 0x0C, bytes(10)),
                    Command(6, 0x8E, b'\1' + bytes(13)), Command(6, 0x88, bytes(6)),
                    Command(6, 0x89, b'\0\7' + b'\xff' * 4 + b'\x01\0')):
        with pytest.raises(ProtocolError):
            candidate.execute(command)
    assert not calls
    candidate.execute(request(0x80, bytes(2)))
    assert len(calls) == 1


def test_raw_transport_waits_for_matching_macro_chunk_without_resending_query(monkeypatch):
    import gillete.hid as hid
    command = request(0x89, b'\0\7' + bytes(4) + b'\x02' + bytes(2))
    correct = command.payload[:7] + b'ab'
    stale = correct[:5] + b'\x01' + correct[6:]
    incoming = [response(command, stale), response(command, correct)]
    sent = []
    def ioctl(fd, operation, buffer, mutate):
        assert fd == 999 and mutate
        if operation == hid.feature_ioctl(6):
            sent.append(bytes(buffer))
        else:
            assert operation == hid.feature_ioctl(7)
            buffer[:] = b'\0' + incoming.pop(0)
        return 91
    monkeypatch.setattr(hid.fcntl, 'ioctl', ioctl)
    monkeypatch.setattr(hid.time, 'sleep', lambda _: None)
    candidate = FirmwareQueryHID('/dev/hidraw999', 0xB4)
    candidate.fd = 999  # No actual descriptor is opened; ioctl is the controlled fixture.
    assert candidate.execute(command) == correct
    assert sent == [b'\0' + command.encode()] and not incoming


def test_total_data_limit_and_wrong_returned_chunk_length_stop_followup_reads():
    io = CatalogDevice((2, 7, 11))
    io.data = {identifier: bytes(4096) for identifier in io.ids}
    result = catalog(io, include_data=True)
    assert sum(len(bytes.fromhex(macro.get('raw', ''))) for macro in result['macros']) == 8192
    assert result['macros'][-1]['status'] == 'outside-diagnostic-limit'
    assert not any(c.operation == 0x89 and c.payload[:2] == b'\0\x0b' for c in io.commands)
    class WrongChunk(CatalogDevice):
        def execute(self, command):
            raw = super().execute(command)
            return raw[:6] + b'\1' + raw[7:] if command.operation == 0x89 else raw
    io = WrongChunk()
    with pytest.raises(ProtocolError, match='length mismatch'):
        catalog(io, include_data=True)
    assert sum(c.operation == 0x89 for c in io.commands) == 1
