"""Opt-in wired mode/input experiment; ordinary wired activation stays gated."""

import argparse
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import signal

from . import driver_capture
from . import wired_probe as wired
from .devices import discover
from .driver_mode import ModeLease
from .hardware import read_journal
from .wired_transport import ModeCaptureHID, read_state
from .model import MODELS
from .onboard import durable_json
from .protocol import ProtocolError
from .service import socket_path


def validate_inspection(document):
    try:
        route = document['read_only_route']
        candidates = [r for r in document['routes'] if r['interface'] == route]
        if (type(document.get('version')) is not int or document['version'] != 1
                or document['kind'] != 'v3-wired-read-only-probe' or document['product'] != wired.PRODUCT
                or document['status'] != 'read-only-state-verified' or document['read_only'] is not True
                or document['writes_enabled'] is not False or document['software_activation_enabled'] is not False
                or route not in ('00', '03') or len(candidates) != 1
                or set(document['descriptors']) != set(wired.LAYOUTS)):
            raise ValueError('A successful wired getter inspection is required')
        result = candidates[0]
        if (result['status'] != 'read-only-state-verified' or result['state_unchanged'] is not True
                or result['before'] != result['after'] or result['before']['mode'] != '0000'):
            raise ValueError('The inspection did not verify unchanged normal mode')
        for number, entry in document['descriptors'].items():
            if (wired.report_sizes(bytes.fromhex(entry['raw'])) != wired.LAYOUTS[number]
                    or entry['matches_reference_sizes'] is not True):
                raise ValueError('Unrecognized wired descriptor layout')
        return result['before']
    except (KeyError, TypeError, ValueError) as error:
        raise ProtocolError('Invalid wired capture proposal: ' + str(error)) from error


def selected(inspection, *, recovery=False):
    validate_inspection(inspection)
    devices = [d for d in discover() if d.product_id == wired.PRODUCT]
    if len(devices) != 1 or (not recovery and devices[0].usb_path != inspection['usb_path']):
        raise ProtocolError('The inspected wired transport is missing or changed')
    device = devices[0]
    current = wired.descriptors(device)
    if recovery:
        if (set(current) != set(inspection['descriptors'])
                or any(current[n]['raw'] != inspection['descriptors'][n]['raw'] for n in current)):
            raise ProtocolError('Wired descriptors differ; recovery requires inspection')
    elif current != inspection['descriptors']:
        raise ProtocolError('Wired USB enumeration, descriptor or driver identity changed; inspect again')
    return device


@contextmanager
def capture_transport(device, inspection, root, *, open_hid=ModeCaptureHID):
    expected = validate_inspection(inspection)
    path = inspection['descriptors'][inspection['read_only_route']]['node']
    verification = {'version': 1, 'kind': 'wired-capture-verification',
                    'normal_mode_verified': False, 'stored_state_unchanged': False}
    with open_hid(path, root / 'mode.json', expected['serial']) as io:
        before = read_state(io)
        if before != expected:
            raise ProtocolError('Wired state changed since inspection; no mode change was admitted')
        durable_json(root / 'verification.json', verification)
        try:
            yield io
        finally:
            try:
                after = read_state(io)
                verification.update(normal_mode_verified=True, stored_state_unchanged=after == before,
                                    before=before, after=after, transport_health=dict(io.reply_health))
                if after != before:
                    raise ProtocolError('Wired saved state changed during capture; current state retained')
            except (OSError, ValueError) as error:
                verification['error'] = str(error)
                raise
            finally:
                durable_json(root / 'verification.json', verification)


def prepare(report, directory):
    inspection = read_journal(report)
    validate_inspection(inspection)
    selected(inspection)  # Cached metadata only; no HID open or mode command.
    directory.mkdir(parents=True, mode=0o700)
    document = {'version': 1, 'kind': 'wired-mode-capture-proposal',
                'inspection': deepcopy(inspection), 'seconds': 180,
                'writes': ['temporary driver mode03/00', 'restore normal mode00/00'],
                'stored_binding_writes': False, 'setting_writes': False}
    durable_json(directory / 'prepared.json', document)
    return document


def run(directory, *, recover=False):
    if socket_path().exists():
        raise ProtocolError('Stop Gillete software control before the isolated wired test')
    proposal = read_journal(directory / 'prepared.json')
    if (type(proposal.get('version')) is not int or proposal['version'] != 1
            or proposal.get('kind') != 'wired-mode-capture-proposal'
            or proposal.get('seconds') != 180 or proposal.get('stored_binding_writes') is not False
            or proposal.get('setting_writes') is not False):
        raise ProtocolError('Invalid wired capture proposal')
    inspection = proposal['inspection']
    expected = validate_inspection(inspection)
    device = selected(inspection, recovery=recover)
    root = directory / 'run'
    if recover:
        path = wired.descriptors(device)[inspection['read_only_route']]['node']
        with ModeCaptureHID(path, root / 'mode.json', expected['serial']) as io:
            if io.execute(wired.BOOTSTRAP['firmware']).hex() != expected['firmware']:
                raise ProtocolError('Firmware changed; no recovery mode command was sent')
            ModeLease(io, root / 'mode.json').restore()
            current = read_state(io)
            durable_json(root / 'recovery.json', {'version': 1, 'normal_mode_verified': True,
                         'stored_state_unchanged': current == expected, 'current': current})
            if current != expected:
                raise ProtocolError('Normal mode restored; other current state differs and was left intact')
        return
    root.mkdir(mode=0o700)
    def stopped():
        path = root / 'user-report.json'
        if not path.exists(): return False
        report = read_journal(path)
        if (report != {'version': 1, 'sequence_completed': True}
                or type(report.get('version')) is not int or report.get('sequence_completed') is not True):
            raise ProtocolError('Expected confirmation for this capture only')
        return True
    driver_capture.capture(device, root / 'mode.json', root / 'capture.json', 180,
        open_transport=lambda d: capture_transport(d, inspection, root), stopped=stopped, max_records=4096)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run', 'recover'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--inspection', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'prepare':
            if not args.inspection: parser.error('--inspection is required to prepare')
            prepare(args.inspection, args.directory)
            print('PREPARED: wired mode capture; no mode or setting changed.')
        else:
            def interrupted(*_):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
            run(args.directory, recover=args.operation == 'recover')
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
