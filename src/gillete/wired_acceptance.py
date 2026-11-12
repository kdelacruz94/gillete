"""Isolated wired software acceptance; ordinary wired activation stays disabled."""

import argparse
import asyncio
from copy import deepcopy
import math
from pathlib import Path
import sys

from . import guided_service as guided
from . import wired_capture as capture
from . import wired_probe as wired
from .device_session import DeviceSession
from .devices import discover
from .hardware import Snapshot, load_snapshot, read_journal
from .model import MODEL_CONTROLS, MODELS
from .onboard import Location, durable_json
from .profiles import ProfileStore
from .protocol import ProtocolError
from .reports import decode_wired
from .service import Daemon, socket_path


def coverage(document):
    """Replay captured mouse states across interfaces; no I/O or output events."""
    events = document['events']
    if document.get('product') != wired.PRODUCT or not 1 <= len(events) <= 4096:
        raise ProtocolError('Expected a bounded wired V3 capture')
    groups, down, up, pairs = {}, set(), set(), set()
    last = -1
    for event in events:
        t = event['t']
        if type(t) not in (int, float) or not math.isfinite(t) or not last <= t <= 180:
            raise ProtocolError('Invalid capture timestamp or order')
        last = t
        frame = decode_wired(MODELS[1], event['interface'], bytes.fromhex(event['raw']))
        if frame is None: continue
        before = frozenset().union(*groups.values())
        groups[frame.source] = frame.controls
        after = frozenset().union(*groups.values())
        down.update(after - before)
        up.update(before - after)
        for control, count in frame.pulses:
            if count:
                down.add(control); up.add(control)
        for first, second in (('ring_finger', 'side_12'), ('left_click', 'side_1')):
            if {first, second} <= after: pairs.add((first, second))
    held = frozenset().union(*groups.values())
    missing = set(MODEL_CONTROLS[MODELS[1]]) - (down & up)
    if held or missing or len(pairs) != 2:
        raise ProtocolError(f'Incomplete wired capture: missing {sorted(missing)}, '
                            f'held {sorted(held)}, combinations {sorted(pairs)}')
    return {'version': 1, 'product': wired.PRODUCT, 'controls': sorted(down & up),
            'combinations': [list(pair) for pair in sorted(pairs)], 'held': [], 'records': len(events)}


def validate_proof(proof):
    try:
        inspection, verification, mode, raw = (proof[k] for k in ('inspection', 'verification', 'mode', 'capture'))
        expected = capture.validate_inspection(inspection)
        if (type(proof.get('version')) is not int or proof['version'] != 1
                or proof.get('kind') != 'wired-input-proof'
                or expected['firmware'] != '01010000'
                or verification.get('normal_mode_verified') is not True
                or verification.get('stored_state_unchanged') is not True
                or verification.get('error') or verification['before'] != expected
                or verification['after'] != expected
                or verification['transport_health']['setting_commands'] != 2
                or mode.get('status') != 'normal-mode-restored' or mode.get('kind') != 'driver-mode'
                or mode.get('product') != wired.PRODUCT or mode.get('serial') != expected['serial']
                or mode.get('before') != '0000'
                or raw['descriptors'] != {n: v['raw'] for n, v in inspection['descriptors'].items() if n != '03'}):
            raise ProtocolError('Wired capture lacks verified mode and saved-state restoration')
        return coverage(raw)
    except (KeyError, TypeError, ValueError) as error:
        raise ProtocolError('Invalid wired input proof: ' + str(error)) from error


def proof_from(directory):
    prepared = read_journal(directory / 'prepared.json')
    proof = {'version': 1, 'kind': 'wired-input-proof', 'inspection': prepared['inspection'],
             **{name: read_journal(directory / 'run' / (filename + '.json')) for name, filename in
                (('verification', 'verification'), ('mode', 'mode'), ('capture', 'capture'))}}
    validate_proof(proof)
    return proof


class SessionHID(capture.ModeCaptureHID):
    """Mode-only transport bound to this isolated controller's active journal."""
    def __init__(self, path, state, serial, firmware):
        super().__init__(path, state / 'unclaimed-mode.json', serial)
        self.state, self.expected_firmware = state, firmware

    def __enter__(self):
        super().__enter__()
        try:
            if (self.execute(wired.BOOTSTRAP['firmware']).hex() != self.expected_firmware
                    or self.device_serial() != self.expected_serial):
                raise ProtocolError('Wired firmware or identity changed; no mode change admitted')
            return self
        except BaseException:
            self.__exit__()
            raise

    def _exchange(self, command):
        if command.operation < 0x80:
            candidates = []
            for path in self.state.glob('mode-*.json'):
                document = read_journal(path)
                if (document.get('kind') == 'driver-mode' and document.get('product') == wired.PRODUCT
                        and document.get('serial') == self.expected_serial
                        and document.get('status') in ('prepared', 'driver-mode-active')):
                    candidates.append(path)
            if len(candidates) != 1:
                raise ProtocolError('Exactly one active isolated wired mode journal is required')
            self.journal = candidates[0]
        return super()._exchange(command)


