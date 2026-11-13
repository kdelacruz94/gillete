"""Hand the V2 over from input-remapper and back, with a receipt.

Usage: .venv/bin/python tools/remapper_handoff.py state|stop|restore RECEIPT.json

stop: requires a RUNNING V2 preset, records its name and the SHA-256 of
input-remapper's config.json and that preset file, then stops only the V2.
restore: refuses if those files changed, restarts the recorded preset and
waits for RUNNING. Other devices, presets and autoload settings are untouched.
Keep RECEIPT.json under evidence/*.local/ so it survives the session.
"""

from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from inputremapper.configs.paths import PathUtils
from inputremapper.daemon import DAEMON

GROUP = 'Razer Razer Naga V2 HyperSpeed'


def files(preset):
    root = Path(PathUtils.get_config_path())
    return [root / 'config.json', root / 'presets' / PathUtils.sanitize_path_component(GROUP) / (preset + '.json')]


def hashes(preset):
    return {str(p): sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in files(preset)}


def wait(proxy, states, seconds=10):
    deadline = time.monotonic() + seconds
    while proxy.get_state(GROUP) not in states:
        if time.monotonic() > deadline:
            raise RuntimeError(f'input-remapper state stayed {proxy.get_state(GROUP)}')
        time.sleep(.2)


def main(action, receipt_path):
    proxy = DAEMON.get_proxy()
    receipt = Path(receipt_path)
    state, running = proxy.get_state(GROUP), proxy.get_running_preset(GROUP)
    if action == 'state':
        print(json.dumps({'state': state, 'preset': running}))
        return 0
    if action == 'stop':
        if receipt.exists():
            raise SystemExit('Receipt exists; restore or inspect it first')
        if state != 'RUNNING' or not running:
            raise SystemExit(f'Expected a RUNNING V2 preset, found {state}/{running}')
        document = {'preset': running, 'hashes': hashes(running), 'status': 'stop-requested'}
        receipt.write_text(json.dumps(document, indent=2))
        proxy.stop_injecting(GROUP)
        wait(proxy, {'STOPPED', 'NO_GRAB', 'UNKNOWN', 'FAILED'})
        document.update(status='stopped', stopped_state=proxy.get_state(GROUP))
        receipt.write_text(json.dumps(document, indent=2))
        print(f'Stopped V2 preset "{running}" ({document["stopped_state"]}); files fingerprinted.')
        return 0
    if action == 'restore':
        document = json.loads(receipt.read_text())
        preset = document['preset']
        if hashes(preset) != document['hashes']:
            raise SystemExit('Preset/config files changed since the stop; not restarting automatically')
        if state == 'RUNNING' and running == preset:
            print(f'Already RUNNING "{preset}".')
        else:
            if not proxy.start_injecting(GROUP, preset, timeout=10000):
                raise SystemExit('input-remapper rejected the restart')
            wait(proxy, {'RUNNING'})
        assert proxy.get_running_preset(GROUP) == preset
        document.update(status='restored', restored_state=proxy.get_state(GROUP))
        receipt.write_text(json.dumps(document, indent=2))
        print(f'Restored V2 preset "{preset}" RUNNING; files unchanged.')
        return 0
    raise SystemExit('Unknown action')


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
