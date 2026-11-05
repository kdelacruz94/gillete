import pytest

from gillete import hardware
from gillete.compile_onboard import CONTROL_IDS
from gillete.devices import Device
from gillete.model import Action, Layers, MODELS, Profile
from gillete.onboard import Location
from gillete.protocol import ProtocolError


class Mouse:
    product = 0xB4

    def __init__(self):
        self.values = {Location(1, control, layer): bytes.fromhex('0202001e000000')
                       for control in CONTROL_IDS[MODELS[0]].values() for layer in (0, 1)}
        self.flags = {control: 1 for control in CONTROL_IDS[MODELS[0]].values()}
        self.serial = 'test-mouse'
        self.writes = []

    def __enter__(self): return self
    def __exit__(self, *_): pass
    def require_normal_mode(self): pass
    def device_serial(self): return self.serial

    def execute(self, command):
        pair = command.category, command.operation
        if pair == (5, 0x80): return b'\x01'
        if pair == (5, 0x81): return b'\x01\x01'
        if pair == (2, 0x84): return bytes([21, *CONTROL_IDS[MODELS[0]].values()])
        if pair == (0, 0x85): return b'\x01'
        if pair == (0, 0x81): return b'\1\2'
        if pair == (7, 0x80): return b'\0\x80'
        if pair == (4, 0x85): return bytes.fromhex('01032003200000')
        if pair == (4, 0x86): return bytes.fromhex('01010101032003200000') + bytes(28)
        raise AssertionError('Unexpected device command')

    def read_binding_record(self, bank, control, layer):
        return bytes((bank, control, self.flags[control])) + self.read_binding(bank, control, layer)

    def read_binding(self, bank, control, layer):
        return self.values[Location(bank, control, layer)]

    def write_binding(self, bank, control, layer, function):
        self.values[Location(bank, control, layer)] = function
        self.flags[control] = layer
        self.writes.append((bank, control, layer, function))


def setup(monkeypatch):
    mouse = Mouse()
    monkeypatch.setattr(hardware, 'transport', lambda _: mouse)
    device = Device(MODELS[0], 'Test Naga', '2.4 GHz', mouse.product, '/test', '')
    profile = Profile('p', 'P', Layers(normal={'side_12': Action('keys', keys=('KEY_F24',))}))
    return mouse, device, profile


def test_inspection_preview_save_and_restore_keep_originals(monkeypatch, tmp_path):
    mouse, device, profile = setup(monkeypatch)
    original = dict(mouse.values)
    snapshot = hardware.inspect(device)
    assert snapshot.assigned == (1,) and snapshot.active == 1
    assert snapshot.plan(profile).writable
    assert not mouse.writes
    journal = tmp_path / 'save.json'
    hardware.apply(device, snapshot, profile, journal)
    assert mouse.values[Location(1, 0x4b, 0)] == bytes.fromhex('02020073000000')
    hardware.restore(device, journal)
    assert mouse.values == original and set(mouse.flags.values()) == {1}


def test_stale_preview_and_wrong_mouse_prevent_all_writes(monkeypatch, tmp_path):
    mouse, device, profile = setup(monkeypatch)
    snapshot = hardware.inspect(device)
    mouse.values[Location(1, 0x40, 1)] = bytes(7)
    with pytest.raises(ProtocolError, match='changed after inspection'):
        hardware.apply(device, snapshot, profile, tmp_path / 'save.json')
    assert not mouse.writes and not (tmp_path / 'save.json').exists()
    mouse.serial = 'another-mouse'
    with pytest.raises(ProtocolError, match='differs from the preview'):
        hardware.apply(device, snapshot, profile, tmp_path / 'save.json')
    assert not mouse.writes


def test_software_actions_and_unassigned_banks_block_saving(monkeypatch, tmp_path):
    mouse, device, profile = setup(monkeypatch)
    snapshot = hardware.inspect(device)
    profile.common.normal['side_12'] = Action('turbo', keys=('KEY_1',), playback='toggle')
    with pytest.raises(ProtocolError, match='save is blocked'):
        hardware.apply(device, snapshot, profile, tmp_path / 'save.json')
    with pytest.raises(ProtocolError, match='Only assigned'):
        hardware.inspect(device, bank=2)
    assert not mouse.writes


def test_slot_backup_retains_unrecognized_functions_and_reply_flags(monkeypatch, tmp_path):
    mouse, device, _ = setup(monkeypatch)
    custom = bytes.fromhex('0d04004b008e00')
    where = Location(1, 0x34, 0)
    mouse.values[where] = custom
    snapshot = hardware.inspect(device)
    path = tmp_path / 'backup.json'
    hardware.backup(snapshot, path)
    assert not mouse.writes
    mouse.values[where] = bytes(7)
    hardware.restore(device, path)
    assert mouse.values[where] == custom and mouse.flags[0x34] == 1


def test_standalone_alternative_saves_and_restores_without_replacing_linux_actions(monkeypatch, tmp_path):
    from copy import deepcopy
    from gillete.model import sequence
    mouse, device, profile = setup(monkeypatch)
    profile.common.normal['side_12'] = sequence(('KEY_LEFTCTRL', 'KEY_K'), ('KEY_M',))
    profile.standalone[MODELS[0]] = Layers(normal={'side_12': Action('keys', keys=('KEY_F24',))})
    opaque = Location(1, 0x34, 1)
    mouse.values[opaque] = bytes.fromhex('05020000000000')
    original, linux = dict(mouse.values), deepcopy(profile.json())
    snapshot = hardware.inspect(device)
    journal = tmp_path / 'standalone.json'
    hardware.apply(device, snapshot, profile, journal)
    assert mouse.values[Location(1, 0x4b, 0)] == mouse.values[Location(1, 0x4b, 1)] == bytes.fromhex('02020073000000')
    assert mouse.values[opaque] == original[opaque]
    assert profile.json() == linux and profile.resolve(MODELS[0], 'side_12').kind == 'macro'
    hardware.restore(device, journal)
    assert mouse.values == original and set(mouse.flags.values()) == {1}
