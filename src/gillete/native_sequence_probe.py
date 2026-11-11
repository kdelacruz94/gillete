"""Opt-in chord/count/power-cycle/reuse acceptance with a foreground test pad."""

import argparse
import json
from pathlib import Path
import select
import subprocess
import sys
import time

from evdev import ecodes

from . import dpi_probe as base
from . import native_macro_probe as probe
from . import native_profile_transaction as tx
from .hardware import read_journal
from .model import Action, Layers, Profile, Step
from .native_macro_observer import Observer
from .onboard import durable_json
from .protocol import ProtocolError
from .service import socket_path


NAMES = {'Ctrl': ecodes.KEY_LEFTCTRL, 'K': ecodes.KEY_K, 'M': ecodes.KEY_M, 'F24': ecodes.KEY_F24}
EDGES = [('Ctrl', True), ('K', True), ('K', False), ('Ctrl', False), ('M', True), ('M', False)]
EDGES += [('F24', down) for _ in range(5) for down in (True, False)]
CONTROL_MODIFIER = 0x04000000


def test_profile():
    chord = Action('macro', steps=(Step('down', 'KEY_LEFTCTRL'), Step('wait', milliseconds=20),
        Step('down', 'KEY_K'), Step('wait', milliseconds=40), Step('up', 'KEY_K'),
        Step('wait', milliseconds=20), Step('up', 'KEY_LEFTCTRL'), Step('wait', milliseconds=80),
        Step('down', 'KEY_M'), Step('wait', milliseconds=40), Step('up', 'KEY_M')))
    def key(**kwargs):
        return Action('macro', steps=(Step('down', 'KEY_F24'), Step('wait', milliseconds=40), Step('up', 'KEY_F24')), **kwargs)
    return Profile('native-combined-validation', 'Gillete native combined test',
        Layers(normal={'side_12': chord, 'side_11': key()},
               shifted={'side_12': key(playback='count', count=3, interval_ms=150), 'side_11': key()}))


def validate(prepared):
    preview = tx.validate(prepared)
    if prepared['profile'] != test_profile().json() or prepared['catalog_before']['ids']:
        raise ProtocolError('Expected exact combined native profile and empty initial catalog')
    before = tx.originals(prepared['before'])
    if any(raw[3:] != bytes.fromhex('0c013900000000') for w, raw in before.items() if w.bank == 1 and w.control == 0x39):
        raise ProtocolError('Existing ring-finger HyperShift trigger required')
    changed = {(w.control, w.layer) for w, value in preview.bindings.items() if before[w][3:] != value}
    if changed != {(c, l) for c in (0x4A, 0x4B) for l in (0, 1)} or len(preview.uploads) != 3:
        raise ProtocolError('Combined test must change only four side11/12 mappings and create three objects')
    return preview


class EdgeObserver(Observer):
    def __enter__(self):
        super().__enter__()
        try:
            if not all(set(NAMES.values()) <= set(s.capabilities().get(ecodes.EV_KEY, [])) for s in self.sources):
                raise ProtocolError('Selected V3 keyboard does not expose required test keys')
            return self
        except BaseException:
            self.__exit__()
            raise

    def observe(self, stopped):
        if self.armed_at is None: raise ProtocolError('Native sequence observer was not armed')
        observed, pressed = [], {}
        while time.monotonic() < self.armed_at + 180:
            if stopped(): raise InterruptedError('Native combined test cancelled')
            readable, _, _ = select.select(self.sources, [], [], .2)
            for source in readable:
                for event in source.read():
                    if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                        raise ProtocolError('Dropped keyboard events invalidate native sequence')
                    if event.timestamp() < self.armed_at or event.type != ecodes.EV_KEY: continue
                    if event.code not in NAMES.values():
                        if event.code < ecodes.BTN_MOUSE: raise ProtocolError('Unexpected additional native key event')
                        continue
                    if len(observed) == len(EDGES): raise ProtocolError('Extra native key after expected sequence')
                    name, down = EDGES[len(observed)]
                    if (event.code, event.value) != (NAMES[name], int(down)):
                        raise ProtocolError('Unexpected native chord/count key sequence')
                    if down: pressed[name] = source.fd
                    elif pressed.pop(name, None) != source.fd:
                        raise ProtocolError('Native key release belongs to another interface')
                    observed.append({'key': name, 'down': down, 't': event.timestamp()})
            if len(observed) == len(EDGES): return observed
        raise ProtocolError('Native chord/count observation timed out')

    def assert_quiet(self, stopped):
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            if stopped(): raise InterruptedError('Native quiet-tail observation cancelled')
            readable, _, _ = select.select(self.sources, [], [], .05)
            for source in readable:
                for event in source.read():
                    if (event.type == ecodes.EV_KEY and event.code < ecodes.BTN_MOUSE
                            or event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED):
                        raise ProtocolError('Unexpected native keyboard event after sequence completion')


