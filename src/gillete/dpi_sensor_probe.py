"""User-paced normal-mode DPI observation; never enables automatic support."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from . import dpi_probe as base
from .hardware import read_journal, transport
from .onboard import durable_json
from .protocol import Command, ProtocolError


PURPOSE = 'sensor-power-cycle'


def validate_feedback(value):
    if (not isinstance(value, dict) or set(value) != {'slower', 'power_cycled', 'speed_after_cycle'}
            or type(value['slower']) is not bool or value['power_cycled'] is not True
            or value['speed_after_cycle'] not in ('original', 'slower', 'unsure')):
        raise ProtocolError('Expected explicit sensitivity and power-cycle observations')
    return value


def exercise(io, prepared, path, feedback, *, ready=lambda: None, stopped=lambda: False,
             wait=time.sleep, now=time.monotonic):
    base.validate_document(prepared)
    if prepared.get('purpose') != PURPOSE or prepared.get('status') != 'prepared-read-only':
        raise ProtocolError('Requires a fresh sensor experiment preparation')
    if path.exists():
        raise ProtocolError('Sensor experiment already started; use its recovery journal')
    if base.stable_state(base.capture(base.ReadBudget(io, stopped))) != base.stable_state(prepared['before']):
        raise ProtocolError('Mouse changed since preparation; prepare again')
    document = deepcopy(prepared)
    document.update(status='armed', original_state_restored=False)
    durable_json(path, document)
    fatal = None
    try:
        reads = base.ReadBudget(io, stopped)
        base.guard(reads, document['before'])
        reads.checkpoint()
        io._exchange(Command(4, 5, bytes.fromhex(document['target'])))
        document['immediate'] = {'selector_zero': reads.execute(base.zero_query()).hex(),
                                 'settings': base.saved_values(reads)}
        if (document['immediate']['selector_zero'] != document['target']
                or document['immediate']['settings'] != document['before']['settings']):
            raise ProtocolError('Candidate DPI or saved-settings readback did not match')
        document['status'] = 'awaiting-user-observation'
        durable_json(path, document)
        deadline = now() + 180
        ready()
        while True:
            if stopped():
                raise InterruptedError('Sensor experiment cancelled')
            if now() >= deadline:
                raise ProtocolError('Sensor observation timed out')
            value = feedback()
            if value is not None:
                document['user_report'] = validate_feedback(value)
                break
            wait(.2)
        # The receiver remains connected during the reported mouse power cycle.
        # Do not query or resend setters while the user has the mouse switched off.
        observed = base.capture(base.ReadBudget(io, stopped))
        document['after_reported_power_cycle'] = observed
        if base.stable_state(observed, include_zero=False) != base.stable_state(document['before'], include_zero=False):
            raise ProtocolError('Protected state changed across the reported power cycle')
        value = observed['selector_zero']
        document['power_cycle_readback'] = ('original' if value == document['before']['selector_zero'] else
                                             'candidate' if value == document['target'] else 'other')
        document['power_cycle_evidence'] = 'user-reported; receiver was not unplugged'
    except BaseException as error:
        document['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception):
            fatal = error
    finally:
        try:
            base.restore_original(io, document)
        except BaseException as error:
            document['recovery_error'] = str(error) or type(error).__name__
            if not isinstance(error, Exception):
                fatal = error
        document['status'] = ('recovery-required' if not document['original_state_restored'] else
                              'test-failed-restored' if document.get('experiment_error') else 'sensor-observation-restored')
        durable_json(path, document)
    if fatal:
        raise fatal
    return document


def prepare(product, directory, requested_dpi=None):
    if directory.exists():
        raise ProtocolError('Choose a fresh sensor experiment directory')
    with transport(base.connected(product)) as io:
        document = base.prepare_document(base.ReadBudget(io), purpose=PURPOSE, requested_dpi=requested_dpi)
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', document)
    return document


def run(directory):
    prepared = read_journal(directory / 'prepared.json')
    base.validate_document(prepared)
    run_dir = directory / 'run'
    run_dir.mkdir(mode=0o700)
    response = run_dir / 'observation.json'

    def feedback():
        if not response.exists():
            return None
        if response.stat().st_size > 4096:
            raise ProtocolError('Observation is too large')
        return json.loads(response.read_text())

    with base.cancellation() as stopped, transport(base.connected(prepared['before']['product'])) as io:
        return exercise(io, prepared, run_dir / 'journal.json', feedback, stopped=stopped,
                        ready=lambda: print('READY: candidate DPI active; move mouse, power-cycle it, '
                                            'then supply observations. Restores after completion or 180 seconds.', flush=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--product', type=lambda value: int(value, 16), choices=base.PRODUCTS_ALLOWED, default=0xE8)
    parser.add_argument('--dpi', type=int, help='Explicit lower sensitivity for read-only preparation')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            document = prepare(args.product, args.directory, args.dpi)
            old = base.selector_zero(bytes.fromhex(document['before']['selector_zero']), args.product)
            target = base.selector_zero(bytes.fromhex(document['target']), args.product)
            print(f'PREPARED read-only: {old} -> {target}; originals saved, no setter sent.')
        else:
            if args.dpi is not None:
                raise ProtocolError('Run uses the exact DPI from its preparation; --dpi is prepare-only')
            document = run(args.directory)
            print('Sensor experiment: ' + document['status'])
            if document.get('experiment_error'):
                print(document['experiment_error'])
            return 0 if document['status'] == 'sensor-observation-restored' else 1
    except (OSError, ValueError, RuntimeError, ProtocolError) as error:
        parser.exit(1, str(error) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
