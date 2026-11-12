"""Prepare/review, then run a bounded software acceptance test."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4

from .devices import discover
from .driver_mode import ModeLease
from .hardware import inspect, load_snapshot, read_journal, snapshot_document, transport
from .onboard import durable_json
from .profiles import ProfileStore
from .service import request, socket_path
from .settings import SPECS
from .validation_plan import PRODUCT_MODELS, assert_unchanged, bind_window, build, describe
from . import control_validation


class Hardware:
    """Default receiver adapter; experiments supply their own guarded adapter."""
    def connected(self, product): return connected(product)
    def inspect(self, device, bank=None): return inspect(device, bank) if bank is not None else inspect(device)
    def transport(self, device): return transport(device)
    def daemon_command(self, config_path, suite):
        return [sys.executable, '-m', 'gillete.cli', '--config', str(config_path), 'daemon',
                *(['--trace-controls'] if suite == 'controls' else [])]


def plan(snapshot, suite):
    if suite == 'examples': return build(snapshot)
    if suite == 'controls': return control_validation.build(snapshot)
    raise ValueError('Unknown software acceptance suite')


def connected(product):
    matches = [d for d in discover() if d.model == PRODUCT_MODELS[product]]
    if len(matches) != 1 or matches[0].product_id != product:
        raise ValueError('Connect exactly one requested receiver, with its wired transport disconnected')
    return matches[0]


def prepare(product, directory, *, suite='examples', hardware=None):
    hardware = hardware or Hardware()
    if suite not in ('examples', 'controls'):
        raise ValueError('Unknown software acceptance suite')
    if directory.exists():
        raise ValueError('Choose a new acceptance-test directory')
    if socket_path().exists():
        raise RuntimeError('Stop the existing Gillete service before preparing the isolated test')
    before = hardware.inspect(hardware.connected(product))
    if any(name not in before.settings for name in SPECS):
        raise RuntimeError('Could not read all saved settings; wake the mouse and prepare again')
    config, overrides = plan(before, suite)
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', {'version': 1, 'kind': 'software-acceptance',
                 'snapshot': snapshot_document(before), 'configuration': config.json(), 'overrides': overrides,
                 'suite': suite, **({'coverage': control_validation.recipe(before.model)} if suite == 'controls' else {})})
    print('PREPARED — read only. Review these temporary software overrides before running:', flush=True)
    for line in (control_validation.describe(overrides) if suite == 'controls' else describe(overrides)):
        print(line, flush=True)
    if suite == 'controls':
        print(f'{len(control_validation.recipe(before.model)["steps"])} control/layer taps; '
              'a second software HyperShift trigger allows testing the first trigger itself. '
              'F13–F24 plus Shift/Ctrl/Alt are temporary markers; compositor shortcuts may receive them. '
              'The isolated service exposes bounded mouse-control edges, not keyboard input or pointer coordinates. '
              'Escape closes the pad and restores mode; no live test has started.', flush=True)
    print(f'Original {len(before.records)} saved descriptors retained privately in {directory}.', flush=True)


async def stop_process(process, grace=0):
    """Reap only a child owned by this controller, with bounded escalation."""
    if process is None or process.returncode is not None:
        return False
    if grace:
        try:
            await asyncio.wait_for(process.wait(), grace)
            return False
        except asyncio.TimeoutError:
            pass
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), 5)
        return False
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await asyncio.wait_for(process.wait(), 5)
        return True


async def clients():
    process = await asyncio.create_subprocess_exec('hyprctl', '-j', 'clients',
                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        raw, _ = await asyncio.wait_for(process.communicate(), 3)
        if process.returncode:
            raise RuntimeError('Hyprland window query failed')
        return json.loads(raw)
    finally:
        await stop_process(process)


class TestStopped(RuntimeError):
    pass


def check_running(stop, pad, daemon=None):
    if stop.is_set() or pad.returncode is not None:
        raise TestStopped('Software test stopped')
    if daemon is not None and daemon.returncode is not None:
        raise RuntimeError('Acceptance service exited')


def control_packet(status, model, device, nonce, address):
    state = status['devices'][model]
    trace = state.get('input_trace')
    if not isinstance(trace, dict):
        raise RuntimeError('The acceptance service did not supply mouse-control evidence')
    if state.get('transport') != {'product': device.product_id, 'usb_path': device.usb_path,
                                  'transport': device.transport}:
        raise RuntimeError('The acceptance service selected another mouse transport')
    if trace.get('profile') != state['profile']:
        raise RuntimeError('The acceptance service returned conflicting mapping context')
    packet = {'version': 1, 'model': model, 'nonce': nonce, 't': trace.get('t'),
        'active': state['active'], 'focused': status['focus']['address'] == address,
        'focus_pending': bool(status.get('focus_pending')), 'trace': trace}
    control_validation.validate_packet(packet)
    return packet


def recover_mode(device, before, state, *, hardware=None):
    hardware = hardware or Hardware()
    for path in sorted(state.glob('mode-*.json')):
        document = read_journal(path)
        if (document.get('serial') == before.serial and document.get('product') == before.product
                and document.get('kind') == 'driver-mode' and document.get('status') != 'normal-mode-restored'):
            with hardware.transport(device) as io:
                ModeLease(io, path).restore()


async def cleanup(directory, daemon, pad, config_path, device, before, samples, *, hardware=None):
    """Restoration must run even when a process or evidence write fails."""
    notes, errors = [], []
    if daemon is not None and daemon.returncode is None:
        try:
            await asyncio.wait_for(request('shutdown', config_path=config_path), 5)
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError):
            notes.append('Service control unavailable during shutdown')
    for process, grace in ((daemon, 20), (pad, 0)):
        try:
            if await stop_process(process, grace):
                notes.append('An owned child required a forced stop')
        except Exception as error:
            errors.append(f'Child shutdown failed: {error}')
    # Never restore mode while an owned daemon might still be using the mouse.
    restored = False
    try:
        if daemon is not None and daemon.returncode is None:
            raise RuntimeError('Service is still alive; retain the mode recovery journal')
        await asyncio.to_thread(recover_mode, device, before, directory / 'state/gillete/onboard', hardware=hardware)
        after = await asyncio.to_thread((hardware or Hardware()).inspect, device, before.bank)
        assert_unchanged(before, after)
        restored = True
    except Exception as error:
        errors.append(f'Restoration verification failed: {error}')
    reports = {'service.json': {'version': 1, 'samples': samples, 'shutdown_notes': notes},
               'restoration.json': {'version': 1, 'normal_mode_verified': restored,
                                    'stored_state_unchanged': restored,
                                    'descriptor_count': len(before.records), 'errors': list(errors)}}
    for name, report in reports.items():
        try:
            durable_json(directory / name, report)
        except Exception as error:
            errors.append(f'Could not save {name}: {error}')
    if restored:
        print(f'RESTORED: normal mode, all {len(before.records)} original saved descriptors, '
              'profile selection and saved settings verified.', flush=True)
    if errors:
        raise RuntimeError('; '.join(errors) + f'. Retain test data in {directory}')


async def run(directory, seconds, *, hardware=None):
    hardware = hardware or Hardware()
    if not 30 <= seconds <= 600:
        raise ValueError('Duration must be 30..600 seconds')
    directory = directory.resolve()
    prepared = read_journal(directory / 'prepared.json')
    if prepared.get('kind') != 'software-acceptance':
        raise ValueError('Not a prepared software acceptance test')
    before = load_snapshot(prepared['snapshot'])
    suite = prepared.get('suite', 'examples')
    config, overrides = plan(before, suite)
    if config.json() != prepared['configuration'] or overrides != prepared['overrides']:
        raise ValueError('Validation plan changed; prepare and review a new test')
    if suite == 'controls' and prepared.get('coverage') != control_validation.recipe(before.model):
        raise ValueError('Control coverage recipe changed; prepare and review a new test')
    if any(name not in before.settings for name in SPECS):
        raise ValueError('Prepared test lacks original saved settings')
    if socket_path().exists():
        raise RuntimeError('Stop the existing Gillete service before the isolated test')
    device = hardware.connected(before.product)
    current = await asyncio.to_thread(hardware.inspect, device, before.bank)
    assert_unchanged(before, current)
    # Atomic claim prevents two controllers from sharing a config identity or
    # reusing stale readiness/evidence files after an interrupted run.
    directory = directory / 'run'
    directory.mkdir(mode=0o700)
    config_path = directory / 'profiles.json'
    ready_path = directory / 'ready.json'
    title = 'Gillete input test ' + uuid4().hex[:12]
    nonce = uuid4().hex
    pad = daemon = None
    samples = []
    coverage_complete = False
    coverage_epoch = None
    coverage_started_at = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous_handlers:
        loop.add_signal_handler(sig, stop.set)
    try:
        pad_args = ([sys.executable, '-m', 'gillete.control_pad',
                     '--output', str(directory / 'coverage.json'), '--state', str(directory / 'control-state.json'),
                     '--nonce', nonce] if suite == 'controls' else
                    [sys.executable, '-m', 'gillete.validation_pad', '--output', str(directory / 'input.json')])
        pad = await asyncio.create_subprocess_exec(*pad_args, '--seconds', str(seconds),
                  '--model', before.model, '--title', title, '--ready', str(ready_path))
        deadline = time.monotonic() + 15
        window = None
        while time.monotonic() < deadline:
            check_running(stop, pad)
            matches = [c for c in await clients() if c.get('pid') == pad.pid and c.get('title') == title]
            if len(matches) == 1:
                window = matches[0]
                break
            await asyncio.sleep(.1)
        if not window:
            raise RuntimeError('Could not identify the test window in Hyprland')
        check_running(stop, pad)
        (control_validation.bind_window if suite == 'controls' else bind_window)(
            config, before.model, window['class'], title)
        ProfileStore(config_path).save(config, expected_revision=0)
        env = {**os.environ, 'XDG_STATE_HOME': str(directory / 'state')}
        daemon = await asyncio.create_subprocess_exec(*hardware.daemon_command(config_path, suite), env=env)

        async def command(name, **kwargs):
            check_running(stop, pad, daemon)
            return await asyncio.wait_for(request(name, config_path=config_path, **kwargs), 5)

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                status = await command('status')
                if (status['focus_available'] and not status.get('focus_pending')
                        and status['suspend_monitor'] and not status['suspended']):
                    break
            except OSError:
                pass
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Focus/suspend monitoring did not become ready')
        await command('enable', model=before.model)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = await command('status')
            state = status['devices'][before.model]
            if (state['active'] and state['profile'] == 'validation'
                    and not status.get('focus_pending') and status['focus']['address'] == window['address']):
                break
            if not state['requested']:
                raise RuntimeError(state['error'] or 'Mouse activation stopped')
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Mouse activation or test-window focus timed out')
        check_running(stop, pad, daemon)
        if suite == 'controls':
            packet = control_packet(status, before.model, device, nonce, window['address'])
            coverage_epoch = packet['trace']['epoch']
            durable_json(directory / 'control-state.json', packet)
            coverage_started_at = time.monotonic()
        durable_json(ready_path, {'version': 1, 'model': before.model, 'title': title, 'seconds': seconds,
                                  **({'nonce': nonce} if suite == 'controls' else {})})
        print('READY: software control active in the focused test window. '
              'Emergency stop: Ctrl+Alt+Pause.', flush=True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            status = await command('status')
            state = status['devices'][before.model]
            samples.append({'t': time.monotonic(), 'active': state['active'], 'profile': state['profile'],
                            'active_macros': state['active_macros'], 'error': state['error']})
            if not state['active']:
                raise RuntimeError(state['error'] or 'Service stopped')
            if suite == 'controls':
                packet = control_packet(status, before.model, device, nonce, window['address'])
                if packet['trace']['epoch'] != coverage_epoch:
                    raise RuntimeError('The acceptance mouse session restarted; retain this incomplete test')
                durable_json(directory / 'control-state.json', packet)
                try:
                    result = read_journal(directory / 'coverage.json')
                except FileNotFoundError:
                    result = None
                if result is not None and result.get('status') == 'complete':
                    control_validation.validate_results(result, before.model, nonce, epoch=coverage_epoch,
                        started_at=coverage_started_at, finished_by=time.monotonic())
                    coverage_complete = True
                    break
            await asyncio.sleep(.25)
    except TestStopped:
        pass
    finally:
        try:
            await cleanup(directory, daemon, pad, config_path, device, before, samples, hardware=hardware)
        finally:
            for sig, handler in previous_handlers.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, handler)
    if suite == 'controls':
        if not coverage_complete:
            try:
                result = read_journal(directory / 'coverage.json')
            except FileNotFoundError:
                result = None
            if result is not None and result.get('status') == 'complete':
                control_validation.validate_results(result, before.model, nonce, epoch=coverage_epoch,
                    started_at=coverage_started_at, finished_by=time.monotonic())
                coverage_complete = True
        if not coverage_complete:
            raise RuntimeError(f'Control coverage is incomplete; retain observations and restoration receipts in {directory}')
        print(f'CONTROL COVERAGE VERIFIED: {len(control_validation.recipe(before.model)["steps"])} '
              'control/layer pairs with mouse edges and desktop key pairs. Native saves and wider lifecycle acceptance remain separate.', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run'))
    parser.add_argument('--product', type=lambda x: int(x, 16), choices=(0xB4, 0xE8))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--suite', choices=('examples', 'controls'), help='Select the plan when preparing; default examples')
    args = parser.parse_args(argv)
    if not 30 <= args.seconds <= 600:
        parser.error('Duration must be 30..600 seconds')
    if args.operation == 'prepare':
        if args.product is None:
            parser.error('--product is required to prepare a check')
        prepare(args.product, args.directory, suite=args.suite or 'examples')
    else:
        if args.suite is not None:
            parser.error('Choose --suite during prepare; run uses the reviewed saved plan')
        asyncio.run(run(args.directory, args.seconds))


if __name__ == '__main__':
    main()
