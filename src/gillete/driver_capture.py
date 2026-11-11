"""Explicit temporary mode test. Capture only the selected mouse, never keyboards.

This is a diagnostic tool, not the live remapper: no evdev grabs, uinput devices,
onboard binding writes, or input-remapper changes occur here.
"""

import argparse
import fcntl
import os
from pathlib import Path
import select
import signal
import struct
import time

from .devices import discover
from .driver_mode import ModeLease
from .hardware import read_records, transport
from .onboard import durable_json
from .protocol import ProtocolError


def capture(device, journal: Path, output: Path, seconds: int, *, open_transport=None,
            stopped=lambda: False, max_records=20000):
    if journal.exists() or output.exists():
        raise ProtocolError('Choose new journal and capture paths')
    if not 1 <= seconds <= 600:
        raise ValueError('Capture duration must be 1..600 seconds')
    if type(max_records) is not int or not 1 <= max_records <= 20000:
        raise ValueError('Capture record limit must be 1..20000')
    records, descriptors, opened = [], {}, []
    baseline = None
    with (open_transport or transport)(device) as io:
        io.require_normal_mode()
        baseline = read_records(io, device.model, 1)
        fd_interfaces = {}
        try:
            for node in device.interfaces:
                if node['kind'] != 'hidraw' or node['number'] not in ('00', '01', '02'):
                    continue
                fd = os.open(node['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
                opened.append(fd)
                info = bytearray(8)
                fcntl.ioctl(fd, 0x80084803, info, True)
                if struct.unpack('IHH', info) != (3, 0x1532, device.product_id):
                    raise ProtocolError('Capture interface identity changed')
                fd_interfaces[fd] = node['number']
                descriptor = Path('/sys/class/hidraw') / Path(node['path']).name / 'device/report_descriptor'
                descriptors[node['number']] = descriptor.read_bytes().hex()
            if set(fd_interfaces.values()) != {'00', '01', '02'} or len(fd_interfaces) != 3:
                raise ProtocolError('Expected one input HID per interface 00, 01 and 02')
            with ModeLease(io, journal):
                # Discard pre-transition reports before announcing the capture.
                for fd in fd_interfaces:
                    while True:
                        try:
                            if not os.read(fd, 4096):
                                raise OSError('Mouse disconnected')
                        except BlockingIOError:
                            break
                start = time.monotonic()
                print('READY: temporary driver mode verified. Capture is active; stored bindings are unchanged.', flush=True)
                previous = {}
                while time.monotonic() - start < seconds and not stopped():
                    for fd in select.select(list(fd_interfaces), [], [], 0.25)[0]:
                        raw = os.read(fd, 4096)
                        if not raw:
                            raise OSError('Mouse disconnected during capture')
                        interface = fd_interfaces[fd]
                        # Retain button/wheel changes, not high-rate pointer motion.
                        signature = raw[:4] if interface == '00' and len(raw) == 8 else raw
                        if previous.get(interface) == signature:
                            continue
                        previous[interface] = signature
                        record = {'t': round(time.monotonic() - start, 6), 'interface': interface, 'raw': raw.hex()}
                        if len(records) >= max_records:
                            raise ProtocolError('Capture limit reached')
                        records.append(record)
                        print(f"HID {interface}: {signature.hex()}", flush=True)
            after = read_records(io, device.model, 1)
            if after != baseline:
                raise ProtocolError('Stored descriptors differ after the mode test; comparison retained')
            print('RESTORED: normal mode and all bank-1 binding descriptors verified unchanged.', flush=True)
        finally:
            for fd in opened:
                os.close(fd)
            durable_json(output, {'version': 1, 'product': device.product_id, 'descriptors': descriptors,
                                  'events': records, 'mode_journal': str(journal),
                                  'bindings_before': [{**w.json(), 'raw': raw.hex()} for w, raw in baseline.items()]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', required=True, type=lambda value: int(value, 16), choices=(0xB4, 0xE8))
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    devices = [d for d in discover() if d.product_id == args.product]
    if len(devices) != 1:
        parser.error('Connect exactly one mouse of the requested model')
    capture(devices[0], args.journal, args.output, args.seconds)


if __name__ == '__main__':
    main()
