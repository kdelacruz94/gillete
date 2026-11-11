"""Journaled DPI retention check across an observed receiver USB replug."""

import argparse
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import errno
from pathlib import Path
import time

from . import dpi_probe as base
from .dpi_sensor_probe import PURPOSE
from .devices import discover
from .hardware import read_journal, transport
from .onboard import durable_json
from .persistence import route
from .protocol import Command, DeviceStatusError, DeviceUnavailable, ProtocolError


def validate_prepared(document):
    base.validate_document(document)
    expected = document.get('receiver_route')
    if (document.get('purpose') != PURPOSE or document.get('experiment') != 'receiver-replug'
            or document.get('status') != 'prepared-read-only' or not isinstance(expected, dict)
            or expected.get('product') != document['before']['product']
            or not isinstance(expected.get('usb_path'), str) or not expected['usb_path'].startswith('/sys/')
            or any(not isinstance(expected.get(k), str) or not expected[k].isdecimal()
                   for k in ('busnum', 'devnum'))):
        raise ProtocolError('Requires a complete receiver-replug preparation')


@contextmanager
def responsive_transport(opening, before, document, path, phase, *, stopped, wait, now):
    """Retry getter readiness only; errors from the yielded setter path escape."""
    deadline, remaining = now() + 45, 2048
    for attempt in range(1, 17):
        if stopped():
            raise InterruptedError('Receiver readiness cancelled')
        if now() >= deadline:
            raise ProtocolError('Receiver read-only readiness time limit reached')
        stack, reads = ExitStack(), None
        try:
            io = stack.enter_context(opening())
            reads = base.ReadBudget(io, stopped)
            reads.remaining = remaining
            base.guard(reads, before)
            observed = base.capture(reads)
        except BaseException as error:
            stack.close()
            transient = (isinstance(error, DeviceUnavailable)
                         or isinstance(error, DeviceStatusError) and error.status in (1, 4)
                         or isinstance(error, OSError) and error.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO))
            if not transient:
                raise
            if reads is not None:
                remaining = reads.remaining
            entry = {'phase': phase, 'attempt': attempt, 'error': str(error)}
            if isinstance(error, DeviceStatusError):
                entry['device_status'] = error.status
            document.setdefault('readiness_retries', []).append(entry)
            durable_json(path, document)
            if attempt == 16 or now() >= deadline or remaining <= 0:
                raise ProtocolError('Receiver read-only readiness limit reached: ' + str(error)) from error
            wait(.5)
            continue
        # Deliberately outside the retry try/except. A caller's uncertain SET
        # or restoration failure must never cause another setter submission.
        try:
            yield io, observed
        finally:
            stack.close()
        return


