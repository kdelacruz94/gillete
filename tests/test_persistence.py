from copy import deepcopy
import json
from pathlib import Path

import pytest

from gillete import persistence as p
from gillete.compile_onboard import CONTROL_IDS
from gillete.devices import Device
from gillete.hid import ReadOnlyHID
from gillete.model import MODELS
from gillete.onboard import Location, durable_json
from gillete.protocol import Command, ProtocolError


class World:
    def __init__(self, model=MODELS[0]):
        self.model, self.product = model, 0xB4 if model == MODELS[0] else 0xE8
        number = '00' if self.product == 0xB4 else '03'
        self.device = Device(model, 'Test mouse', '2.4 GHz', self.product, '/test/usb', 'test',
                             [{'kind': 'hidraw', 'number': number, 'path': '/dev/hidraw9'}])
        self.devices = [self.device]
        self.address = {'product': self.product, 'usb_path': '/test/usb', 'busnum': '1', 'devnum': '2',
                        'node': '/dev/hidraw9', 'hid': '/test/usb/hid-old'}
        self.serial, self.firmware, self.mode = 'test', b'\1\2', bytes(2)
        self.assigned, self.active = (1,), 1
        self.controls = set(CONTROL_IDS[model].values())
        self.records = {Location(bank, c, layer): bytes((bank, c, 0)) + bytes.fromhex('0202001e000000')
                        for bank in (0, 1) for c in self.controls for layer in (0, 1)}
        self.changed = Location(1, 0x4b, 0)
        for bank in (0, 1):
            where = Location(bank, 0x4b, 0)
            self.records[where] = bytes((bank, 0x4b, 0)) + bytes.fromhex('02020073000000')
        self.commands, self.reads = [], []
        self.on_read = None

    def reader(self, path, product):
        assert path == self.address['node'] and product == self.product
        world = self
        class IO:
            product = world.product
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def require_normal_mode(self):
                if self.execute(Command(0, 0x84, bytes(2))) != bytes(2):
                    raise ProtocolError('normal mode required')
            def device_serial(self): return self.execute(Command(0, 0x82, bytes(22))).decode()
            def execute(self, command):
                pair = command.category, command.operation
                world.commands.append(pair)
                if pair == (0, 0x81): return world.firmware
                if pair == (0, 0x82): return world.serial.encode()
                if pair == (0, 0x84): return world.mode
                if pair == (5, 0x80): return bytes((len(world.assigned),))
                if pair == (5, 0x81): return bytes((1 if world.product == 0xB4 else 5, *world.assigned))
                if pair == (5, 0x84): return bytes((world.active,))
                if pair == (2, 0x84): return bytes((len(world.controls), *sorted(world.controls)))
                raise AssertionError('Unexpected getter or setter')
            def read_binding_record(self, bank, control, layer):
                world.reads.append(Location(bank, control, layer))
                if world.on_read:
                    world.on_read(world)
                return world.records[Location(bank, control, layer)]
        return IO()

    def journal(self):
        return {'version': 1, 'product': self.product, 'serial': self.serial,
                'status': 'applied-readback-verified', 'power_cycle_verified': False,
                'entries': [{**self.changed.json(), 'before': '0202001e000000', 'after': '02020073000000',
                             'reply_flag_before': 0}]}


def setup(tmp_path, monkeypatch, model=MODELS[0]):
    world = World(model)
    monkeypatch.setattr(p, 'discover', lambda: world.devices)
    monkeypatch.setattr(p, 'route', lambda device: deepcopy(world.address))
    monkeypatch.setattr(p, 'BindingReader', world.reader)
    source = tmp_path / 'save.json'
    durable_json(source, world.journal())
    return world, p.Verification(world.device, source, tmp_path / 'verification')


