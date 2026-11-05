import json

import pytest

from gillete.onboard import Location, Programmer
from gillete.protocol import ProtocolError


class Mouse:
    product = 0xB4
    def __init__(self):
        self.values = {Location(1, b, l): bytes((2, 2, 0, b, 0, 0, 0)) for b in (0x40, 0x41) for l in (0, 1)}
        self.writes = []
        self.fail_after_write = None
        self.disconnected = False
        self.serial = "unique-test-mouse"

    def device_serial(self):
        if self.disconnected:
            raise OSError("Disconnected")
        return self.serial

    def require_normal_mode(self):
        pass

    def read_binding(self, bank, button, layer):
        if self.disconnected:
            raise OSError("Disconnected")
        return self.values[Location(bank, button, layer)]

    def write_binding(self, bank, button, layer, value):
        if self.disconnected:
            raise OSError("Disconnected")
        where = Location(bank, button, layer)
        self.values[where] = value
        self.writes.append((where, value))
        if len(self.writes) == self.fail_after_write:
            raise TimeoutError("SET reached device but acknowledgment was lost")


def make(tmp_path):
    mouse = Mouse()
    programmer = Programmer(mouse, tmp_path / "journal.json", mouse.serial, {0x40, 0x41})
    return mouse, programmer


def test_shifted_change_journals_normal_companion_and_restores_in_correct_order(tmp_path):
    mouse, p = make(tmp_path)
    original = dict(mouse.values)
    shifted = Location(1, 0x40, 1)
    result = p.apply({shifted: bytes.fromhex("02020004000000")})
    assert result["status"] == "applied-readback-verified"
    assert result["power_cycle_verified"] is False
    assert [w.layer for w, _ in mouse.writes] == [1, 0]
    assert p.path.stat().st_mode & 0o777 == 0o600
    mouse.writes.clear()
    p.restore()
    assert mouse.values == original
    assert [w.layer for w, _ in mouse.writes] == [1, 0]


def test_acknowledgment_timeout_rolls_back_even_the_uncertain_write(tmp_path):
    mouse, p = make(tmp_path)
    original = dict(mouse.values)
    mouse.fail_after_write = 1
    with pytest.raises(TimeoutError):
        p.apply({Location(1, 0x40, 1): bytes(7)})
    assert mouse.values == original
    assert json.loads(p.path.read_text())["status"] == "rolled-back-readback-verified"


def test_identity_and_existing_journal_prevent_writes(tmp_path):
    mouse, p = make(tmp_path)
    mouse.serial = "different-mouse"
    with pytest.raises(ProtocolError):
        p.apply({Location(1, 0x40, 0): bytes(7)})
    assert mouse.writes == []
    mouse.serial = p.serial
    p.apply({Location(1, 0x40, 0): bytes(7)})
    count = len(mouse.writes)
    with pytest.raises(ProtocolError):
        p.apply({Location(1, 0x41, 0): bytes(7)})
    assert len(mouse.writes) == count


def test_journal_is_durable_before_first_write(tmp_path):
    mouse, p = make(tmp_path)
    write = mouse.write_binding
    def checked(*args):
        saved = json.loads(p.path.read_text())
        assert saved["status"] == "prepared"
        assert saved["entries"][0]["before"] == mouse.values[Location(1, 0x40, 0)].hex()
        write(*args)
    mouse.write_binding = checked
    p.apply({Location(1, 0x40, 0): bytes(7)})


def test_disconnect_retains_recoverable_journal(tmp_path):
    mouse, p = make(tmp_path)
    original = dict(mouse.values)
    write = mouse.write_binding
    def disconnect(*args):
        write(*args)
        mouse.disconnected = True
    mouse.write_binding = disconnect
    with pytest.raises(ProtocolError, match="restore is required"):
        p.apply({Location(1, 0x40, 0): bytes(7)})
    assert json.loads(p.path.read_text())["status"] == "restore-required"
    mouse.disconnected = False
    mouse.write_binding = write
    p.restore()
    assert mouse.values == original


def test_unknown_button_rejected_without_usb_writes(tmp_path):
    mouse, p = make(tmp_path)
    with pytest.raises(ProtocolError):
        p.apply({Location(1, 0xFF, 0): bytes(7)})
    assert mouse.writes == [] and not p.path.exists()


def test_original_reply_flag_one_is_preserved_on_restore(tmp_path):
    mouse, p = make(tmp_path)
    flags = {0x40: 1, 0x41: 1}
    write = mouse.write_binding
    def write_with_flags(bank, control, layer, function):
        write(bank, control, layer, function)
        flags[control] = layer
    def record(bank, control, layer):
        return bytes((bank, control, flags[control])) + mouse.read_binding(bank, control, layer)
    mouse.write_binding = write_with_flags
    mouse.read_binding_record = record
    original = dict(mouse.values)
    p.apply({Location(1, 0x40, 0): bytes(7)})
    assert flags[0x40] == 0
    p.restore()
    assert mouse.values == original and flags == {0x40: 1, 0x41: 1}
    entries = json.loads(p.path.read_text())["entries"]
    assert {e["layer"] for e in entries} == {0, 1}


def test_journal_update_failure_still_rolls_back_hardware(tmp_path, monkeypatch):
    import gillete.onboard as onboard
    mouse, p = make(tmp_path)
    original = dict(mouse.values)
    real_write = onboard.durable_json
    writes = 0
    def disk_full_after_prepare(path, data):
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError("Disk full")
        real_write(path, data)
    monkeypatch.setattr(onboard, "durable_json", disk_full_after_prepare)
    with pytest.raises(OSError, match="Disk full"):
        p.apply({Location(1, 0x40, 0): bytes(7)})
    assert mouse.values == original
    assert json.loads(p.path.read_text())["status"] == "prepared"
