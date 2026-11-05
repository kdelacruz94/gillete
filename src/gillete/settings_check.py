"""Prepare/review, then explicitly run a bounded reversible settings check."""

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import signal
import sys

from .devices import discover
from .hardware import Snapshot, apply_settings, inspect, read_journal, restore
from .onboard import Location, durable_json
from .protocol import ProtocolError
from .settings import DPI_MAX, SettingsDraft, Stages, decode_dpi, decode_polling, describe, plan


def connected(product):
    devices = [d for d in discover() if d.product_id == product]
    if len(devices) != 1:
        raise ProtocolError('Connect exactly one receiver of the requested model')
    return devices[0]


def test_draft(snapshot):
    """Small DPI change; stage selected independently of record identifiers."""
    current = decode_dpi(bytes.fromhex(snapshot.settings['dpi']), snapshot.product)
    stages = Stages.decode(bytes.fromhex(snapshot.settings['stages']), snapshot.product)
    polling = decode_polling(bytes.fromhex(snapshot.settings['polling']), snapshot.product)
    pair = tuple(v + 100 if v <= DPI_MAX[snapshot.product] - 100 else v - 100 for v in current)
    values = list(stages.values)
    if len(values) == 1:
        values.append(pair)
    active = stages.active % len(values) + 1
    values[active - 1] = pair
    return SettingsDraft(pair, tuple(values), active, 500 if polling == 1000 else 1000)


def snapshot_document(snapshot):
    return {'product': snapshot.product, 'model': snapshot.model, 'serial': snapshot.serial,
            'bank': snapshot.bank, 'assigned': list(snapshot.assigned), 'active': snapshot.active,
            'controls': sorted(snapshot.controls), 'settings': snapshot.settings, 'metadata': snapshot.metadata,
            'records': [{**where.json(), 'raw': raw.hex()} for where, raw in snapshot.records.items()]}


def load_snapshot(document):
    return Snapshot(document['product'], document['model'], document['serial'], document['bank'],
                    tuple(document['assigned']), document['active'], set(document['controls']),
                    {Location(r['bank'], r['control'], r['layer']): bytes.fromhex(r['raw']) for r in document['records']},
                    document['settings'], document.get('metadata', {}))


def prepare(product, directory):
    if directory.exists():
        raise ValueError('Choose a new settings-test directory')
    snapshot = inspect(connected(product))
    draft = test_draft(snapshot)
    proposed = plan(snapshot, draft)
    directory.mkdir(parents=True, mode=0o700)
    durable_json(directory / 'prepared.json', {'version': 1, 'snapshot': snapshot_document(snapshot),
                                              'draft': asdict(draft)})
    print('PREPARED — read only; no settings changed.', flush=True)
    for name, after in proposed.changes.items():
        print(f'{name.title()}: {describe(name, proposed.before[name], product)} → {describe(name, after, product)}', flush=True)
    print(f'Original {len(snapshot.records)} saved button descriptors retained privately in {directory}.', flush=True)


async def inspect_awake(device, bank):
    # A just-powered-on wireless mouse can take a moment to answer. Retrying
    # read-only inspection is safe; setter requests are never blindly resent.
    for attempt in range(6):
        try:
            return await asyncio.to_thread(inspect, device, bank)
        except (OSError, ProtocolError):
            if attempt == 5:
                raise
            await asyncio.sleep(.5)