def validate_edges(events, *, qt=False):
    if not isinstance(events, list) or len(events) != len(EDGES): raise ProtocolError('Incomplete observed native sequence')
    previous = -1
    for e, (key, down) in zip(events, EDGES):
        if (not isinstance(e, dict) or e.get('key') != key or e.get('down') is not down
                or type(e.get('t')) not in (int, float) or not previous <= e['t'] < float('inf')):
            raise ProtocolError('Observed native sequence/timing does not match')
        previous = e['t']
        if qt and (e.get('repeat') is not False or type(e.get('modifiers')) is not int):
            raise ProtocolError('Unexpected desktop repeat/modifier event')
        if qt and down and key == 'K' and e['modifiers'] != CONTROL_MODIFIER:
            raise ProtocolError('Desktop did not receive Ctrl+K')
        if qt and down and key == 'M' and e['modifiers'] != 0:
            raise ProtocolError('Ctrl leaked into the M key')


def setting_count(io):
    value = getattr(io, 'reply_health', {}).get('setting_commands')
    if type(value) is not int: raise ProtocolError('Setting-command telemetry is required for reuse acceptance')
    return value


def recover_all(io, root):
    first, second = root / 'initial/profile.json', root / 'repeat/profile.json'
    if not first.exists(): raise ProtocolError('No initial transaction exists; no profile write was admitted')
    document = read_journal(first)
    secondary_error = None
    if not document.get('original_state_restored') and second.exists():
        try: tx.undo(io, second)
        except (OSError, ValueError) as error: secondary_error = str(error)
    result = tx.undo(io, first)
    return result, secondary_error