@pytest.mark.parametrize('model', MODELS)
def test_power_cycle_and_observed_replug_verify_reads_without_changing_journal(tmp_path, monkeypatch, model):
    world, check = setup(tmp_path, monkeypatch, model)
    original = check.source.read_bytes()
    records = deepcopy(world.records)
    check.prepare()
    assert check.phase == 'awaiting-power-cycle' and not check.document['power_cycle_readback_verified']
    assert check.document['changed_assignments'] == 1
    check.power_cycle()
    assert check.document['power_cycle_reported'] and check.phase == 'awaiting-disconnect'
    assert not check.observe(world.devices)
    assert not check.observe([]) and check.phase == 'awaiting-reconnect'
    world.address.update(devnum='3', node='/dev/hidraw20', hid='/test/usb/hid-new')
    assert check.observe(world.devices)
    check.reconnect()
    receipt = json.loads(check.path.read_text())
    assert receipt['status'] == 'verified-readback'
    assert receipt['power_cycle_readback_verified'] and receipt['receiver_replug_readback_verified']
    assert receipt['receiver_disconnect_observed'] and not receipt['physical_button_behavior_verified']
    assert check.source.read_bytes() == original and world.records == records
    assert check.path.stat().st_mode & 0o777 == 0o600 and check.directory.stat().st_mode & 0o777 == 0o700
    assert len(world.reads) == 3 * len(records)


def test_all_assigned_v3_slots_are_compared_even_when_journal_changes_one(tmp_path, monkeypatch):
    world, check = setup(tmp_path, monkeypatch, MODELS[1])
    world.assigned = (1, 3)
    for where, raw in list(world.records.items()):
        if where.bank == 1:
            world.records[Location(3, where.control, where.layer)] = b'\3' + raw[1:]
    check.prepare()
    where = Location(3, 0x40, 1)
    world.records[where] = world.records[where][:3] + bytes(7)
    with pytest.raises(ProtocolError, match='changed since'):
        check.power_cycle()
    assert not check.document['power_cycle_readback_verified']


@pytest.mark.parametrize('mutation,match', [
    (lambda d: d.update(status='restored-readback-verified'), 'completed binding save'),
    (lambda d: d.update(kind='device-settings'), 'completed binding save'),
    (lambda d: d.update(version=True), 'completed binding save'),
    (lambda d: d.update(serial='another mouse'), 'another mouse'),
    (lambda d: d.update(entries=[]), 'no changed'),
    (lambda d: d['entries'].append(dict(d['entries'][0])), 'duplicated'),
    (lambda d: d['entries'][0].update(bank=0), 'outside'),
    (lambda d: d['entries'][0].update(bank=2), 'outside'),
    (lambda d: d['entries'][0].update(layer=True), 'location'),
    (lambda d: d['entries'][0].update(after='ff'), 'binding'),
    (lambda d: d['entries'][0].update(after='zz' * 7), 'binding'),
    (lambda d: d['entries'][0].update(after='00000000000000'), 'Current bindings differ'),
    (lambda d: d['entries'][0].update(before=d['entries'][0]['after']), 'no changed'),
])
def test_unusable_save_journals_do_not_become_verification_baselines(tmp_path, monkeypatch, mutation, match):
    world, check = setup(tmp_path, monkeypatch)
    document = world.journal()
    mutation(document)
    durable_json(check.source, document)
    with pytest.raises(ProtocolError, match=match):
        check.prepare()
    assert check.phase == 'new' and not check.document['receiver_replug_readback_verified']


@pytest.mark.parametrize('change,match', [
    (lambda w: setattr(w, 'serial', 'another'), 'another mouse'),
    (lambda w: setattr(w, 'firmware', b'\1\3'), 'changed since'),
    (lambda w: setattr(w, 'mode', b'\3\0'), 'normal mode'),
    (lambda w: w.records.update({Location(0, 0x4b, 0): bytes((0, 0x4b, 0)) + bytes(7)}), 'Active bindings'),
    (lambda w: w.records.update({Location(1, 0x40, 0): bytes((1, 0x40, 1)) + w.records[Location(1, 0x40, 0)][3:]}), 'changed since'),
])
def test_identity_mode_active_mirror_and_metadata_changes_reject_persistence(tmp_path, monkeypatch, change, match):
    world, check = setup(tmp_path, monkeypatch)
    check.prepare()
    change(world)
    with pytest.raises(ProtocolError, match=match):
        check.power_cycle()
    assert not check.document['power_cycle_readback_verified']


def test_journal_change_during_baseline_or_later_read_cannot_be_certified(tmp_path, monkeypatch):
    world, check = setup(tmp_path, monkeypatch)
    def change(w):
        w.on_read = None
        check.source.write_bytes(check.source.read_bytes() + b' ')
    world.on_read = change
    with pytest.raises(ProtocolError, match='journal changed'):
        check.prepare()
    other = p.Verification(world.device, check.source, tmp_path / 'second')
    other.prepare()
    world.on_read = change
    with pytest.raises(ProtocolError, match='journal changed'):
        other.power_cycle()