async def run(directory, seconds):
    prepared = read_journal(directory / 'prepared.json')
    before = load_snapshot(prepared['snapshot'])
    draft = SettingsDraft(**prepared['draft'])
    proposed = plan(before, draft)
    device = connected(before.product)
    path = directory / 'settings.json'
    if path.exists():
        raise ValueError('This settings check has already started; use its recovery journal if necessary')
    pad = None
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    power_cycled = False
    try:
        current = await inspect_awake(device, before.bank)
        if (current.serial != before.serial or current.records != before.records
                or current.active != before.active or current.assigned != before.assigned):
            raise ProtocolError('Mouse identity, profile or bindings changed since test preparation; prepare again')
        if stop.is_set():
            return
        await asyncio.to_thread(apply_settings, device, before, draft, path)
        if stop.is_set():
            return
        pad = await asyncio.create_subprocess_exec(sys.executable, '-m', 'gillete.settings_check', 'pad',
                                                   '--directory', str(directory), '--seconds', str(seconds))
        for _ in range(40):
            if (directory / 'pad-ready.json').exists():
                break
            if pad.returncode is not None:
                raise RuntimeError('Settings test window exited before becoming ready')
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Settings test window did not become ready')
        print('READY: temporary DPI/stage/polling values verified. Power-cycle this mouse, move it to wake it, '
              'then click “I power-cycled the mouse” in the test window.', flush=True)
        waiters = [asyncio.create_task(pad.wait()), asyncio.create_task(stop.wait())]
        try:
            await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
        response = directory / 'action.json'
        if not stop.is_set() and response.exists() and read_journal(response).get('action') == 'power-cycled':
            after = await inspect_awake(device, before.bank)
            if after.serial != before.serial or after.records != before.records:
                raise ProtocolError('Mouse identity or saved bindings differ after power cycle')
            if {name: bytes.fromhex(after.settings[name]) for name in proposed.after} != proposed.after:
                raise ProtocolError('Settings did not match after the reported power cycle')
            power_cycled = True
            document = read_journal(path)
            document['power_cycle_verified'] = True
            durable_json(path, document)
            print('VERIFIED: all proposed settings survived the reported power cycle.', flush=True)
    finally:
        if pad is not None and pad.returncode is None:
            pad.terminate()
            await pad.wait()
        if path.exists():
            await asyncio.to_thread(restore, device, path)
            after = await inspect_awake(device, before.bank)
            same_settings = all(after.settings.get(name) == value for name, value in before.settings.items() if not name.endswith('_error'))
            if after.serial != before.serial or after.records != before.records or not same_settings:
                raise ProtocolError(f'Restoration comparison failed; retain recovery journal {path}')
            durable_json(directory / 'result.json', {'version': 1, 'power_cycle_verified': power_cycled,
                                                     'original_settings_restored': True,
                                                     'normal_mode_verified': True,
                                                     'saved_bindings_unchanged': len(after.records)})
            print(f'RESTORED: original settings, normal mode and all {len(after.records)} saved bindings verified.', flush=True)


def pad(directory, seconds):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
    import shiboken6
    prepared = read_journal(directory / 'prepared.json')
    before = load_snapshot(prepared['snapshot'])
    proposed = plan(before, SettingsDraft(**prepared['draft']))
    app = QApplication([])
    app.setDesktopFileName('org.gillete.SettingsCheck')
    window = QWidget()
    model_name = 'Naga V2 HyperSpeed' if before.product == 0xB4 else 'Naga V3 Pro'
    window.setWindowTitle('Gillete settings check — ' + model_name)
    window.resize(680, 350)
    layout = QVBoxLayout(window)
    text = [model_name, 'Wait for READY in chat. Then switch this mouse off and back to 2.4 GHz.',
            'Move it to wake it, then click the verification button below.', '',
            'Temporary settings:']
    text += [f'{name.title()}: {describe(name, value, before.product)}' for name, value in proposed.changes.items()]
    text += ['', 'Closing this window or reaching the time limit restores the original settings.']
    label = QLabel('\n'.join(text))
    label.setWordWrap(True)
    layout.addWidget(label)
    verify = QPushButton('I power-cycled the mouse — verify and restore')
    def verify_clicked():
        durable_json(directory / 'action.json', {'version': 1, 'action': 'power-cycled'})
        window.close()
    verify.clicked.connect(verify_clicked)
    layout.addWidget(verify)
    finish = QPushButton('Restore now without a persistence test')
    finish.clicked.connect(window.close)
    layout.addWidget(finish)
    window.show()
    QTimer.singleShot(0, lambda: durable_json(directory / 'pad-ready.json', {'version': 1}))
    QTimer.singleShot(seconds * 1000, window.close)
    try:
        return app.exec()
    finally:
        shiboken6.delete(window)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run', 'pad'))
    parser.add_argument('--product', type=lambda x: int(x, 16), choices=(0xB4, 0xE8))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 300:
        parser.error('Duration must be 30..300 seconds')
    if args.operation == 'prepare':
        if args.product is None:
            parser.error('--product is required to prepare a check')
        prepare(args.product, args.directory)
    elif args.operation == 'run':
        asyncio.run(run(args.directory, args.seconds))
    else:
        pad(args.directory, args.seconds)


if __name__ == '__main__':
    main()
