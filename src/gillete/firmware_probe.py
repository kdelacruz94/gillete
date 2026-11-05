"""Opt-in bounded firmware reads. No setters, input grabs or remapping.

Keep candidate commands out of the ordinary application transport allowlist.
Reports retain private raw replies and classify rejection separately from
unsupported claims. A successful query does not establish firmware playback
or nonpersistent DPI writes.
"""

import argparse
import json
import os
from pathlib import Path
import time

from .devices import discover
from .hardware import inventory, profile_slots, read_records
from .hid import CONFIG_INTERFACE, ReadOnlyHID
from .macro_reads import catalog, validate_request
from .onboard import durable_json
from .protocol import Command, DeviceStatusError, ProtocolError
from .settings import SPECS, query, validate_pair


class FirmwareQueryHID(ReadOnlyHID):
    def execute(self, command):
        if command.category == 6:
            validate_request(command)
            return self._exchange(command)
        return super().execute(command)


class Probe:
    def __init__(self, io, document, *, max_requests=512, seconds=40):
        self.io, self.product, self.document = io, io.product, document
        self.max_requests, self.reserve = max_requests, 0
        self.deadline = time.monotonic() + seconds
        self.phase = 'before'

    def execute(self, command):
        if len(self.document['queries']) >= self.max_requests - self.reserve or time.monotonic() >= self.deadline:
            raise ProtocolError('Read-only diagnostic request/time limit reached')
        entry = {'phase': self.phase, 'category': command.category, 'operation': command.operation,
                 'request': command.payload.hex()}
        self.document['queries'].append(entry)
        try:
            response = self.io.execute(command)
            entry['response'] = response.hex()
            return response
        except (OSError, ProtocolError) as error:
            entry['error'] = str(error)
            if isinstance(error, DeviceStatusError):
                entry['device_status'] = error.status
            raise

    def read_binding_record(self, bank, control, layer):
        return self.execute(Command(2, 0x8C, bytes((bank, control, layer)) + bytes(7)))

    def state(self, model):
        mode = self.execute(Command(0, 0x84, bytes(2)))
        if mode != bytes(2):
            raise ProtocolError('Read-only diagnostic requires normal mode; no mode change was made')
        serial = self.execute(Command(0, 0x82, bytes(22))).split(b'\0', 1)[0]
        if not serial or set(serial) == {48} or any(not 32 <= value < 127 for value in serial):
            raise ProtocolError('Device did not supply a unique hardware identity')
        assigned, active = profile_slots(self)
        controls = inventory(self)
        records = {}
        for bank in (0, active):
            records.update(read_records(self, model, bank))
        settings = {name: self.execute(query(name)).hex() for name in SPECS}
        return {'serial': serial.decode('ascii'), 'mode': mode.hex(), 'assigned': list(assigned),
                'active': active, 'controls': sorted(controls), 'settings': settings,
                'records': [{**where.json(), 'raw': raw.hex()} for where, raw in sorted(records.items())]}


def dpi_selectors(io):
    values = {}
    for selector in (1, 0):
        raw = io.execute(Command(4, 0x85, bytes((selector,)) + bytes(6)))
        if len(raw) != 7 or raw[0] != selector:
            raise ProtocolError('DPI response did not echo the requested storage selector')
        pair = validate_pair((int.from_bytes(raw[1:3], 'big'), int.from_bytes(raw[3:5], 'big')), io.product)
        values[str(selector)] = {'raw': raw.hex(), 'dpi': list(pair)}
    return {'status': 'selectors-read', 'selectors': values, 'temporary_writes_verified': False,
            'note': 'Readable selectors do not prove separate storage or nonpersistent writes.'}


def collect(io, model, document, sections, *, include_data=False):
    probe = Probe(io, document)
    try:
        document['before'] = probe.state(model)
    except (OSError, ProtocolError) as error:
        document.update(status='preflight-failed', error=str(error))
        return
    probe.reserve = len(document['queries'])
    for section in sections:
        probe.phase = section
        try:
            document['sections'][section] = (catalog(probe, include_data=include_data)
                                              if section == 'macros' else dpi_selectors(probe))
        except (OSError, ProtocolError) as error:
            outcome = {'status': 'stopped', 'error': str(error)}
            if isinstance(error, DeviceStatusError):
                outcome['device_status'] = error.status
            document['sections'][section] = outcome
    probe.reserve = 0
    probe.phase = 'after'
    try:
        document['after'] = probe.state(model)
        document['state_unchanged'] = document['after'] == document['before']
        document['status'] = 'read-complete' if document['state_unchanged'] else 'state-difference-observed'
    except (OSError, ProtocolError) as error:
        document.update(status='verification-unavailable', verification_error=str(error))


def run(product, output, sections, *, include_data=False):
    if not sections or len(set(sections)) != len(sections) or set(sections) - {'macros', 'dpi'}:
        raise ProtocolError('Choose macros and/or dpi once each')
    matches = [device for device in discover() if device.product_id == product]
    if product not in CONFIG_INTERFACE or len(matches) != 1:
        raise ProtocolError('Connect exactly one verified receiver transport for the requested product')
    device = matches[0]
    nodes = [node for node in device.interfaces if node['kind'] == 'hidraw' and node['number'] == CONFIG_INTERFACE[product]]
    if len(nodes) != 1:
        raise ProtocolError('Configuration interface is missing or ambiguous')
    document = {'version': 1, 'kind': 'firmware-read-only-probe', 'product': product, 'model': device.model,
                'transport': device.transport, 'read_only': True, 'status': 'prepared',
                'sections': {}, 'queries': [], 'state_unchanged': None,
                'limits': {'requests': 512, 'seconds': 40, 'macro_bytes': 8192},
                'candidate_protocol': 'OpenSynapse eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e; unverified Naga portability'}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reserve a fresh report; never overwrite a prior hardware observation.
    with output.open('x') as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(document, handle)
    try:
        with FirmwareQueryHID(nodes[0]['path'], product) as io:
            collect(io, device.model, document, sections, include_data=include_data)
    except (OSError, ProtocolError) as error:
        document.update(status='transport-failed', error=str(error))
    finally:
        durable_json(output, document)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', required=True, type=lambda value: int(value, 16), choices=(0xB4, 0xE8))
    parser.add_argument('--output', required=True, type=Path, help='New private JSON report path')
    parser.add_argument('--sections', nargs='+', choices=('macros', 'dpi'), default=['macros', 'dpi'])
    parser.add_argument('--include-macro-data', action='store_true', help='Capture bounded raw data for enumerated nonzero IDs')
    args = parser.parse_args(argv)
    try:
        document = run(args.product, args.output, args.sections, include_data=args.include_macro_data)
    except (OSError, ProtocolError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Read-only diagnostic: {document["status"]}. Private report: {args.output}')
    for name, section in document['sections'].items():
        detail = section.get('error', f'{section.get("count", "")} catalog entries' if name == 'macros' else 'selectors queried')
        print(f'{name}: {section["status"]} — {detail}')
    if document.get('error'):
        print(document['error'])
    if document['state_unchanged']:
        print('Normal mode, device identity, bindings and saved settings matched before/after.')
    return 0 if document['status'] == 'read-complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
