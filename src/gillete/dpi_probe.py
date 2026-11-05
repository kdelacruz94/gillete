"""Explicit reversible selector-zero DPI experiment, separate from the service.

Readback independence is only one prerequisite for per-program hardware DPI.
This experiment does not establish sensor behavior, power-cycle persistence or
driver-mode support, and never enables a production capability automatically.
"""

import argparse
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import signal
import time

from .compile_onboard import CONTROL_IDS
from .devices import PRODUCTS, discover
from .hardware import inventory, profile_slots, read_journal, read_records, transport
from .onboard import durable_json
from .protocol import Command, ProtocolError
from .settings import DPI_MAX, SPECS, decode_dpi, describe, query, validate_value


PRODUCTS_ALLOWED = (0xB4, 0xE8)
KIND = 'temporary-dpi-experiment'


def selector_zero(raw, product):
    if len(raw) != 7 or raw[0] != 0:
        raise ProtocolError('DPI query did not echo selector zero')
    return decode_dpi(b'\1' + raw[1:], product)


def zero_query():
    return Command(4, 0x85, bytes(7))


def saved_values(io):
    return {name: io.execute(query(name)).hex() for name in SPECS}


def guard(io, before):
    if io.product != before['product'] or io.device_serial() != before['serial']:
        raise ProtocolError('DPI experiment belongs to a different mouse')
    io.require_normal_mode()
    if io.execute(Command(0, 0x81, bytes(2))).hex() != before['firmware']:
        raise ProtocolError('Mouse firmware changed since the DPI experiment was prepared')
    assigned, active = profile_slots(io)
    if list(assigned) != before['assigned'] or active != before['active']:
        raise ProtocolError('Onboard profile selection/inventory changed during DPI experiment')


def capture(io):
    if io.product not in PRODUCTS_ALLOWED:
        raise ProtocolError('DPI experiment requires a verified B4/E8 receiver route')
    model = PRODUCTS[io.product][0]
    io.require_normal_mode()
    serial = io.device_serial()
    firmware = io.execute(Command(0, 0x81, bytes(2))).hex()
    assigned, active = profile_slots(io)
    controls = inventory(io)
    if not set(CONTROL_IDS[model].values()) <= controls:
        raise ProtocolError('Mouse control inventory does not match this layout')
    records = {}
    for bank in (0, *assigned):
        records.update(read_records(io, model, bank))
    before = {'product': io.product, 'serial': serial, 'firmware': firmware,
              'assigned': list(assigned), 'active': active, 'controls': sorted(controls),
              'records': [{**where.json(), 'raw': raw.hex()} for where, raw in sorted(records.items())],
              'settings': saved_values(io), 'selector_zero': io.execute(zero_query()).hex()}
    validate_state(before)
    guard(io, before)
    return before


def validate_state(state):
    """Validate recovery bytes and identity before admitting any setter."""
    try:
        product = state['product']
        if type(product) is not int or product not in PRODUCTS_ALLOWED:
            raise ValueError('Unsupported receiver')
        serial = state['serial']
        if (not isinstance(serial, str) or not 1 <= len(serial) <= 22
                or set(serial) == {'0'} or any(not 32 <= ord(c) < 127 for c in serial)):
            raise ValueError('Invalid hardware identity')
        if len(bytes.fromhex(state['firmware'])) != 2:
            raise ValueError('Invalid firmware version')
        assigned, active = state['assigned'], state['active']
        maximum = 1 if product == 0xB4 else 5
        if (not isinstance(assigned, list) or not 1 <= len(assigned) <= maximum
                or any(type(v) is not int or not 1 <= v <= maximum for v in assigned)
                or len(set(assigned)) != len(assigned) or type(active) is not int or active not in assigned):
            raise ValueError('Invalid assigned profiles')
        expected = set(CONTROL_IDS[PRODUCTS[product][0]].values())
        controls = state['controls']
        if (not isinstance(controls, list) or not 1 <= len(controls) <= 79
                or any(type(v) is not int or not 1 <= v <= 255 for v in controls)
                or len(set(controls)) != len(controls) or not expected <= set(controls)):
            raise ValueError('Invalid control inventory')
        wanted = {(bank, control, layer) for bank in (0, *assigned) for control in expected for layer in (0, 1)}
        records = state['records']
        if not isinstance(records, list) or len(records) != len(wanted):
            raise ValueError('Incomplete original bindings')
        found = set()
        for record in records:
            where = tuple(record[name] for name in ('bank', 'control', 'layer'))
            raw = bytes.fromhex(record['raw'])
            if (any(type(v) is not int for v in where) or where not in wanted or where in found
                    or len(raw) != 10 or raw[:2] != bytes(where[:2]) or raw[2] not in (0, 1)):
                raise ValueError('Invalid original binding')
            found.add(where)
        if set(state['settings']) != set(SPECS):
            raise ValueError('Incomplete original settings')
        for name, value in state['settings'].items():
            validate_value(name, bytes.fromhex(value), product)
        selector_zero(bytes.fromhex(state['selector_zero']), product)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ProtocolError('Invalid DPI experiment state: ' + str(error)) from error


