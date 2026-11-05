"""Read-only binding persistence checks; recovery journals are never modified."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from .compile_onboard import CONTROL_IDS
from .devices import discover
from .hardware import inventory, profile_slots, read_records
from .hid import BindingHID, CONFIG_INTERFACE, ReadOnlyHID
from .model import MODELS
from .onboard import Location, durable_json
from .protocol import Command, ProtocolError


class BindingReader(ReadOnlyHID):
    # Reuse getter codecs, without inheriting the binding setter.
    read_binding_record = BindingHID.read_binding_record
    device_serial = BindingHID.device_serial
    require_normal_mode = BindingHID.require_normal_mode

    def __init__(self, path, product):
        super().__init__(path, product)
        self.remaining = 400
        self.deadline = time.monotonic() + 120

    def execute(self, command):
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            raise ProtocolError('Persistence read budget exhausted')
        self.remaining -= 1
        return super().execute(command)


def route(device, *, sysfs=Path('/sys')):
    if device.product_id not in (0xB4, 0xE8):
        raise ProtocolError('Persistence verification currently supports the two receivers')
    usb = Path(device.usb_path).resolve(strict=True)
    if ((usb / 'idVendor').read_text().strip(), (usb / 'idProduct').read_text().strip()) != ('1532', f'{device.product_id:04x}'):
        raise ProtocolError('Receiver USB identity changed')
    address = {key: (usb / key).read_text().strip() for key in ('busnum', 'devnum')}
    if any(not value.isdecimal() or not 1 <= int(value) <= 65535 for value in address.values()):
        raise ProtocolError('Receiver enumeration identity is unavailable')
    number = CONFIG_INTERFACE[device.product_id]
    nodes = [node for node in device.interfaces if node['kind'] == 'hidraw' and node['number'] == number]
    if len(nodes) != 1:
        raise ProtocolError('Receiver configuration interface is incomplete or ambiguous')
    node = Path(nodes[0]['path'])
    if node.parent != Path('/dev') or not node.name.startswith('hidraw'):
        raise ProtocolError('Unexpected receiver configuration node')
    hid = (sysfs / 'class/hidraw' / node.name / 'device').resolve(strict=True)
    interface = next((p for p in (hid, *hid.parents) if (p / 'bInterfaceNumber').is_file()), None)
    if (not hid.is_relative_to(usb) or interface is None or not interface.is_relative_to(usb)
            or (interface / 'bInterfaceNumber').read_text().strip() != number):
        raise ProtocolError('Configuration node moved to another receiver or interface')
    return {'product': device.product_id, 'usb_path': str(usb), **address, 'node': str(node), 'hid': str(hid)}


def connected(device):
    matches = [d for d in discover() if d.product_id == device.product_id and d.usb_path == device.usb_path]
    if len(matches) != 1:
        raise ProtocolError('Reconnect this receiver to the same USB port and refresh the check')
    return matches[0]


@dataclass
class State:
    product: int
    model: str
    serial: str
    firmware: bytes
    assigned: tuple[int, ...]
    active: int
    controls: set[int]
    records: dict[Location, bytes]

    def json(self):
        return {'product': self.product, 'model': self.model, 'serial': self.serial,
                'firmware': self.firmware.hex(), 'assigned': list(self.assigned), 'active': self.active,
                'controls': sorted(self.controls),
                'records': [{**where.json(), 'raw': raw.hex()} for where, raw in sorted(self.records.items())]}


def read_state(device):
    device = connected(device)
    expected_model = MODELS[0] if device.product_id == 0xB4 else MODELS[1]
    if device.model != expected_model:
        raise ProtocolError('Receiver model does not match its product ID')
    before = route(device)
    with BindingReader(before['node'], device.product_id) as io:
        if route(connected(device)) != before:
            raise ProtocolError('Receiver changed while its configuration node was opening')
        io.require_normal_mode()
        serial = io.device_serial()
        firmware = io.execute(Command(0, 0x81, bytes(2)))
        assigned, active = profile_slots(io)
        controls = inventory(io)
        if not set(CONTROL_IDS[device.model].values()) <= controls:
            raise ProtocolError('Receiver control inventory does not match this mouse')
        records = {}
        for bank in (0, *assigned):
            records.update(read_records(io, device.model, bank))
        # The active mirror must agree with its assigned slot, independently
        # of what a successful setter ACK or stored read claimed previously.
        for where, raw in records.items():
            if where.bank == 0 and raw[3:] != records[Location(active, where.control, where.layer)][3:]:
                raise ProtocolError('Active bindings do not match the selected stored slot')
        if (io.device_serial() != serial or io.execute(Command(0, 0x81, bytes(2))) != firmware
                or profile_slots(io) != (assigned, active) or inventory(io) != controls):
            raise ProtocolError('Mouse identity, firmware or inventory changed during readback')
        io.require_normal_mode()
        if route(connected(device)) != before:
            raise ProtocolError('Receiver enumeration changed during readback')
    return State(device.product_id, device.model, serial, firmware, assigned, active, controls, records), before


def journal(path):
    with path.open('rb') as file:
        raw = file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ProtocolError('Save journal is too large')
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ProtocolError('Invalid save journal JSON') from error
    if (not isinstance(document, dict) or type(document.get('version')) is not int or document['version'] != 1
            or document.get('kind') is not None or document.get('status') != 'applied-readback-verified'):
        raise ProtocolError('Choose a completed binding save, not a backup, settings save or restored transaction')
    return document, hashlib.sha256(raw).hexdigest()


def saved_targets(document, state):
    if document.get('product') != state.product or not state.serial or document.get('serial') != state.serial:
        raise ProtocolError('Save journal belongs to another mouse')
    entries = document.get('entries')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 790:
        raise ProtocolError('Save journal has no changed bindings or has too many entries')
    targets, changed = {}, 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ProtocolError('Malformed save entry')
        fields = [entry.get(name) for name in ('bank', 'control', 'layer')]
        if any(type(value) is not int for value in fields):
            raise ProtocolError('Malformed save location')
        where = Location(*fields)
        if (where.bank not in state.assigned or where.control not in CONTROL_IDS[state.model].values()
                or where.layer not in (0, 1) or where in targets):
            raise ProtocolError('Save locations are duplicated or outside the assigned control inventory')
        values = []
        for key in ('before', 'after'):
            value = entry.get(key)
            if not isinstance(value, str) or len(value) != 14:
                raise ProtocolError('Malformed saved binding')
            try:
                values.append(bytes.fromhex(value))
            except ValueError as error:
                raise ProtocolError('Malformed saved binding') from error
            if len(values[-1]) != 7:
                raise ProtocolError('Malformed saved binding')
        before, after = values
        if state.records[where][3:] != after:
            raise ProtocolError('Current bindings differ from this save journal; choose the current save')
        targets[where] = after
        changed += before != after
    if not changed:
        raise ProtocolError('The journal contains no changed assignments to verify')
    return changed


class Verification:
    def __init__(self, device, source, directory):
        self.device, self.source, self.directory = device, source, directory
        self.path = directory / 'result.json'
        self.owned = False
        self.phase = 'new'
        self.document = {'version': 1, 'kind': 'binding-persistence-readback', 'status': 'new',
                         'source_journal': str(source), 'read_only': True,
                         'power_cycle_reported': False, 'power_cycle_readback_verified': False,
                         'receiver_disconnect_observed': False, 'receiver_replug_readback_verified': False,
                         'physical_button_behavior_verified': False}

    def record(self):
        if self.owned:
            self.document['updated_at'] = datetime.now(timezone.utc).isoformat()
            durable_json(self.path, self.document)

    def transition(self, phase):
        self.phase = self.document['status'] = phase
        self.record()

    def check_journal(self):
        document, digest = journal(self.source)
        if digest != self.document['source_sha256']:
            raise ProtocolError('Save journal changed during verification; start a new check')
        return document

    def prepare(self):
        if self.phase != 'new':
            raise ProtocolError('This verification has already started')
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.owned = True
        self.record()
        document, digest = journal(self.source)
        self.document['source_sha256'] = digest
        state, address = read_state(self.device)
        count = saved_targets(document, state)
        self.check_journal()
        self.baseline, self.address = state, address
        self.document.update(baseline=state.json(), original_route=address, changed_assignments=count)
        self.transition('awaiting-power-cycle')

    def compare(self, name):
        document = self.check_journal()
        state, address = read_state(self.device)
        self.document[name] = {'state': state.json(), 'route': address}
        self.check_journal()
        saved_targets(document, state)
        if state != self.baseline:
            raise ProtocolError('Mouse identity, firmware, slots or binding records changed since the baseline')
        return address

    def power_cycle(self):
        if self.phase != 'awaiting-power-cycle':
            raise ProtocolError('Power-cycle confirmation is not expected now')
        self.document['power_cycle_reported'] = True
        self.record()
        address = self.compare('after_reported_power_cycle')
        if address != self.address:
            raise ProtocolError('Keep the receiver connected during the mouse power-cycle step')
        self.document['power_cycle_readback_verified'] = True
        self.transition('awaiting-disconnect')

    def observe(self, devices):
        if self.phase not in ('awaiting-disconnect', 'awaiting-reconnect'):
            return False
        matches = [d for d in devices if d.product_id == self.device.product_id and d.usb_path == self.device.usb_path]
        if len(matches) > 1:
            raise ProtocolError('Receiver route is ambiguous')
        if not matches and self.phase == 'awaiting-disconnect':
            self.document['receiver_disconnect_observed'] = True
            self.transition('awaiting-reconnect')
        if not matches or self.phase != 'awaiting-reconnect':
            return False
        nodes = [n for n in matches[0].interfaces if n['kind'] == 'hidraw'
                 and n['number'] == CONFIG_INTERFACE[self.device.product_id]]
        return len(nodes) == 1

    def reconnect(self):
        if self.phase != 'awaiting-reconnect' or not self.document['receiver_disconnect_observed']:
            raise ProtocolError('Wait for an observed receiver disconnect before checking its reconnection')
        address = self.compare('after_receiver_reconnect')
        if all(address[key] == self.address[key] for key in ('busnum', 'devnum')):
            raise ProtocolError('USB enumeration did not change; a receiver replug has not been established')
        self.document['receiver_replug_readback_verified'] = True
        self.transition('verified-readback')

    def finish(self, status, error=''):
        if status not in ('cancelled', 'timed-out', 'failed'):
            raise ValueError('Invalid verification outcome')
        self.document['error'] = error
        self.transition(status)
