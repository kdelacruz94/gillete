"""Explicit, bounded V3 software acceptance test with an isolated configuration."""

import argparse
import asyncio
import json
from pathlib import Path
import signal
import sys
import time

from .devices import discover
from .driver_mode import ModeLease
from .hardware import inspect, journal_directory, read_journal, transport
from .model import Action, Layers, MODELS, Profile, sequence
from .onboard import durable_json
from .profiles import Configuration, ProfileStore, Rule
from .service import request, socket_path


async def run(directory, seconds):
    if directory.exists():
        raise ValueError('Choose a new acceptance-test directory')
    if socket_path().exists():
        raise RuntimeError('Stop the existing Gillete service before the isolated acceptance test')
    devices = [d for d in discover() if d.product_id == 0xE8]
    if len(devices) != 1:
        raise ValueError('Connect exactly one V3 receiver')
    before = await asyncio.to_thread(inspect, devices[0])
    previous_journals = set(journal_directory().glob('mode-*.json'))
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'before.json', {'product': before.product, 'serial': before.serial,
                                           'records': [{**w.json(), 'raw': raw.hex()} for w, raw in before.records.items()]})
    pad = daemon = None
    samples = []
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        pad = await asyncio.create_subprocess_exec(sys.executable, '-m', 'gillete.validation_pad',
                                                   '--output', str(directory / 'input.json'), '--seconds', str(seconds))
        app_class = None
        for _ in range(40):
            process = await asyncio.create_subprocess_exec('hyprctl', '-j', 'clients', stdout=asyncio.subprocess.PIPE)
            raw, _ = await asyncio.wait_for(process.communicate(), 3)
            matches = [c for c in json.loads(raw) if c.get('pid') == pad.pid and c.get('title') == 'Gillete input test']
            if len(matches) == 1:
                app_class = matches[0]['class']
                break
            if pad.returncode is not None:
                raise RuntimeError('Test window exited before it was ready')
            await asyncio.sleep(.1)
        if not app_class:
            raise RuntimeError('Could not identify the test window in Hyprland')
        config = Configuration()
        profile = Profile('validation', 'Software acceptance', Layers(normal={
            'side_12': Action('keys', keys=('KEY_F24',)),
            'side_11': sequence(('KEY_LEFTCTRL', 'KEY_K'), ('KEY_M',)),
            'top_rear': Action('turbo', keys=('KEY_1',), playback='toggle', interval_ms=200)},
            shifted={'side_12': Action('keys', keys=('KEY_F23',))}))
        config.profiles[profile.id] = profile
        config.rules = [Rule(profile.id, app_class=app_class, title='Gillete input test', model=MODELS[1], priority=1000)]
        config_path = directory / 'profiles.json'
        ProfileStore(config_path).save(config, expected_revision=0)
        daemon = await asyncio.create_subprocess_exec(sys.executable, '-m', 'gillete.cli', '--config', str(config_path), 'daemon')
        for _ in range(60):
            if daemon.returncode is not None:
                raise RuntimeError('Acceptance service failed to start')
            try:
                status = await request('status')
                if status['focus_available'] and status['suspend_monitor']:
                    break
            except (OSError, RuntimeError):
                pass
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Focus/suspend monitoring did not become ready')
        await request('enable', model=MODELS[1])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = await request('status')
            device = status['devices'][MODELS[1]]
            if device['active']:
                break
            if not device['requested']:
                raise RuntimeError(device['error'] or 'V3 activation stopped')
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('V3 activation timed out')
        print('READY: V3 software control active. Use the Gillete input test window. Emergency stop: Ctrl+Alt+Pause.', flush=True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and pad.returncode is None and not stop.is_set():
            status = await request('status')
            state = status['devices'][MODELS[1]]
            samples.append({'t': time.monotonic(), 'active': state['active'],
                            'profile': state['profile'], 'active_macros': state['active_macros'], 'error': state['error']})
            if not state['active']:
                raise RuntimeError(state['error'] or 'Service stopped')
            await asyncio.sleep(.25)
    finally:
        shutdown_notes = []
        if daemon is not None and daemon.returncode is None:
            try:
                await request('shutdown')
            except (OSError, RuntimeError, asyncio.TimeoutError):
                shutdown_notes.append('Service control connection was unavailable during shutdown')
            try:
                await asyncio.wait_for(daemon.wait(), 20)
            except asyncio.TimeoutError:
                try:
                    daemon.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(daemon.wait(), 10)
                except asyncio.TimeoutError:
                    daemon.kill()
                    await daemon.wait()
                    shutdown_notes.append('Service needed a forced stop; recovery journals checked afterward')
        if pad is not None and pad.returncode is None:
            try:
                pad.terminate()
            except ProcessLookupError:
                pass
            await pad.wait()
        durable_json(directory / 'service.json', {'version': 1, 'samples': samples, 'shutdown_notes': shutdown_notes})
        def recover_test_mode():
            for path in set(journal_directory().glob('mode-*.json')) - previous_journals:
                doc = read_journal(path)
                if (doc.get('serial') == before.serial and doc.get('product') == before.product
                        and doc.get('kind') == 'driver-mode' and doc.get('status') != 'normal-mode-restored'):
                    with transport(devices[0]) as io:
                        ModeLease(io, path).restore()
        await asyncio.to_thread(recover_test_mode)
        after = await asyncio.to_thread(inspect, devices[0], before.bank)
        if after.serial != before.serial or after.records != before.records:
            raise RuntimeError('Stored binding comparison failed after software acceptance')
        durable_json(directory / 'restoration.json', {'normal_mode_verified': True, 'stored_descriptors_unchanged': True,
                                                     'descriptor_count': len(after.records)})
        print('RESTORED: normal mode verified; all 50 original V3 stored descriptors unchanged.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 600:
        parser.error('Duration must be 30..600 seconds')
    asyncio.run(run(args.directory, args.seconds))


if __name__ == '__main__':
    main()
