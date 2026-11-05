"""Linux hidraw feature-report transport, initially restricted to read commands.

GET-style Razer queries still require HID SET_REPORT to submit the query packet.
This transport rejects setting commands; opening it never detaches a driver,
grabs input, or changes device mode. Requires access to the chosen hidraw node.
"""

import fcntl
import os
from pathlib import Path
import struct
import time

from .protocol import Command, DeviceStatusError, ProtocolError

CONFIG_INTERFACE = {0x00B4: "00", 0x00E8: "03"}  # Observed on the user's receivers.

READ_COMMANDS = frozenset({(0, 0x81), (0, 0x82), (0, 0x84), (0, 0x85),
                           (2, 0x84), (2, 0x8C), (2, 0xB0), (4, 0x85), (4, 0x86),
                           (5, 0x80), (5, 0x81), (5, 0x84), (7, 0x80)})


def feature_ioctl(number: int, length: int = 91) -> int:
    return (3 << 30) | (length << 16) | (ord("H") << 8) | number


class ReadOnlyHID:
    def __init__(self, path: str, expected_product: int):
        self.path = path
        self.product = expected_product
        self.fd: int | None = None

    def __enter__(self):
        if self.product not in (0x00B4, 0x00E7, 0x00E8):
            raise ProtocolError("Unsupported device identity")
        node = Path(self.path)
        if node.parent != Path("/dev") or not node.name.startswith("hidraw"):
            raise ProtocolError("Choose a discovered hidraw device")
        self.fd = os.open(node, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            raw = bytearray(8)
            fcntl.ioctl(self.fd, 0x80084803, raw, True)  # HIDIOCGRAWINFO
            bus, vendor, product = struct.unpack("IHH", raw)
            if bus != 3 or vendor != 0x1532 or product != self.product:
                raise ProtocolError("Device identity changed before opening")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def execute(self, command: Command) -> bytes:
        if (command.category, command.operation) not in READ_COMMANDS:
            raise ProtocolError("This transport permits read-only device queries")
        return self._exchange(command)

    def _exchange(self, command: Command) -> bytes:
        if self.fd is None:
            raise RuntimeError("Transport is closed")
        outgoing = bytearray(b"\0" + command.encode())
        result = fcntl.ioctl(self.fd, feature_ioctl(6), outgoing, True)
        if result not in (0, 90, 91):
            raise ProtocolError(f"Incomplete feature request: {result}")
        deadline = time.monotonic() + 0.8
        while True:
            time.sleep(0.025)
            incoming = bytearray(91)
            count = fcntl.ioctl(self.fd, feature_ioctl(7), incoming, True)
            if count != 91:
                raise ProtocolError(f"Expected 91 bytes including report ID, got {count}")
            report = bytes(incoming[1:])
            command.validate_frame(report)
            if command.matches(report) and report[0] != 1:
                return command.decode(report)
            if time.monotonic() >= deadline:
                raise ProtocolError("No matching completed reply; request was not resent")


class BindingHID(ReadOnlyHID):
    """Explicit binding programming, separate from the diagnostics transport.

    Callers must use the journaled programmer, which verifies identity and mode
    before any change. This class provides no mode/firmware/lighting setters.
    """
    def write_binding(self, bank: int, control: int, layer: int, function: bytes):
        banks = (1,) if self.product == 0x00B4 else (1, 2, 3, 4, 5)
        if bank not in banks or layer not in (0, 1) or not 1 <= control <= 255 or len(function) != 7:
            raise ProtocolError("Invalid stored binding request")
        return self._exchange(Command(2, 0x0C, bytes((bank, control, layer)) + function))

    def read_binding(self, bank: int, control: int, layer: int) -> bytes:
        return self.read_binding_record(bank, control, layer)[3:]

    def read_binding_record(self, bank: int, control: int, layer: int) -> bytes:
        if not 0 <= bank <= (1 if self.product == 0x00B4 else 5) or layer not in (0, 1) or not 1 <= control <= 255:
            raise ProtocolError("Invalid binding read")
        return self.execute(Command(2, 0x8C, bytes((bank, control, layer)) + bytes(7)))

    def device_serial(self) -> str:
        raw = self.execute(Command(0, 0x82, bytes(22)))
        serial = raw.split(b"\0", 1)[0]
        if not serial or set(serial) == {48} or not all(32 <= c < 127 for c in serial):
            raise ProtocolError("A unique hardware serial is required before programming")
        return serial.decode("ascii")

    def require_normal_mode(self):
        if self.execute(Command(0, 0x84, bytes(2))) != b"\0\0":
            raise ProtocolError("Stored programming requires normal mode; no mode change was made")


def inspect_device(path: str, product: int) -> dict:
    """Conservative metadata queries; no assignment enumeration or mutations."""
    queries = {"firmware": Command(0, 0x81, bytes(2)),
               "serial": Command(0, 0x82, bytes(22)),
               "mode": Command(0, 0x84, bytes(2)),
               "battery": Command(7, 0x80, bytes(2))}
    result: dict = {"product": f"1532:{product:04x}", "path": path, "read_only": True}
    with ReadOnlyHID(path, product) as hid:
        for name, command in queries.items():
            try:
                payload = hid.execute(command)
                result[name] = payload.hex()
            except (OSError, ProtocolError) as error:
                result[name + "_error"] = str(error)
    return result


def snapshot_device(device) -> dict:
    """Read complete stored/active assignments without changing either.

    V3 banks 0..5 accept binding reads on the observed receiver. Acceptance of
    reads does not establish independent storage or that writes are safe.
    """
    if device.product_id not in CONFIG_INTERFACE:
        raise ProtocolError("Configuration interface not yet verified for this transport")
    nodes = [i for i in device.interfaces if i["kind"] == "hidraw"
             and i["number"] == CONFIG_INTERFACE[device.product_id]]
    if len(nodes) != 1:
        raise ProtocolError("Configuration interface is missing or ambiguous")
    result = inspect_device(nodes[0]["path"], device.product_id)
    result.update({"schema": 1, "model": device.model, "identity": device.identity,
                   "source": "physical read-only queries", "assignments": []})
    with ReadOnlyHID(nodes[0]["path"], device.product_id) as hid:
        initial = hid.execute(Command(2, 0x84, bytes(22)))
        count = initial[0]
        if not 1 <= count <= 79:
            raise ProtocolError("Invalid control count")
        inventory = initial if len(initial) == count + 1 else hid.execute(Command(2, 0x84, bytes(count + 1)))
        ids = inventory[1:]
        if inventory[0] != count or len(ids) != count or len(set(ids)) != count or 0 in ids:
            raise ProtocolError("Inconsistent control inventory")
        result["control_ids"] = list(ids)
        result["raw_inventory"] = inventory.hex()
        banks = range(2) if device.product_id == 0x00B4 else range(6)
        for bank in banks:
            for layer in (0, 1):
                for control in ids:
                    data = hid.execute(Command(2, 0x8C, bytes((bank, control, layer)) + bytes(7)))
                    if data[:2] != bytes((bank, control)):
                        raise ProtocolError("Snapshot response identity mismatch")
                    result["assignments"].append({"bank": bank, "control": control,
                                                   "layer": layer, "raw": data.hex()})
    return result
