import pytest

from gillete.protocol import Binding, Command, DeviceStatusError, ProtocolError, V2_CONTROLS, checksum, v2_decode_inventory


def reply(command, payload=None, status=2):
    b = bytearray(command.encode())
    b[0] = status
    if payload is not None:
        b[5] = len(payload)
        b[8:8+len(payload)] = payload
    b[88] = checksum(b)
    return bytes(b)


def test_known_binding_request_bytes():
    binding = Binding(1, 0x40, 1, bytes.fromhex("0c010100000000"))
    request = binding.write_command().encode()
    assert len(request) == 90
    assert request[:18] == bytes.fromhex("001f0000000a020c0140010c010100000000")
    assert request[88] == 0x48
    assert request[89] == 0


def test_response_layer_byte_is_not_used_as_request_layer():
    command = Binding(1, 0x40, 0, bytes(7)).read_command()
    payload = bytes.fromhex("01400102020004000000")
    decoded = Binding.response(command.decode(reply(command, payload)), bank=1, control=0x40, layer=0)
    assert decoded.layer == 0
    assert decoded.write_command().payload[2] == 0
    assert decoded.function == payload[3:]


def test_reject_corrupt_stale_truncated_and_error_replies():
    command = Binding(1, 0x40, 0, bytes(7)).read_command()
    frame = reply(command)
    with pytest.raises(ProtocolError):
        command.decode(frame[:-1])
    corrupt = bytearray(frame)
    corrupt[10] ^= 1
    with pytest.raises(ProtocolError):
        command.decode(bytes(corrupt))
    stale = reply(Binding(1, 0x41, 0, bytes(7)).read_command())
    assert not command.matches(stale)
    with pytest.raises(ProtocolError):
        command.decode(stale)
    with pytest.raises(DeviceStatusError) as error:
        command.decode(reply(command, status=4))
    assert error.value.status == 4


def test_inventory_includes_scroll_directions_and_rejects_unknown_layout():
    ids = bytes(V2_CONTROLS.values())
    assert len(v2_decode_inventory(bytes([21]) + ids)) == 21
    assert {9, 10} <= set(ids)
    with pytest.raises(ProtocolError):
        v2_decode_inventory(bytes([21]) + ids[:-1] + bytes([ids[0]]))
    with pytest.raises(ProtocolError):
        Binding(0, 0x40, 0, bytes(7)).write_command()


def test_profile_queries_with_zero_declared_size_are_command_specific():
    for operation, payload in ((0x80, b'\x01'), (0x81, b'\x05\x01\0\0\0\0'), (0x84, b'\x01')):
        command = Command(5, operation, b'')
        frame = bytearray(reply(command, payload))
        frame[5] = 0
        frame[88] = checksum(frame)
        assert command.decode(bytes(frame)) == payload
    command = Command(5, 0x81, b'')
    assert command.decode(reply(command, b'\x01\x01')) == b'\x01\x01'
    assert command.decode(reply(command, b'\x05\x01')) == b'\x05\x01'
    with pytest.raises(ProtocolError):
        command.decode(reply(command, b'\x01\x01\x00'))
    with pytest.raises(ProtocolError):
        Command(0, 0x85, b'\0').decode(reply(Command(0, 0x85, b'')))