def exercise(io, prepared, root, observe, *, ready=lambda: None, stopped=lambda: False):
    preview = validate(prepared)
    path = root / 'experiment.json'
    if path.exists() or (root / 'initial').exists() or (root / 'repeat').exists():
        raise ProtocolError('Fresh combined experiment paths required')
    result = {'version': 1, 'kind': 'native-combined-observation', 'status': 'preparing',
              'original_state_restored': False, 'native_sequence_observed': False}
    durable_json(path, result)
    fatal = None
    try:
        first = tx.apply(io, prepared, root / 'initial/profile.json', stopped=stopped)
        repeated = tx.prepare(io, test_profile())
        repeated_preview = tx.validate(repeated)
        if repeated_preview.uploads or repeated_preview.required_bytes:
            raise ProtocolError('Repeated native profile did not reuse all objects')
        count = setting_count(io)
        tx.apply(io, repeated, root / 'repeat/profile.json', stopped=stopped)
        if setting_count(io) != count: raise ProtocolError('Repeated profile save submitted a setting command')
        result.update(status='awaiting-native-sequence', repeated_save_setting_commands=0,
                      reused_objects=len(repeated_preview.assets))
        durable_json(path, result)
        ready()
        observed = observe(stopped)
        if observed.get('power_cycled') is not True or observed.get('sequence_completed') is not True:
            raise ProtocolError('Explicit power-cycle and sequence confirmations are required')
        validate_edges(observed.get('raw'))
        validate_edges(observed.get('desktop'), qt=True)
        if probe.normalized(probe.snapshot(base.ReadBudget(io, stopped))) != probe.normalized(first['saved_state']):
            raise ProtocolError('Native profile changed after the reported power cycle')
        for asset in preview.assets: tx.verify_asset(io, asset)
        result.update(observation=observed, native_sequence_observed=True)
        events = observed['raw']
        result['timing_ms'] = {'k_hold': (events[2]['t'] - events[1]['t']) * 1000,
                               'm_hold': (events[5]['t'] - events[4]['t']) * 1000,
                               'count_holds': [(events[i + 1]['t'] - events[i]['t']) * 1000 for i in (6, 8, 10)],
                               'count_periods': [(events[i + 2]['t'] - events[i]['t']) * 1000 for i in (6, 8)]}
    except BaseException as error:
        result['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception): fatal = error
    finally:
        try:
            if (root / 'initial/profile.json').exists():
                restored, secondary = recover_all(io, root)
                result['original_state_restored'] = restored['original_state_restored']
                if secondary: result['secondary_recovery_error'] = secondary
            else:
                result['original_state_restored'] = (probe.normalized(probe.snapshot(base.ReadBudget(io)))
                                                      == probe.normalized(prepared['before']))
        except BaseException as error:
            result['recovery_error'] = str(error) or type(error).__name__
            if not isinstance(error, Exception): fatal = error
        result['status'] = ('recovery-required' if not result['original_state_restored'] else
                            'test-failed-restored' if result.get('experiment_error') else 'native-combined-restored')
        durable_json(path, result)
    if fatal: raise fatal
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run', 'recover'))
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    pad = None
    try:
        if socket_path().exists(): raise ProtocolError('Disable Gillete software control first')
        if args.operation == 'prepare':
            if args.directory.exists(): raise ProtocolError('Choose a fresh directory')
            with probe.open_mouse() as io: prepared = tx.prepare(io, test_profile())
            validate(prepared)
            args.directory.mkdir(parents=True, mode=0o700)
            durable_json(args.directory / 'prepared.json', prepared)
            print('Native combined test: prepared-read-only')
            return 0
        root = args.directory / 'run'
        if args.operation == 'recover':
            with probe.open_mouse() as io: result, secondary = recover_all(io, root)
            print('Native combined recovery:', result['status'])
            if secondary: print('Secondary recovery:', secondary)
            return 0
        prepared = read_journal(args.directory / 'prepared.json')
        validate(prepared)
        root.mkdir(mode=0o700)
        pad_file, ready_file = root / 'desktop.json', root / 'ready.json'
        pad = subprocess.Popen([sys.executable, '-m', 'gillete.native_sequence_pad', '--output', str(pad_file), '--ready', str(ready_file)])
        def pad_state(): return read_journal(pad_file) if pad_file.exists() else {}
        with base.cancellation() as cancelled, EdgeObserver(base.connected(0xE8)) as observer, probe.open_mouse() as io:
            bad_reports = []
            def capture(command, report, error):
                if len(bad_reports) >= 16: return
                bad_reports.append({'category': command.category, 'operation': command.operation,
                                    'report': report.hex(), 'error': error})
                durable_json(root / 'malformed-replies.json', {'version': 1, 'reports': bad_reports})
            io.bad_report_observer = capture
            def stopped(): return cancelled() or pad.poll() is not None or pad_state().get('closed', False)
            def ready():
                print('FOCUS: click the Gillete native keyboard sequence test window; READY will follow.', flush=True)
                deadline = time.monotonic() + 60
                while not pad_state().get('active'):
                    if stopped() or time.monotonic() >= deadline: raise ProtocolError('Focus the native test window before testing')
                    time.sleep(.1)
                observer.arm()
                durable_json(ready_file, {'version': 1, 'ready': True})
                while not (pad_state().get('ready') and pad_state().get('active')):
                    if stopped() or time.monotonic() >= deadline: raise ProtocolError('Native test window did not become ready')
                    time.sleep(.1)
                print('READY: off/on V3, click test window, then 12; ring+12; 11; ring+11. Wait one second '
                      'between combinations; confirm off/on and sequence afterward.', flush=True)
            def observe(stopped):
                raw = observer.observe(stopped)
                report = root / 'user-report.json'
                while time.monotonic() < observer.armed_at + 180:
                    if stopped(): raise InterruptedError('Native test window closed or cancelled')
                    if report.exists():
                        with report.open('rb') as handle: data = handle.read(4097)
                        if len(data) > 4096: raise ProtocolError('User report too large')
                        confirmation = json.loads(data)
                        if confirmation != {'power_cycled': True, 'sequence_completed': True} or any(v is not True for v in confirmation.values()):
                            raise ProtocolError('Expected explicit off/on and full sequence confirmation')
                        observer.assert_quiet(stopped)
                        desktop = pad_state()
                        if desktop.get('unexpected_keys'): raise ProtocolError('Additional keys were received by the test window')
                        return {'raw': raw, 'desktop': desktop.get('events'), **confirmation}
                    time.sleep(.1)
                raise ProtocolError('Native combined confirmation timed out')
            result = exercise(io, prepared, root, observe, ready=ready, stopped=stopped)
        print('Native combined test:', result['status'], flush=True)
        for field in ('experiment_error', 'recovery_error'):
            if result.get(field): print(result[field], flush=True)
        return 0 if result['status'] == 'native-combined-restored' else 1
    except (OSError, ValueError) as error: parser.exit(1, f'{error}\n')
    finally:
        if pad is not None and pad.poll() is None:
            pad.terminate()
            try: pad.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pad.kill()
                pad.wait(timeout=3)


if __name__ == '__main__':
    raise SystemExit(main())
