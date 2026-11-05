"""Read-only Naga V3 wired descriptor and configuration-route validation.

No input capture, mode change, setting write or software activation. Candidate
routes remain local to this diagnostic; success does not modify CONFIG_INTERFACE.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

from .compile_onboard import CONTROL_IDS
from .descriptors import report_sizes
from .devices import discover
from .firmware_probe import Probe
from .hid import ReadOnlyHID
from .model import MODELS
from .onboard import durable_json
from .protocol import Command, ProtocolError
from .settings import SPECS, validate_value


PRODUCT = 0xE7
LAYOUTS = {
    '00': {'input': {'0': 8}, 'output': {}, 'feature': {}},
    '01': {'input': {str(i): 16 for i in range(1, 6)}, 'output': {}, 'feature': {}},
    '02': {'input': {'0': 8}, 'output': {'0': 1}, 'feature': {}},
    '03': {'input': {}, 'output': {}, 'feature': {'0': 90}},
}
BOOTSTRAP = {'firmware': Command(0, 0x81, bytes(4)),
             'mode': Command(0, 0x84, bytes(2)), 'polling': Command(0, 0x85, bytes(1))}


class RouteIdentityChanged(ProtocolError):
    """A topology/identity change stops the whole probe, not just one route."""


class WiredQueryHID(ReadOnlyHID):
    def __init__(self, path):
        super().__init__(path, PRODUCT)

    def __enter__(self):
        try:
            return super().__enter__()
        except ProtocolError as error:
            raise RouteIdentityChanged(str(error)) from error

    def execute(self, command):
        pair, data = (command.category, command.operation), command.payload
        allowed = {**{(c.category, c.operation): c.payload for c in BOOTSTRAP.values()},
                   (0, 0x82): bytes(22), (4, 0x85): b'\1' + bytes(6),
                   (4, 0x86): b'\1' + bytes(37),
                   **{(5, op): b'' for op in (0x80, 0x81, 0x84)}}
        valid = pair in allowed and data == allowed[pair]
        if pair == (2, 0x84):
            valid = 2 <= len(data) <= 80 and not any(data)
        if pair == (2, 0x8C):
            valid = (len(data) == 10 and data[0] <= 5 and data[1] in CONTROL_IDS[MODELS[1]].values()
                     and data[2] in (0, 1) and not any(data[3:]))
        if not valid or command.transaction != 0x1F:
            raise ProtocolError('Wired diagnostic permits only the explicit getter shapes')
        return super().execute(command)


def descriptors(device, sysfs=Path('/sys')):
    """Resolve every HID through the selected USB ancestor, not listing order."""
    if device.product_id != PRODUCT:
        raise ProtocolError('Descriptor capture requires the V3 wired product')
    usb = Path(device.usb_path).resolve(strict=True)
    if ((usb / 'idVendor').read_text().strip(), (usb / 'idProduct').read_text().strip()) != ('1532', '00e7'):
        raise ProtocolError('Wired USB identity changed during discovery')
    address = {name: (usb / name).read_text().strip() for name in ('busnum', 'devnum')}
    if any(not value.isdecimal() or int(value) < 1 for value in address.values()):
        raise ProtocolError('Missing wired USB enumeration identity')
    found = {}
    for node in device.interfaces:
        if node['kind'] != 'hidraw':
            continue
        path = Path(node['path'])
        if path.parent != Path('/dev') or not path.name.startswith('hidraw'):
            raise ProtocolError('Unexpected raw HID node path')
        hid = (sysfs / 'class/hidraw' / path.name / 'device').resolve(strict=True)
        if not hid.is_relative_to(usb):
            raise ProtocolError('HID node moved to another USB device')
        interface = next((p for p in (hid, *hid.parents) if (p / 'bInterfaceNumber').is_file()), None)
        if interface is None or not interface.is_relative_to(usb):
            raise ProtocolError('Missing wired USB interface identity')
        number = (interface / 'bInterfaceNumber').read_text().strip()
        if number != node['number'] or number not in LAYOUTS or number in found:
            raise ProtocolError('Wired HID interfaces are changed, missing or ambiguous')
        with (hid / 'report_descriptor').open('rb') as handle:
            raw = handle.read(4097)
        sizes = report_sizes(raw)
        def driver(owner):
            link = owner / 'driver'
            return link.resolve().name if link.is_symlink() else None
        found[number] = {'node': str(path), 'hid_device': str(hid), 'usb_address': address,
                         'hid_driver': driver(hid), 'usb_driver': driver(interface),
                         'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                         'raw': raw.hex(), 'reports': sizes, 'matches_reference_sizes': sizes == LAYOUTS[number]}
    if set(found) != set(LAYOUTS):
        raise ProtocolError('Expected one wired HID for each interface 00/01/02/03')
    return dict(sorted(found.items()))


class WiredProbe(Probe):
    def state(self, model):
        result = super().state(model)
        if not set(CONTROL_IDS[model].values()) <= set(result['controls']):
            raise ProtocolError('Wired control inventory does not include the 12-button layout')
        result['firmware'] = self.execute(BOOTSTRAP['firmware']).hex()
        for name in SPECS:
            validate_value(name, bytes.fromhex(result['settings'][name]), PRODUCT)
        return result


def check_route(io, attempt):
    probe = WiredProbe(io, attempt, max_requests=256, seconds=120)
    probe.phase = 'route'
    try:
        values = {}
        for name, command in BOOTSTRAP.items():
            raw = probe.execute(command)
            if len(raw) != len(command.payload):
                raise ProtocolError('Wired getter returned an unexpected payload length')
            values[name] = raw.hex()
            if name == 'mode' and raw != bytes(2):
                attempt.update(status='normal-mode-required', bootstrap=values)
                return
            if name == 'polling':
                validate_value('polling', raw, PRODUCT)
        attempt['bootstrap'] = values
    except (OSError, ProtocolError) as error:
        attempt.update(status='route-failed', error=str(error))
        return
    # Only a failed bootstrap tries the other route. Once these getters work,
    # an inventory/readback failure is its own result, not an interface sweep.
    try:
        probe.phase = 'before'
        attempt['before'] = probe.state(MODELS[1])
    except (OSError, ProtocolError) as error:
        attempt.update(status='read-preflight-failed', error=str(error))
        return
    try:
        probe.phase = 'after'
        attempt['after'] = probe.state(MODELS[1])
        attempt['state_unchanged'] = attempt['before'] == attempt['after']
        attempt['status'] = 'read-only-state-verified' if attempt['state_unchanged'] else 'state-difference-observed'
    except (OSError, ProtocolError) as error:
        attempt.update(status='verification-unavailable', error=str(error))


def query_routes(document, open_hid=None, verify=lambda: None):
    open_hid = open_hid or WiredQueryHID
    if any(not value['matches_reference_sizes'] for value in document['descriptors'].values()):
        document['status'] = 'descriptor-difference; query skipped'
        return
    for number in ('00', '03'):
        node = document['descriptors'][number]
        attempt = {'interface': number, 'node': node['node'], 'queries': [], 'state_unchanged': None,
                   'basis': 'Linux-fork index-0 candidate' if number == '00' else 'descriptor feature-report candidate'}
        document['routes'].append(attempt)
        try:
            verify()
            with open_hid(node['node']) as io:
                verify()
                if io.product != PRODUCT:
                    raise RouteIdentityChanged('Query route belongs to a different product')
                check_route(io, attempt)
                verify()
        except RouteIdentityChanged as error:
            attempt.update(status='identity-changed', error=str(error))
        except (OSError, ProtocolError) as error:
            attempt.update(status='route-failed', error=str(error))
        document['status'] = attempt['status']
        if attempt['status'] != 'route-failed':
            if attempt['status'] == 'read-only-state-verified':
                document['read_only_route'] = number
            return


def run(output, *, query=False, sysfs=Path('/sys')):
    devices = discover(sysfs)
    wired = [d for d in devices if d.product_id == PRODUCT]
    if len(wired) != 1:
        raise ProtocolError('Connect exactly one V3 Pro USB cable transport')
    # The receiver may remain attached during read-only discovery. Record it,
    # but choose the cable by PID and USB ancestor, never a shared serial.
    device = wired[0]
    document = {'version': 1, 'kind': 'v3-wired-read-only-probe', 'product': PRODUCT,
                'read_only': True, 'status': 'prepared', 'usb_path': device.usb_path,
                'receiver_present': any(d.product_id == 0xE8 for d in devices),
                'descriptors': {}, 'routes': [], 'read_only_route': None,
                'writes_enabled': False, 'software_activation_enabled': False,
                'limits_per_route': {'requests': 256, 'seconds': 120}}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with output.open('x') as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(document, handle)
    try:
        document['descriptors'] = descriptors(device, sysfs)
        document['status'] = 'descriptors-captured'
        if query:
            def verify():
                try:
                    if descriptors(device, sysfs) != document['descriptors']:
                        raise ProtocolError('Descriptor or driver association changed')
                except (OSError, ProtocolError) as error:
                    raise RouteIdentityChanged('Wired USB/HID identity changed during route inspection') from error
            query_routes(document, verify=verify)
    except (OSError, ProtocolError) as error:
        document.update(status='inspection-failed', error=str(error))
    finally:
        durable_json(output, document)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private JSON report path')
    parser.add_argument('--query-routes', action='store_true', help='Also submit bounded getters on candidate interfaces 00 then 03')
    args = parser.parse_args(argv)
    try:
        document = run(args.output, query=args.query_routes)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print('V3 wired inspection: ' + document['status'])
    for number, entry in document['descriptors'].items():
        print(f'Interface {number}: {entry["bytes"]} descriptor bytes; known report sizes: {entry["matches_reference_sizes"]}')
    for attempt in document['routes']:
        print(f'Query route {attempt["interface"]}: {attempt["status"]}' + (f' — {attempt["error"]}' if attempt.get('error') else ''))
    if document.get('error'):
        print(document['error'])
    print('Writes and software activation remain unverified and disabled for the wired transport.')
    return 0 if document['status'] in ('descriptors-captured', 'read-only-state-verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
