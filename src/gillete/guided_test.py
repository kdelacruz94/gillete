"""Explicit one-button V3 receiver test; restores in finally, with durable journal.

Run only when the user is ready to press/release side button 12. Does not grab
input or change a device mode. No firmware commands beyond binding read/write.
"""

import argparse
import json
import os
from pathlib import Path
import select
import signal
import time

from evdev import InputDevice, ecodes

from .devices import discover
from .hid import BindingHID, CONFIG_INTERFACE
from .onboard import Location, Programmer
from .protocol import Command, ProtocolError
from .raw_keyboard import keyboard_usages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--standalone", action="store_true", help="Also test shifted F23 after a user-reported power cycle")
    parser.add_argument("--product", choices=("00e8", "00b4"), default="00e8")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        raise ValueError("Test duration must be 1..300 seconds")
    product = int(args.product, 16)
    label = "V3" if product == 0x00E8 else "V2"
    devices = [d for d in discover() if d.product_id == product]
    if len(devices) != 1:
        raise ProtocolError(f"Connect exactly one {label} receiver")
    device = devices[0]
    path = next(i["path"] for i in device.interfaces
                if i["kind"] == "hidraw" and i["number"] == CONFIG_INTERFACE[device.product_id])
    sources = []
    raw_sources = {}
    previous_handler = signal.getsignal(signal.SIGTERM)
    def terminate(*_):
        raise KeyboardInterrupt("Test terminated; restoring original assignment")
    signal.signal(signal.SIGTERM, terminate)
    try:
        for interface in device.interfaces:
            if product == 0x00B4 and interface["kind"] == "hidraw" and interface["number"] in {"01", "02"}:
                descriptor = (Path("/sys/class/hidraw") / Path(interface["path"]).name / "device/report_descriptor").read_bytes()
                expected = 314 if interface["number"] == "01" else 61
                if len(descriptor) != expected:
                    raise ProtocolError("Keyboard descriptor differs from the observed layout")
                fd = os.open(interface["path"], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                raw_sources[fd] = {"numbered": interface["number"] == "01", "held": frozenset()}
                continue
            if product == 0x00B4:
                continue
            if interface["kind"] == "input":
                source = InputDevice(interface["path"])
                if ecodes.KEY_F24 in source.capabilities().get(ecodes.EV_KEY, []):
                    sources.append(source)
                else:
                    source.close()
        if not sources and not raw_sources:
            raise ProtocolError("No readable keyboard input interface")
        with BindingHID(path, device.product_id) as hid:
            control_count = 33 if product == 0x00E8 else 21
            inventory = hid.execute(Command(2, 0x84, bytes(control_count + 1)))
            if inventory[0] != control_count or len(set(inventory[1:])) != control_count:
                raise ProtocolError("Control inventory changed")
            programmer = Programmer(hid, args.journal, hid.device_serial(), set(inventory[1:]))
            control = 0x4B
            active_before = hid.read_binding(0, control, 0)
            original = hid.read_binding(1, control, 0)
            if active_before != original:
                raise ProtocolError("Bank 1 is not mirrored by active state; no write performed")
            f24 = bytes.fromhex("02020073000000")
            targets = {Location(1, control, 0): f24}
            active_values = {0: active_before}
            if args.standalone:
                # Existing firmware HyperShift function; do not alter the trigger.
                trigger = 0x39 if product == 0x00E8 else 0x0B
                if hid.read_binding(1, trigger, 0)[0] != 0x0C:
                    raise ProtocolError("Expected native HyperShift trigger is not configured")
                active_values[1] = hid.read_binding(0, control, 1)
                if active_values[1] != hid.read_binding(1, control, 1):
                    raise ProtocolError("Shifted active/stored banks differ; no write performed")
                targets[Location(1, control, 1)] = bytes.fromhex("02020072000000")
            print("PREPARED: side 12, bank 1, normal layer -> F24; original retained in journal", flush=True)
            applied = False
            try:
                programmer.apply(targets)
                applied = True
                for where, function in targets.items():
                    if hid.read_binding(0, control, where.layer) != function:
                        raise ProtocolError("Stored assignment changed but active view did not; restoring")
                if args.standalone:
                    trigger_name = "ring-finger" if product == 0x00E8 else "front index-finger/DPI-up"
                    print(f"READY: switch {label} OFF then ON; press/release side12; then hold {trigger_name} HyperShift and press/release side12", flush=True)
                else:
                    print(f"READY: press and release {label} side button 12 once now", flush=True)
                deadline = time.monotonic() + args.seconds
                required = {ecodes.KEY_F24, ecodes.KEY_F23} if args.standalone else {ecodes.KEY_F24}
                down, up = set(), set()
                while time.monotonic() < deadline and up != required:
                    readable, _, _ = select.select([*sources, *raw_sources], [], [], min(1, max(0, deadline-time.monotonic())))
                    for source in readable:
                        if isinstance(source, int):
                            previous = frozenset().union(*(s["held"] for s in raw_sources.values()))
                            data = os.read(source, 64)
                            if not data:
                                raise ProtocolError("Raw keyboard disconnected")
                            pressed = keyboard_usages(data, numbered=raw_sources[source]["numbered"])
                            if pressed is None:
                                continue
                            raw_sources[source]["held"] = pressed
                            current = frozenset().union(*(s["held"] for s in raw_sources.values()))
                            for usage, code in ((0x73, ecodes.KEY_F24), (0x72, ecodes.KEY_F23)):
                                if code not in required:
                                    continue
                                name = "F24" if code == ecodes.KEY_F24 else "F23"
                                if usage in current and usage not in previous:
                                    down.add(code)
                                    print(f"OBSERVED: {name} key-down from physical {label} HID report", flush=True)
                                elif usage in previous and usage not in current and code in down:
                                    up.add(code)
                                    print(f"OBSERVED: {name} key-up from physical {label} HID report", flush=True)
                            continue
                        for event in source.read():
                            if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                                raise ProtocolError("Input dropped during test")
                            if event.type == ecodes.EV_KEY and event.code in required:
                                name = "F24" if event.code == ecodes.KEY_F24 else "F23"
                                if event.value == 1:
                                    down.add(event.code)
                                    print(f"OBSERVED: {name} key-down from physical {label}", flush=True)
                                elif event.value == 0 and event.code in down:
                                    up.add(event.code)
                                    print(f"OBSERVED: {name} key-up from physical {label}", flush=True)
                print("RESULT: " + ("physical press/release passed" if up == required else "timed out; physical behavior unverified"), flush=True)
                if args.standalone:
                    print("NOTE: power cycle is user-operated; confirm it separately before claiming persistence", flush=True)
            finally:
                if applied:
                    programmer.restore()
                    for layer, original_active in active_values.items():
                        if hid.read_binding(0, control, layer) != original_active:
                            raise ProtocolError("Stored restore verified, but active restore mismatches")
                    print("RESTORED: original stored assignment and active assignment verified", flush=True)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        for source in sources:
            source.close()
        for fd in raw_sources:
            os.close(fd)
        if args.journal.exists() and "SUDO_UID" in os.environ:
            os.chown(args.journal, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))


if __name__ == "__main__":
    main()
