"""Opt-in two-asset normal/HyperShift test; production Save to Mouse stays gated."""

import argparse
import json
import math
from pathlib import Path
import time

from . import dpi_probe as base
from . import native_macro_probe as probe
from . import native_profile_transaction as tx
from .hardware import read_journal
from .model import Action, Layers, Profile, Step
from .native_macro_observer import SequenceObserver
from .onboard import durable_json
from .protocol import ProtocolError
from .service import socket_path


EXPECTED = ('F24', 'F23', 'F24', 'F23')


def test_profile():
    def macro(key):
        return Action('macro', steps=(Step('down', key), Step('wait', milliseconds=80), Step('up', key)))
    return Profile('native-two-asset-validation', 'Gillete native validation',
                   Layers(normal={c: macro('KEY_F24') for c in ('side_11', 'side_12')},
                          shifted={c: macro('KEY_F23') for c in ('side_11', 'side_12')}))


def validate(prepared):
    preview = tx.validate(prepared)
    if prepared['profile'] != test_profile().json() or prepared['catalog_before']['ids']:
        raise ProtocolError('Expected the exact two-asset experiment and empty initial catalog')
    before = tx.originals(prepared['before'])
    if any(raw[3:] != bytes.fromhex('0c013900000000') for where, raw in before.items()
           if where.bank == 1 and where.control == 0x39):
        raise ProtocolError('Existing ring-finger HyperShift trigger is required; it will not be changed')
    changes = {(w.control, w.layer) for w, target in preview.bindings.items() if before[w][3:] != target}
    if changes != {(c, l) for c in (0x4A, 0x4B) for l in (0, 1)} or len(preview.assets) != 2:
        raise ProtocolError('Test must change only both layers of sides 11/12 and upload exactly two assets')
    return preview


def validate_observation(observation):
    if not isinstance(observation, dict) or set(observation) != {'sequence', 'sequence_completed'}:
        raise ProtocolError('Expected actual key observations plus explicit user sequence confirmation')
    sequence = observation['sequence']
    if (observation['sequence_completed'] is not True or not isinstance(sequence, list) or len(sequence) != 4
            or any(not isinstance(e, dict) or set(e) != {'key', 'hold_ms'} or e['key'] != key
                   or type(e['hold_ms']) not in (float, int) or not math.isfinite(e['hold_ms'])
                   or not 0 <= e['hold_ms'] <= 180000 for key, e in zip(EXPECTED, sequence))):
        raise ProtocolError('Native button sequence or user confirmation did not match')


def observe_sequence(observer, report, stopped, *, now=time.monotonic, wait=time.sleep):
    result = observer.observe(stopped)
    while now() < observer.armed_at + 180:
        if stopped(): raise InterruptedError('Native profile sequence cancelled')
        if report.exists():
            with report.open('rb') as handle: raw = handle.read(4097)
            if len(raw) > 4096: raise ProtocolError('Sequence confirmation too large')
            confirmation = json.loads(raw)
            if confirmation != {'sequence_completed': True} or confirmation['sequence_completed'] is not True:
                raise ProtocolError('Expected explicit confirmation of the requested physical sequence')
            result = {**result, **confirmation}
            validate_observation(result)
            return result
        wait(.2)
    raise ProtocolError('User sequence confirmation timed out')


def exercise(io, prepared, root, observe, *, ready=lambda: None, stopped=lambda: False):
    preview = validate(prepared)
    path = root / 'profile.json'
    result_path = root / 'experiment.json'
    if path.exists() or result_path.exists(): raise ProtocolError('Fresh experiment paths required')
    result = {'version': 1, 'kind': 'native-two-asset-observation', 'status': 'preparing',
              'native_sequence_observed': False, 'original_state_restored': False}
    durable_json(result_path, result)
    fatal = None
    try:
        saved = tx.apply(io, prepared, path, stopped=stopped)
        result['status'] = 'awaiting-native-sequence'
        durable_json(result_path, result)
        ready()
        observation = observe(stopped)
        validate_observation(observation)
        if probe.normalized(probe.snapshot(base.ReadBudget(io, stopped))) != probe.normalized(saved['saved_state']):
            raise ProtocolError('Saved profile changed during native observation')
        for asset in preview.assets: tx.verify_asset(io, asset)
        result.update(observation=observation, native_sequence_observed=True)
    except BaseException as error:
        result['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception): fatal = error
    finally:
        try:
            if path.exists():
                recovered = tx.undo(io, path)
                result['original_state_restored'] = recovered['original_state_restored']
            else:
                result['original_state_restored'] = (probe.normalized(probe.snapshot(base.ReadBudget(io)))
                                                      == probe.normalized(prepared['before']))
        except BaseException as error:
            result['recovery_error'] = str(error) or type(error).__name__
            if not isinstance(error, Exception): fatal = error
        result['status'] = ('recovery-required' if not result['original_state_restored'] else
                            'test-failed-restored' if result.get('experiment_error') else 'native-profile-test-restored')
        durable_json(result_path, result)
    if fatal: raise fatal
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run', 'recover'))
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if socket_path().exists(): raise ProtocolError('Stop the Gillete service before this isolated test')
        if args.operation == 'prepare':
            if args.directory.exists(): raise ProtocolError('Choose a fresh experiment directory')
            with probe.open_mouse() as io: prepared = tx.prepare(io, test_profile())
            validate(prepared)
            args.directory.mkdir(parents=True, mode=0o700)
            durable_json(args.directory / 'prepared.json', prepared)
            print('Native profile test: prepared-read-only')
            return 0
        if args.operation == 'recover':
            with probe.open_mouse() as io: result = tx.undo(io, args.directory / 'run/profile.json')
            print('Native profile recovery:', result['status'])
            return 0
        prepared = read_journal(args.directory / 'prepared.json')
        validate(prepared)
        root = args.directory / 'run'
        root.mkdir(mode=0o700)
        with base.cancellation() as stopped, SequenceObserver(base.connected(0xE8)) as observer, probe.open_mouse() as io:
            def ready():
                observer.arm()
                print('READY: side12; ring+side12; side11; ring+side11. Release each. '
                      'Confirm the full sequence; restores on completion or 180 seconds.', flush=True)
            result = exercise(io, prepared, root,
                              lambda stopped: observe_sequence(observer, root / 'sequence-report.json', stopped),
                              ready=ready, stopped=stopped)
        print('Native profile test:', result['status'], flush=True)
        for field in ('experiment_error', 'recovery_error'):
            if result.get(field): print(result[field], flush=True)
        return 0 if result['status'] == 'native-profile-test-restored' else 1
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
