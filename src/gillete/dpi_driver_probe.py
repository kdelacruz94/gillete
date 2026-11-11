"""Explicit user-paced DPI validation in temporary driver mode."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from . import dpi_probe as base
from .driver_mode import ModeLease
from .hardware import read_journal, transport
from .onboard import durable_json
from .protocol import Command, ProtocolError
from .service import socket_path


def validate(prepared):
    base.validate_document(prepared)
    if prepared.get('experiment') != 'driver-dpi' or prepared.get('purpose') != 'sensor-power-cycle':
        raise ProtocolError('Not a prepared driver-mode DPI experiment')


def driver_state(io, before):
    if io.product != before['product'] or io.device_serial() != before['serial']:
        raise ProtocolError('Driver DPI experiment belongs to another mouse')
    if io.execute(Command(0, 0x84, bytes(2))) != b'\3\0':
        raise ProtocolError('Expected owned driver mode')
    if io.execute(Command(0, 0x81, bytes(2))).hex() != before['firmware']:
        raise ProtocolError('Firmware changed during driver-mode DPI test')
    assigned, active = base.profile_slots(io)
    if list(assigned) != before['assigned'] or active != before['active']:
        raise ProtocolError('Profile inventory changed during driver-mode DPI test')
    return {'selector_zero': io.execute(base.zero_query()).hex(), 'settings': base.saved_values(io)}


def exercise(io, prepared, path, mode_path, feedback, *, ready=lambda: None,
             stopped=lambda: False, wait=time.sleep, now=time.monotonic):
    validate(prepared)
    if prepared.get('status') != 'prepared-read-only' or path.exists() or mode_path.exists():
        raise ProtocolError('Requires fresh driver-mode DPI preparation and journals')
    if base.stable_state(base.capture(base.ReadBudget(io, stopped))) != base.stable_state(prepared['before']):
        raise ProtocolError('Mouse changed since preparation')
    document = deepcopy(prepared)
    document.update(status='armed', original_state_restored=False, normal_mode_restored=False)
    durable_json(path, document)
    lease, fatal = ModeLease(io, mode_path), None
    try:
        if stopped():
            raise InterruptedError('Driver DPI test cancelled')
        lease.enter()
        reads = base.ReadBudget(io, stopped)
        document['driver_before'] = driver_state(reads, document['before'])
        if document['driver_before']['settings'] != document['before']['settings']:
            raise ProtocolError('Mode entry changed saved settings')
        reads.checkpoint()
        io._exchange(Command(4, 5, bytes.fromhex(document['target'])))
        document['driver_candidate'] = driver_state(reads, document['before'])
        if (document['driver_candidate']['selector_zero'] != document['target']
                or document['driver_candidate']['settings'] != document['before']['settings']):
            raise ProtocolError('Driver-mode DPI or protected saved settings did not match')
        document['status'] = 'awaiting-driver-observation'
        durable_json(path, document)
        deadline = now() + 180
        ready()
        while True:
            if stopped():
                raise InterruptedError('Driver DPI observation cancelled')
            if now() >= deadline:
                raise ProtocolError('Driver DPI observation timed out')
            value = feedback()
            if value is not None:
                if not isinstance(value, dict) or set(value) != {'feels_usual'} or type(value['feels_usual']) is not bool:
                    raise ProtocolError('Expected an explicit driver-mode sensitivity observation')
                document['user_report'] = value
                break
            wait(.2)
        document['driver_observed'] = driver_state(reads, document['before'])
        if document['driver_observed'] != document['driver_candidate']:
            raise ProtocolError('Driver state changed during observation')
    except BaseException as error:
        document['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception):
            fatal = error
    finally:
        # Leave driver mode before the existing normal-mode settings repair.
        # Even an uncertain mode SET may have taken effect; use its journal.
        try:
            if mode_path.exists():
                lease.restore()
            document['normal_mode_restored'] = io.execute(Command(0, 0x84, bytes(2))) == bytes(2)
            if not document['normal_mode_restored']:
                raise ProtocolError('Normal mode restoration did not verify')
            base.restore_original(io, document)
        except BaseException as error:
            document['recovery_error'] = str(error) or type(error).__name__
            if not isinstance(error, Exception):
                fatal = error
        document['status'] = ('recovery-required' if not document['original_state_restored'] else
                              'test-failed-restored' if document.get('experiment_error') else 'driver-dpi-restored')
        durable_json(path, document)
    if fatal:
        raise fatal
    return document


def prepare(product, directory, dpi):
    if directory.exists() or socket_path().exists():
        raise ProtocolError('Choose a fresh directory and stop the Gillete service first')
    with transport(base.connected(product)) as io:
        document = base.prepare_document(base.ReadBudget(io), purpose='sensor-power-cycle', requested_dpi=dpi)
    document['experiment'] = 'driver-dpi'
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', document)
    return document


def run(directory):
    prepared = read_journal(directory / 'prepared.json')
    validate(prepared)
    if socket_path().exists():
        raise ProtocolError('Stop the Gillete service before this isolated test')
    root = directory / 'run'
    root.mkdir(mode=0o700)
    def feedback():
        response = root / 'observation.json'
        if not response.exists():
            return None
        if response.stat().st_size > 4096:
            raise ProtocolError('Observation too large')
        return json.loads(response.read_text())
    with base.cancellation() as stopped, transport(base.connected(prepared['before']['product'])) as io:
        return exercise(io, prepared, root / 'journal.json', root / 'mode.json', feedback, stopped=stopped,
                        ready=lambda: print('READY: driver mode and candidate DPI active. Move the mouse only; '
                                            'do not power-cycle or unplug it. Restores on report or timeout.', flush=True))


def recover(directory):
    root = directory / 'run'
    document = read_journal(root / 'journal.json')
    validate(document)
    with transport(base.connected(document['before']['product'])) as io:
        if (root / 'mode.json').exists():
            ModeLease(io, root / 'mode.json').restore()
    result = base.recover(root / 'journal.json')
    result['normal_mode_restored'] = True
    durable_json(root / 'journal.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'recover'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--product', type=lambda value: int(value, 16), choices=base.PRODUCTS_ALLOWED, default=0xE8)
    parser.add_argument('--dpi', type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            document = prepare(args.product, args.directory, 1200 if args.dpi is None else args.dpi)
            pair = base.selector_zero(bytes.fromhex(document['target']), args.product)
            print(f'PREPARED read-only: temporary driver mode, DPI {pair}; normal mode and originals will be restored.')
        else:
            if args.dpi is not None:
                raise ProtocolError('--dpi is prepare-only')
            document = run(args.directory) if args.command == 'run' else recover(args.directory)
            print('Driver DPI experiment: ' + document['status'])
            for key in ('experiment_error', 'recovery_error'):
                if document.get(key):
                    print(document[key])
            return 0 if (document['original_state_restored'] and not document.get('recovery_error')
                         and (args.command == 'recover' or document['status'] == 'driver-dpi-restored')) else 1
    except (OSError, ValueError, RuntimeError, ProtocolError) as error:
        parser.exit(1, str(error) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