def stable_state(state, *, include_zero=True):
    result = deepcopy(state)
    # Reply byte 2 is metadata, not part of a saved button function. Retain it
    # in evidence, but do not confuse a changed reply flag with a new mapping.
    result['records'] = sorted((r['bank'], r['control'], r['layer'], r['raw'][6:]) for r in result['records'])
    if not include_zero:
        result.pop('selector_zero')
    return result


def target_value(before, purpose='readback', requested_dpi=None):
    old = selector_zero(bytes.fromhex(before['selector_zero']), before['product'])
    saved = decode_dpi(bytes.fromhex(before['settings']['dpi']), before['product'])
    if purpose == 'sensor-power-cycle':
        if requested_dpi is not None and (type(requested_dpi) is not int or not 100 <= requested_dpi < min(old)):
            raise ProtocolError('Requested sensor DPI must be an integer from 100 below both original axes')
        pair = ([requested_dpi] * 2 if requested_dpi is not None else
                [max(100, (value // 200) * 100) for value in old])
        if any(value in (old[i], saved[i]) for i, value in enumerate(pair)):
            raise ProtocolError('Cannot prepare a distinct half-sensitivity value at this DPI')
        return (b'\0' + b''.join(v.to_bytes(2, 'big') for v in pair)
                + bytes.fromhex(before['selector_zero'])[5:]).hex()
    if purpose != 'readback':
        raise ProtocolError('Unknown DPI experiment purpose')
    if requested_dpi is not None:
        raise ProtocolError('A requested DPI is only valid for the user-paced sensor experiment')
    # Each axis differs from both original getters by a small bounded amount.
    pair = [next(value + delta for delta in (100, -100, 200, -200)
                 if 100 <= value + delta <= DPI_MAX[before['product']] and value + delta != saved[i])
            for i, value in enumerate(old)]
    return (b'\0' + b''.join(v.to_bytes(2, 'big') for v in pair)
            + bytes.fromhex(before['selector_zero'])[5:]).hex()


def validate_document(document):
    if (type(document.get('version')) is not int or document['version'] != 1
            or document.get('kind') != KIND or document.get('temporary_dpi_supported') is not False):
        raise ProtocolError('Not a temporary-DPI experiment journal')
    validate_state(document.get('before'))
    if document.get('target') != target_value(document['before'], document.get('purpose', 'readback'),
                                             document.get('requested_dpi')):
        raise ProtocolError('DPI target differs from the bounded prepared experiment')


def prepare_document(io, *, purpose='readback', requested_dpi=None):
    before = capture(io)
    return {'version': 1, 'kind': KIND, 'status': 'prepared-read-only', 'before': before,
            'purpose': purpose, 'requested_dpi': requested_dpi, 'target': target_value(before, purpose, requested_dpi),
            'selector_readback_independent': False,
            'original_state_restored': False, 'temporary_dpi_supported': False}


class ReadBudget:
    """Check cancellation and bounded query work between kernel operations."""
    def __init__(self, io, stopped=lambda: False):
        self.io, self.product, self.stopped = io, io.product, stopped
        self.remaining, self.deadline = 2048, time.monotonic() + 120

    def checkpoint(self):
        if self.stopped():
            raise InterruptedError('DPI experiment cancelled')
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            raise ProtocolError('DPI experiment read/time limit reached')

    def execute(self, command):
        self.checkpoint()
        self.remaining -= 1
        return self.io.execute(command)

    def device_serial(self):
        self.checkpoint()
        self.remaining -= 1
        return self.io.device_serial()

    def require_normal_mode(self):
        if self.execute(Command(0, 0x84, bytes(2))) != bytes(2):
            raise ProtocolError('DPI experiment requires normal mode; no mode change was made')

    def read_binding_record(self, bank, control, layer):
        return self.execute(Command(2, 0x8C, bytes((bank, control, layer)) + bytes(7)))


def restore_original(io, document):
    """Repair changed saved values, then selector zero; never rewrite bindings.

    A candidate selector can alias saved storage. Repair saved storage again if
    restoring selector zero affects it, then require both getters to match. Do
    not loop or repeatedly resend an uncertain setter.
    """
    validate_document(document)
    document['original_state_restored'] = False
    before = document['before']
    guard(io, before)

    def repair_saved():
        current = saved_values(io)
        changes = {name for name in SPECS if current[name] != before['settings'][name]}
        if 'stages' in changes:
            changes.add('dpi')  # A table setter may change the scalar as well.
        for name, (category, setter, _, _) in SPECS.items():
            if name in changes:
                guard(io, before)
                io._exchange(Command(category, setter, bytes.fromhex(before['settings'][name])))
        if saved_values(io) != before['settings']:
            raise ProtocolError('Saved settings restoration did not verify; recovery journal retained')

    repair_saved()
    if io.execute(zero_query()).hex() != before['selector_zero']:
        guard(io, before)
        io._exchange(Command(4, 5, bytes.fromhex(before['selector_zero'])))
    repair_saved()
    after = capture(io)
    document['after_restore'] = after
    if stable_state(after) != stable_state(before):
        raise ProtocolError('Original DPI/settings/binding state did not verify; recovery journal retained')
    document['original_state_restored'] = True


def exercise(io, prepared, path, *, hold_seconds=3, stopped=lambda: False, wait=time.sleep):
    if type(hold_seconds) is not int or not 0 <= hold_seconds <= 10:
        raise ProtocolError('DPI experiment duration must be 0–10 seconds')
    validate_document(prepared)
    if prepared.get('purpose', 'readback') != 'readback':
        raise ProtocolError('Use the user-paced sensor experiment for this preparation')
    if path.exists():
        raise ProtocolError('This experiment has already started; use its recovery journal')
    document = deepcopy(prepared)
    before = document['before']
    reads = ReadBudget(io, stopped)
    if stable_state(capture(reads)) != stable_state(before):
        raise ProtocolError('Mouse changed since preparation; prepare a fresh DPI experiment')
    document.update(status='armed', selector_readback_independent=False, original_state_restored=False)
    durable_json(path, document)  # Complete originals on disk before the first SET.
    fatal = None
    try:
        reads.checkpoint()
        guard(reads, before)
        reads.checkpoint()
        io._exchange(Command(4, 5, bytes.fromhex(document['target'])))
        # Check the coupled settings immediately, before holding the value or
        # spending time enumerating bindings. No ACK is accepted as readback.
        current = {'selector_zero': reads.execute(zero_query()).hex(), 'settings': saved_values(reads)}
        document['immediate'] = current
        if current['selector_zero'] != document['target']:
            raise ProtocolError('Selector-zero DPI did not match the proposed value')
        if current['settings'] != before['settings']:
            raise ProtocolError('Selector-zero DPI changed saved-settings readback')
        for _ in range(hold_seconds * 10):
            reads.checkpoint()
            wait(.1)
        observed = capture(reads)
        document['observed'] = observed
        if (observed['selector_zero'] != document['target']
                or stable_state(observed, include_zero=False) != stable_state(before, include_zero=False)):
            raise ProtocolError('DPI or protected mouse state changed during the experiment')
        document['selector_readback_independent'] = True
    except BaseException as error:
        document['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception):
            fatal = error
    finally:
        # Cleanup deliberately bypasses the experiment's cancellation/budget.
        # Never abort restoration because the test duration or query budget ran out.
        try:
            restore_original(io, document)
        except BaseException as error:
            document['recovery_error'] = str(error) or type(error).__name__
            if not isinstance(error, Exception):
                fatal = error
        document['status'] = ('recovery-required' if not document['original_state_restored'] else
                              'test-failed-restored' if document.get('experiment_error') else 'readback-roundtrip-restored')
        durable_json(path, document)
    if fatal:
        raise fatal
    return document


def connected(product):
    if product not in PRODUCTS_ALLOWED:
        raise ProtocolError('Choose receiver product 00b4 or 00e8')
    matches = [device for device in discover() if device.model == PRODUCTS[product][0]]
    if len(matches) != 1 or matches[0].product_id != product:
        raise ProtocolError('Connect exactly one transport for the selected model, using its receiver')
    return matches[0]


def prepare(product, directory):
    if directory.exists():
        raise ProtocolError('Choose a new DPI experiment directory')
    with transport(connected(product)) as io:
        document = prepare_document(ReadBudget(io))
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', document)
    return document


@contextmanager
def cancellation():
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield lambda: stopped
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run(directory, hold_seconds):
    prepared = read_journal(directory / 'prepared.json')
    validate_document(prepared)
    if prepared.get('status') != 'prepared-read-only':
        raise ProtocolError('Run requires a fresh read-only preparation')
    # Claim once, independently of journal creation; concurrent/repeated runs
    # cannot overwrite a prior journal, even if preflight fails.
    run_directory = directory / 'run'
    run_directory.mkdir(mode=0o700)
    with cancellation() as stopped, transport(connected(prepared['before']['product'])) as io:
        return exercise(io, prepared, run_directory / 'journal.json', hold_seconds=hold_seconds, stopped=stopped)


def recover(path):
    document = read_journal(path)
    validate_document(document)
    if document.get('status') not in {'armed', 'recovery-required', 'test-failed-restored',
                                      'readback-roundtrip-restored', 'original-state-restored',
                                      'sensor-observation-restored', 'awaiting-user-observation'}:
        raise ProtocolError('Recovery requires a journal from an attempted experiment')
    document['original_state_restored'] = False
    # Cancellation requests are deferred until restoration has completed.
    with cancellation(), transport(connected(document['before']['product'])) as io:
        try:
            restore_original(io, document)
        except BaseException as error:
            document.update(status='recovery-required', recovery_error=str(error) or type(error).__name__)
            durable_json(path, document)
            raise
        document['status'] = 'original-state-restored'
        document.pop('recovery_error', None)
        durable_json(path, document)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    first = commands.add_parser('prepare', help='Read-only snapshot and exact proposed DPI change')
    first.add_argument('--product', required=True, type=lambda v: int(v, 16), choices=PRODUCTS_ALLOWED)
    first.add_argument('--directory', required=True, type=Path)
    trial = commands.add_parser('run', help='Explicitly change DPI, check independence, then restore')
    trial.add_argument('--directory', required=True, type=Path)
    trial.add_argument('--hold-seconds', type=int, choices=range(0, 11), default=3)
    recovery = commands.add_parser('recover', help='Explicitly restore original settings from a retained journal')
    recovery.add_argument('--journal', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            document = prepare(args.product, args.directory)
            before = document['before']
            old = selector_zero(bytes.fromhex(before['selector_zero']), before['product'])
            target = selector_zero(bytes.fromhex(document['target']), before['product'])
            print(f'PREPARED — read only. Selector-zero DPI: {old[0]} × {old[1]} → {target[0]} × {target[1]}.')
            print('Run will submit 04:05 with selector 0, then restore the original value. '
                  'If saved settings change, restoration may write their original DPI/stages/polling values.')
            for name in SPECS:
                print(f"Original saved {name}: {describe(name, bytes.fromhex(before['settings'][name]), before['product'])}")
            print('Exact originals and candidate bytes are in the private prepared.json; no settings changed.')
            return 0
        document = run(args.directory, args.hold_seconds) if args.command == 'run' else recover(args.journal)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f'{error}\n')
    print('DPI experiment: ' + document['status'])
    for key in ('experiment_error', 'recovery_error'):
        if document.get(key):
            print(document[key])
    print('Readback does not prove sensor behavior, power-cycle persistence or driver-mode support.')
    return 0 if document['original_state_restored'] and (args.command == 'recover' or not document.get('experiment_error')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
