import pytest

from gillete import hid
from gillete.protocol import Command, DeviceStatusError, ProtocolError, checksum
from test_macro_reads import response


def harness(monkeypatch, command, reports):
    clock, sent, reads = [0.], [], []
    pending = list(reports)
    def ioctl(fd, operation, buffer, mutate):
        assert fd == 999 and mutate
        if operation == hid.feature_ioctl(6): sent.append(bytes(buffer))
        else:
            assert operation == hid.feature_ioctl(7)
            frame = pending.pop(0) if len(pending) > 1 else pending[0]
            reads.append(frame)
            buffer[:] = b'\0' + frame
        return 91
    monkeypatch.setattr(hid.fcntl, 'ioctl', ioctl)
    monkeypatch.setattr(hid.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(hid.time, 'monotonic', lambda: clock[0])
    io = hid.BindingHID('/dev/hidraw999', 0xE8)
    io.fd = 999
    return io, sent, reads


@pytest.mark.parametrize('command', [Command(0, 0x84, bytes(2)), Command(6, 8, bytes.fromhex('000100000006'))])
def test_corrupt_reply_then_valid_never_resubmits_even_a_setting_command(monkeypatch, command):
    good = response(command, command.payload)
    corrupt = bytearray(good)
    corrupt[88] ^= 1
    io, sent, reads = harness(monkeypatch, command, [bytes(corrupt), good])
    assert io._exchange(command) == command.payload
    assert sent == [b'\0' + command.encode()] and len(reads) == 2
    assert io.last_reply['completed'] and io.reply_health['malformed_reports'] == 1


def test_persistent_corruption_fails_after_three_gets_without_resubmitting(monkeypatch):
    command = Command(0, 0x84, bytes(2))
    corrupt = bytearray(response(command, bytes(2)))
    corrupt[88] ^= 1
    io, sent, reads = harness(monkeypatch, command, [bytes(corrupt)])
    with pytest.raises(ProtocolError, match='malformed-report limit'): io.execute(command)
    assert len(sent) == 1 and len(reads) == 3
    assert not io.last_reply['completed'] and io.reply_health['exchanges_with_malformed_reports'] == 1


def test_valid_rejection_wrong_payload_and_short_ioctl_are_not_retried(monkeypatch):
    command = Command(0, 0x84, bytes(2))
    io, sent, reads = harness(monkeypatch, command, [response(command, bytes(2), status=5)])
    with pytest.raises(DeviceStatusError): io.execute(command)
    assert len(sent) == len(reads) == 1
    io, sent, reads = harness(monkeypatch, command, [response(command, b'\0')])
    with pytest.raises(ProtocolError, match='payload size'): io.execute(command)
    assert len(sent) == len(reads) == 1
    original = hid.fcntl.ioctl
    monkeypatch.setattr(hid.fcntl, 'ioctl', lambda fd, op, buffer, mutate:
                        90 if op == hid.feature_ioctl(7) else original(fd, op, buffer, mutate))
    with pytest.raises(ProtocolError, match='Expected 91 bytes'): io.execute(command)


def test_malformed_then_stale_and_busy_still_require_matching_valid_completion(monkeypatch):
    command = Command(0, 0x84, bytes(2))
    corrupt = bytearray(response(command, bytes(2)))
    corrupt[3] = 1
    corrupt[88] = checksum(corrupt)  # Even checksum-valid reserved fields stay rejected.
    stale = response(Command(7, 0x80, bytes(2)), bytes(2))
    busy = response(command, bytes(2), status=1)
    good = response(command, bytes(2))
    io, sent, reads = harness(monkeypatch, command, [bytes(corrupt), stale, busy, good])
    assert io.execute(command) == bytes(2) and len(sent) == 1 and len(reads) == 4


def test_corruption_followed_by_only_stale_replies_keeps_protocol_failure_classification(monkeypatch):
    command = Command(0, 0x84, bytes(2))
    corrupt = bytearray(response(command, bytes(2)))
    corrupt[88] ^= 1
    stale = response(Command(7, 0x80, bytes(2)), bytes(2))
    io, sent, reads = harness(monkeypatch, command, [bytes(corrupt), stale])
    with pytest.raises(ProtocolError, match='after malformed reports'): io.execute(command)
    assert len(sent) == 1 and len(reads) <= 33