def exercise(prepared, path, opening, observe, *, ready=lambda: None,
             stopped=lambda: False, wait=time.sleep, now=time.monotonic):
    validate_prepared(prepared)
    if path.exists():
        raise ProtocolError('Experiment already started; use its recovery journal')
    expected = prepared['receiver_route']
    if observe() != expected:
        raise ProtocolError('Receiver changed since preparation')
    document = deepcopy(prepared)
    armed, fatal = False, None
    try:
        with opening() as io:
            reads = base.ReadBudget(io, stopped)
            if base.stable_state(base.capture(reads)) != base.stable_state(prepared['before']):
                raise ProtocolError('Mouse changed since preparation')
            document.update(status='armed', original_state_restored=False)
            durable_json(path, document)
            armed = True
            base.guard(reads, document['before'])
            reads.checkpoint()
            io._exchange(Command(4, 5, bytes.fromhex(document['target'])))
            document['immediate'] = {'selector_zero': reads.execute(base.zero_query()).hex(),
                                     'settings': base.saved_values(reads)}
            if (document['immediate']['selector_zero'] != document['target']
                    or document['immediate']['settings'] != document['before']['settings']):
                raise ProtocolError('Candidate DPI or protected settings did not match')
        # No descriptor stays open across USB removal; no SET is replayed.
        document['status'] = 'awaiting-receiver-replug'
        durable_json(path, document)
        deadline, disconnected = now() + 180, False
        ready()
        while True:
            if stopped():
                raise InterruptedError('Receiver experiment cancelled')
            if now() >= deadline:
                raise ProtocolError('Receiver-replug observation timed out')
            current = observe()
            if current is None:
                if not disconnected:
                    disconnected = True
                    document['receiver_disconnect_observed'] = True
                    durable_json(path, document)
            elif disconnected and not current.get('pending'):
                if (current.get('product') != expected['product']
                        or current.get('usb_path') != expected['usb_path']):
                    raise ProtocolError('A different receiver route appeared')
                if (current['busnum'], current['devnum']) != (expected['busnum'], expected['devnum']):
                    document['reconnected_route'] = current
                    break
            wait(.2)
        with responsive_transport(opening, document['before'], document, path, 'after-replug',
                                  stopped=stopped, wait=wait, now=now) as (io, observed):
            document['after_receiver_replug'] = observed
            if base.stable_state(observed, include_zero=False) != base.stable_state(document['before'], include_zero=False):
                raise ProtocolError('Protected mouse state changed across receiver replug')
            value = observed['selector_zero']
            document['receiver_replug_readback'] = ('original' if value == document['before']['selector_zero'] else
                                                    'candidate' if value == document['target'] else 'other')
    except BaseException as error:
        if not armed:
            raise
        document['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception):
            fatal = error
    finally:
        if armed:
            try:
                with responsive_transport(opening, document['before'], document, path, 'restoration',
                                          stopped=lambda: False, wait=wait, now=now) as (io, _):
                    base.restore_original(io, document)
            except BaseException as error:
                document['recovery_error'] = str(error) or type(error).__name__
                if not isinstance(error, Exception):
                    fatal = error
            document['status'] = ('recovery-required' if not document['original_state_restored'] else
                                  'test-failed-restored' if document.get('experiment_error') else 'receiver-replug-restored')
            durable_json(path, document)
    if fatal:
        raise fatal
    return document


def observe_route(expected):
    matches = [d for d in discover() if d.product_id == expected['product'] and d.usb_path == expected['usb_path']]
    if not matches:
        return {'pending': True} if Path(expected['usb_path']).exists() else None
    if len(matches) != 1:
        raise ProtocolError('Receiver route is ambiguous')
    try:
        return route(matches[0])
    except (OSError, ProtocolError):
        return {'pending': True}  # Incomplete interfaces do not prove removal.


def prepare(product, directory, dpi):
    if directory.exists():
        raise ProtocolError('Choose a fresh receiver experiment directory')
    device = base.connected(product)
    expected = route(device)
    with transport(device) as io:
        document = base.prepare_document(base.ReadBudget(io), purpose=PURPOSE, requested_dpi=dpi)
    if route(base.connected(product)) != expected:
        raise ProtocolError('Receiver changed during preparation')
    document.update(experiment='receiver-replug', receiver_route=expected)
    validate_prepared(document)
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', document)
    return document


def run(directory):
    document = read_journal(directory / 'prepared.json')
    validate_prepared(document)
    run_dir = directory / 'run'
    run_dir.mkdir(mode=0o700)
    expected = document['receiver_route']

    def opening():
        device = base.connected(expected['product'])
        if device.usb_path != expected['usb_path']:
            raise ProtocolError('Reconnect the receiver to its original USB port')
        return transport(device)

    with base.cancellation() as stopped:
        return exercise(document, run_dir / 'journal.json', opening, lambda: observe_route(expected),
                        stopped=stopped, ready=lambda: print('READY: candidate DPI active. Unplug the selected receiver, '
                                                            'wait five seconds, reconnect to the same USB port; keep mouse on.', flush=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--product', type=lambda value: int(value, 16), choices=base.PRODUCTS_ALLOWED, default=0xE8)
    parser.add_argument('--dpi', type=int, help='Prepare-only explicit lower DPI (default 1200)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            document = prepare(args.product, args.directory, 1200 if args.dpi is None else args.dpi)
            old = base.selector_zero(bytes.fromhex(document['before']['selector_zero']), args.product)
            target = base.selector_zero(bytes.fromhex(document['target']), args.product)
            print(f'PREPARED read-only: {old} -> {target}; same-port replug, then verified restoration.')
        else:
            if args.dpi is not None:
                raise ProtocolError('Run uses the prepared DPI; --dpi is prepare-only')
            document = run(args.directory)
            print('Receiver experiment: ' + document['status'])
            if document.get('experiment_error'):
                print(document['experiment_error'])
            return 0 if document['status'] == 'receiver-replug-restored' else 1
    except (OSError, ValueError, RuntimeError, ProtocolError) as error:
        parser.exit(1, str(error) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
