import json

import pytest

from gillete.driver_mode import ModeLease
from gillete.protocol import ProtocolError


class ModeDevice:
    product = 0xE8

    def __init__(self):
        self.current = b'\0\0'
        self.serial = 'test-mouse'
        self.fail_ack = False
        self.writes = []

    def device_serial(self): return self.serial
    def execute(self, command):
        assert (command.category, command.operation) == (0, 0x84)
        return self.current

    def _exchange(self, command):
        assert (command.category, command.operation) == (0, 4)
        self.current = command.payload
        self.writes.append(command.payload)
        if self.fail_ack:
            self.fail_ack = False
            raise TimeoutError('Lost acknowledgment')


def test_temporary_mode_restores_after_interruption(tmp_path):
    io = ModeDevice()
    path = tmp_path / 'mode.json'
    with pytest.raises(KeyboardInterrupt):
        with ModeLease(io, path):
            assert json.loads(path.read_text())['before'] == '0000'
            assert io.current == b'\x03\0'
            raise KeyboardInterrupt
    assert io.current == b'\0\0'
    assert json.loads(path.read_text())['status'] == 'normal-mode-restored'


def test_mode_ack_timeout_restores_uncertain_change(tmp_path):
    io = ModeDevice()
    io.fail_ack = True
    with pytest.raises(TimeoutError):
        ModeLease(io, tmp_path / 'mode.json').enter()
    assert io.current == b'\0\0'
    assert io.writes == [b'\x03\0', b'\0\0']


def test_do_not_take_existing_mode_or_restore_other_mouse(tmp_path):
    io = ModeDevice()
    io.current = b'\x03\0'
    path = tmp_path / 'mode.json'
    with pytest.raises(ProtocolError):
        ModeLease(io, path).enter()
    assert not io.writes and not path.exists()
    io.current = b'\0\0'
    lease = ModeLease(io, path)
    lease.enter()
    io.serial = 'other-mouse'
    with pytest.raises(ProtocolError):
        ModeLease(io, path).restore()
    assert io.current == b'\x03\0' and len(io.writes) == 1
