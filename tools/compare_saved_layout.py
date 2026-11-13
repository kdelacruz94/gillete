"""Read-only check that connected mice still hold their reviewed saved layouts.

Usage: .venv/bin/python tools/compare_saved_layout.py REFERENCE.json [REFERENCE.json ...]

Each REFERENCE is a JSON document whose "snapshot" key holds an earlier
hardware snapshot (for example an evidence/*.local/prepared.json). Every
connected supported mouse is read with the same getter-only path the service
uses (no setters, no mode change) and compared row by row with the reference
for its USB product. Serials are compared, never printed. Run it with Gillete's
service stopped or with that mouse's software control disabled; the service
owns the HID transport while a mouse is active. Exit status 1 means a
difference, a missing reference or a failed read.
"""

import json
import sys

from gillete import wired_backend
from gillete.devices import discover
from gillete.hardware import inspect, load_snapshot


def main(paths):
    references = {}
    for path in paths:
        snapshot = load_snapshot(json.load(open(path))['snapshot'])
        references[snapshot.product] = snapshot
    status = 0
    for device in discover():
        reference = references.get(device.product_id)
        if reference is None:
            print(f'{device.model} {device.product_id:04x}: no reference given')
            status = 1
            continue
        reader = wired_backend.inspect_device if device.product_id == 0xE7 else inspect
        try:
            live = reader(device)
        except Exception as error:  # report it; never retry through a write path
            print(f'{device.model} {device.product_id:04x}: read failed: {type(error).__name__}: {error}')
            status = 1
            continue
        changed = sorted(f'{where.control:02x}/{where.layer}' for where, raw in live.records.items()
                         if reference.records.get(where) is None or reference.records[where][3:] != raw[3:])
        same_mouse = live.serial == reference.serial
        print(f'{device.model} {device.product_id:04x}: same mouse={same_mouse} slot={live.bank} '
              f'assigned={live.assigned} rows={len(live.records)} changed={changed or "none"} '
              f'dpi={live.settings.get("dpi")} (reference {reference.settings.get("dpi")}) '
              f'firmware={live.metadata.get("firmware")}')
        status |= bool(changed) or not same_mouse
    return status


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1:]))
