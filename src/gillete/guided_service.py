"""Prepare/review, then run a bounded receiver software acceptance test."""

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


def connected(product):
    matches = [d for d in discover() if d.model == PRODUCT_MODELS[product]]
    if len(matches) != 1 or matches[0].product_id != product:
        raise ValueError('Connect exactly one requested receiver, with its wired transport disconnected')
    return matches[0]


def prepare(product, directory):
    if directory.exists():
        raise ValueError('Choose a new acceptance-test directory')
    if socket_path().exists():
        raise RuntimeError('Stop the existing Gillete service before preparing the isolated test')
    before = inspect(connected(product))
    if any(name not in before.settings for name in SPECS):
        raise RuntimeError('Could not read all saved settings; wake the mouse and prepare again')
    config, overrides = build(before)
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', {'version': 1, 'kind': 'software-acceptance',
                 'snapshot': snapshot_document(before), 'configuration': config.json(), 'overrides': overrides})
    print('PREPARED — read only. Review these temporary software overrides before running:', flush=True)
    for line in describe(overrides):
        print(line, flush=True)
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


def recover_mode(device, before, state):
    for path in sorted(state.glob('mode-*.json')):
        document = read_journal(path)
        if (document.get('serial') == before.serial and document.get('product') == before.product
                and document.get('kind') == 'driver-mode' and document.get('status') != 'normal-mode-restored'):
            with transport(device) as io:
                ModeLease(io, path).restore()


async def cleanup(directory, daemon, pad, config_path, device, before, samples):
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
        await asyncio.to_thread(recover_mode, device, before, directory / 'state/gillete/onboard')
        after = await asyncio.to_thread(inspect, device, before.bank)
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


async def run(directory, seconds):
    if not 30 <= seconds <= 600:
        raise ValueError('Duration must be 30..600 seconds')
    directory = directory.resolve()
    prepared = read_journal(directory / 'prepared.json')
    if prepared.get('kind') != 'software-acceptance':
        raise ValueError('Not a prepared software acceptance test')
    before = load_snapshot(prepared['snapshot'])
    config, overrides = build(before)
    if config.json() != prepared['configuration'] or overrides != prepared['overrides']:
        raise ValueError('Validation plan changed; prepare and review a new test')
    if any(name not in before.settings for name in SPECS):
        raise ValueError('Prepared test lacks original saved settings')
    if socket_path().exists():
        raise RuntimeError('Stop the existing Gillete service before the isolated test')
    device = connected(before.product)
    current = await asyncio.to_thread(inspect, device, before.bank)
    assert_unchanged(before, current)
    # Atomic claim prevents two controllers from sharing a config identity or
    # reusing stale readiness/evidence files after an interrupted run.
    directory = directory / 'run'
    directory.mkdir(mode=0o700)
    config_path = directory / 'profiles.json'
    ready_path = directory / 'ready.json'
    title = 'Gillete input test ' + uuid4().hex[:12]
    pad = daemon = None
    samples = []
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous_handlers:
        loop.add_signal_handler(sig, stop.set)
    try:
        pad = await asyncio.create_subprocess_exec(sys.executable, '-m', 'gillete.validation_pad',
                  '--output', str(directory / 'input.json'), '--seconds', str(seconds),
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
        bind_window(config, before.model, window['class'], title)
        ProfileStore(config_path).save(config, expected_revision=0)
        env = {**os.environ, 'XDG_STATE_HOME': str(directory / 'state')}
        daemon = await asyncio.create_subprocess_exec(sys.executable, '-m', 'gillete.cli',
                         '--config', str(config_path), 'daemon', env=env)

        async def command(name, **kwargs):
            check_running(stop, pad, daemon)
            return await asyncio.wait_for(request(name, config_path=config_path, **kwargs), 5)

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                status = await command('status')
                if status['focus_available'] and status['suspend_monitor'] and not status['suspended']:
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
                    and status['focus']['address'] == window['address']):
                break
            if not state['requested']:
                raise RuntimeError(state['error'] or 'Mouse activation stopped')
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Mouse activation or test-window focus timed out')
        check_running(stop, pad, daemon)
        durable_json(ready_path, {'version': 1, 'model': before.model, 'title': title, 'seconds': seconds})
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
            await asyncio.sleep(.25)
    except TestStopped:
        pass
    finally:
        try:
            await cleanup(directory, daemon, pad, config_path, device, before, samples)
        finally:
            for sig, handler in previous_handlers.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run'))
    parser.add_argument('--product', type=lambda x: int(x, 16), choices=tuple(PRODUCT_MODELS))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 600:
        parser.error('Duration must be 30..600 seconds')
    if args.operation == 'prepare':
        if args.product is None:
            parser.error('--product is required to prepare a check')
        prepare(args.product, args.directory)
    else:
        asyncio.run(run(args.directory, args.seconds))


if __name__ == '__main__':
    main()