class Hardware:
    decode = staticmethod(decode_wired)

    def __init__(self, proof, directory, *, recovering=False):
        validate_proof(proof)
        self.proof, self.directory = deepcopy(proof), directory.resolve()
        self.inspection = self.proof['inspection']
        self.expected = capture.validate_inspection(self.inspection)
        self.state = self.directory / 'run/state/gillete/onboard'
        self.recovering = recovering

    def connected(self, product):
        if product != wired.PRODUCT:
            raise ProtocolError('The isolated wired test cannot enable another mouse')
        matches = [d for d in discover() if d.model == MODELS[1]]
        if not self.recovering and (len(matches) != 1 or matches[0].product_id != product):
            raise ProtocolError('Use only the wired V3 transport; disconnect its receiver for software testing')
        return capture.selected(self.inspection, recovery=self.recovering)

    def node(self, device):
        selected = self.connected(device.product_id)
        if device.model != MODELS[1] or device.usb_path != selected.usb_path:
            raise ProtocolError('The inspected wired transport changed')
        return wired.descriptors(selected)[self.inspection['read_only_route']]['node']

    def inspect(self, device, bank=None):
        with wired.WiredQueryHID(self.node(device)) as io:
            current = capture.read_state(io)
        if (current['serial'] != self.expected['serial'] or current['firmware'] != self.expected['firmware']
                or current['assigned'] != [1] or current['active'] != 1 or bank not in (None, 1)):
            raise ProtocolError('Wired identity, firmware or assigned slot differs from the accepted capture')
        return Snapshot(wired.PRODUCT, MODELS[1], current['serial'], 1, (1,), 1, set(current['controls']),
            {Location(r['bank'], r['control'], r['layer']): bytes.fromhex(r['raw'])
             for r in current['records'] if r['bank'] == 1}, current['settings'],
            {'firmware': current['firmware']})

    def transport(self, device):
        return SessionHID(self.node(device), self.state, self.expected['serial'], self.expected['firmware'])

    def session(self, device, coordinator, state, pin_profile, **kwargs):
        self.node(device)  # Reject other mice before opening inputs or creating output.
        if self.recovering or state.resolve() != self.state:
            raise ProtocolError('The wired session requires its isolated journal directory')
        return DeviceSession(device, coordinator, state, pin_profile, hardware=self, **kwargs)

    def daemon_command(self, config_path, suite):
        if suite != 'controls': raise ProtocolError('Only the reviewed wired control suite is available')
        return [sys.executable, '-m', 'gillete.wired_acceptance', 'daemon',
                '--directory', str(self.directory), '--config', str(config_path)]


def prepare(captured, directory):
    proof = proof_from(captured)
    hardware = Hardware(proof, directory)
    guided.prepare(wired.PRODUCT, directory, suite='controls', hardware=hardware)
    document = read_journal(directory / 'prepared.json')
    document['wired_proof'] = proof
    durable_json(directory / 'prepared.json', document)


def prepared_hardware(directory, *, recovering=False):
    document = read_journal(directory / 'prepared.json')
    if document.get('kind') != 'software-acceptance' or document.get('suite') != 'controls':
        raise ProtocolError('Expected the prepared wired control suite')
    return Hardware(document['wired_proof'], directory, recovering=recovering)


def recover(directory):
    if socket_path().exists():
        raise ProtocolError('Stop software control before recovering its owned wired mode')
    hardware = prepared_hardware(directory, recovering=True)
    device = hardware.connected(wired.PRODUCT)
    before = load_snapshot(read_journal(directory / 'prepared.json')['snapshot'])
    guided.recover_mode(device, before, hardware.state, hardware=hardware)
    after = hardware.inspect(device, before.bank)
    guided.assert_unchanged(before, after)
    durable_json(directory / 'run/recovery.json', {'version':1, 'normal_mode_verified':True,
                 'stored_state_unchanged':True, 'descriptor_count':len(before.records)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run', 'recover', 'daemon'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'prepare':
            if args.capture is None: parser.error('--capture is required to prepare')
            prepare(args.capture, args.directory)
        elif args.operation == 'recover':
            recover(args.directory)
        else:
            hardware = prepared_hardware(args.directory)
            if args.operation == 'run':
                asyncio.run(guided.run(args.directory, 600, hardware=hardware))
            else:
                expected = hardware.directory / 'run/profiles.json'
                if args.config is None or args.config.resolve() != expected:
                    raise ProtocolError('The wired experiment requires its isolated run configuration')
                asyncio.run(Daemon(ProfileStore(expected), trace_controls=True,
                                   session_factory=hardware.session).run())
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