def test_replug_requires_absence_new_enumeration_same_port_and_complete_interface(tmp_path, monkeypatch):
    world, check = setup(tmp_path, monkeypatch)
    check.prepare()
    check.power_cycle()
    with pytest.raises(ProtocolError, match='observed receiver disconnect'):
        check.reconnect()
    assert not check.observe([])
    incomplete = deepcopy(world.device)
    incomplete.interfaces.clear()
    assert not check.observe([incomplete])
    with pytest.raises(ProtocolError, match='enumeration did not change'):
        check.reconnect()
    world.address['devnum'] = '3'
    moved = deepcopy(world.device)
    moved.usb_path = '/another/port'
    world.devices = [moved]
    with pytest.raises(ProtocolError, match='same USB port'):
        check.reconnect()
    assert not check.document['receiver_replug_readback_verified']


def test_route_change_during_read_and_early_replug_are_rejected(tmp_path, monkeypatch):
    world, check = setup(tmp_path, monkeypatch)
    check.prepare()
    world.address['devnum'] = '3'
    with pytest.raises(ProtocolError, match='Keep the receiver connected'):
        check.power_cycle()
    world.address['devnum'] = '2'
    def replug(w):
        w.address['devnum'] = '3'
        w.on_read = None
    world.on_read = replug
    with pytest.raises(ProtocolError, match='enumeration changed during'):
        check.power_cycle()


def test_cancel_timeout_and_failure_receipts_leave_recovery_source_intact(tmp_path, monkeypatch):
    world, check = setup(tmp_path, monkeypatch)
    original = check.source.read_bytes()
    for status in ('cancelled', 'timed-out', 'failed'):
        attempt = p.Verification(world.device, check.source, tmp_path / status)
        attempt.prepare()
        attempt.finish(status, 'test detail')
        result = json.loads(attempt.path.read_text())
        assert result['status'] == status and not result['receiver_replug_readback_verified']
    assert check.source.read_bytes() == original
    check.directory.mkdir()
    marker = check.directory / 'result.json'
    marker.write_text('Existing receipt')
    with pytest.raises(FileExistsError):
        check.prepare()
    check.finish('failed')
    assert marker.read_text() == 'Existing receipt'


def test_binding_reader_rejects_setters_and_bounds_queries(monkeypatch):
    reader = p.BindingReader('/unused', 0xB4)
    assert not hasattr(reader, 'write_binding')
    with pytest.raises(ProtocolError, match='read-only'):
        reader.execute(Command(2, 0x0C, bytes(10)))
    monkeypatch.setattr(ReadOnlyHID, '_exchange', lambda self, command: b'\0\0')
    reader.remaining = 1
    reader.execute(Command(0, 0x84, bytes(2)))
    with pytest.raises(ProtocolError, match='budget'):
        reader.execute(Command(0, 0x84, bytes(2)))
    reader.remaining, reader.deadline = 10, 0
    with pytest.raises(ProtocolError, match='budget'):
        reader.execute(Command(0, 0x84, bytes(2)))


def test_route_resolves_configuration_node_to_exact_receiver_and_interface(tmp_path):
    usb = tmp_path / 'sys/devices/usb1/1-2'
    usb.mkdir(parents=True)
    for name, value in {'idVendor': '1532', 'idProduct': '00e8', 'busnum': '1', 'devnum': '2'}.items():
        (usb / name).write_text(value)
    interface = usb / '1-2:1.3'
    hid = interface / 'hid'
    hid.mkdir(parents=True)
    (interface / 'bInterfaceNumber').write_text('03')
    link = tmp_path / 'sys/class/hidraw/hidraw9/device'
    link.parent.mkdir(parents=True)
    link.symlink_to(hid)
    device = World(MODELS[1]).device
    device.usb_path = str(usb)
    found = p.route(device, sysfs=tmp_path / 'sys')
    assert found['hid'] == str(hid) and found['devnum'] == '2'
    (interface / 'bInterfaceNumber').write_text('00')
    with pytest.raises(ProtocolError, match='another receiver or interface'):
        p.route(device, sysfs=tmp_path / 'sys')
