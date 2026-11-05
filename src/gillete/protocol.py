"""Razer 90-byte report framing and V2 binding requests, with no I/O side effects.

Wire facts and model limits are documented in docs/feasibility.md. V3 command
compatibility is deliberately not inferred from its USB identity.
"""

from dataclasses import dataclass
from functools import reduce
from operator import xor


class ProtocolError(ValueError):
    pass


class DeviceStatusError(ProtocolError):
    def __init__(self, status: int):
        self.status = status
        super().__init__({1: "Device busy", 3: "Command rejected", 4: "Device timeout",
                          5: "Unsupported command"}.get(status, f"Unknown status {status}"))


def checksum(report: bytes) -> int:
    if len(report) != 90:
        raise ProtocolError("A report must contain exactly 90 bytes")
    return reduce(xor, report[2:88], 0)


@dataclass(frozen=True)
class Command:
    category: int
    operation: int
    payload: bytes
    transaction: int = 0x1F

    def __post_init__(self):
        if any(type(v) is not int or not 0 <= v <= 255
               for v in (self.category, self.operation, self.transaction)):
            raise ProtocolError("Command fields must be bytes")
        if not isinstance(self.payload, bytes) or len(self.payload) > 80:
            raise ProtocolError("Payload must be at most 80 bytes")

    def encode(self) -> bytes:
        report = bytearray(90)
        report[1] = self.transaction
        report[5:8] = bytes((len(self.payload), self.category, self.operation))
        report[8:8 + len(self.payload)] = self.payload
        report[88] = checksum(report)
        return bytes(report)

    def validate_frame(self, report: bytes):
        if len(report) != 90 or report[88] != checksum(report):
            raise ProtocolError("Invalid report length or checksum")
        if any(report[i] for i in (2, 3, 4, 89)) or report[5] > 80:
            raise ProtocolError("Invalid reserved fields or payload size")

    def matches(self, report: bytes) -> bool:
        self.validate_frame(report)
        if (report[1], report[6], report[7]) != (self.transaction, self.category, self.operation):
            return False
        if self.category == 2 and self.operation == 0x8C and report[0] == 2:
            return report[5] == 10 and report[8:10] == self.payload[:2]
        return True

    def decode(self, report: bytes) -> bytes:
        if not self.matches(report):
            raise ProtocolError("Reply belongs to another command or binding")
        if report[0] != 2:
            raise DeviceStatusError(report[0])
        # These profile queries declare zero bytes even when their argument
        # area contains the result. Limit the exception to the documented
        # count/list/active commands; never relax generic framing checks.
        profile_sizes = {0x80: 1, 0x81: 6, 0x84: 1}
        if self.category == 5 and self.operation in profile_sizes and not self.payload:
            size = profile_sizes[self.operation]
            if self.operation == 0x81:
                if not 1 <= report[8] <= 5:
                    raise ProtocolError("Unknown maximum onboard profile ID")
                size = report[8] + 1
                if 2 <= report[5] <= size:
                    size = report[5]
            if report[5] not in (0, size):
                raise ProtocolError("Unexpected profile response payload size")
            return bytes(report[8:8 + size])
        if report[5] != len(self.payload):
            raise ProtocolError("Unexpected response payload size")
        return bytes(report[8:8 + report[5]])


# Verified inventory in the upstream V2 receiver investigation; not V3 IDs.
V2_CONTROLS = {
    "left_click": 1, "right_click": 2, "wheel_click": 3,
    "wheel_up": 9, "wheel_down": 10, "wheel_tilt_left": 0x34,
    "wheel_tilt_right": 0x35, "dpi_up": 0x0B, "dpi_down": 0x0C,
    **{f"side_{i}": 0x3F + i for i in range(1, 13)},
}


def v2_inventory_command() -> Command:
    return Command(2, 0x84, bytes(22))


def v2_decode_inventory(payload: bytes) -> tuple[int, ...]:
    if len(payload) != 22 or payload[0] != 21:
        raise ProtocolError("Unexpected V2 control inventory size")
    ids = tuple(payload[1:])
    if len(set(ids)) != 21 or set(ids) != set(V2_CONTROLS.values()):
        raise ProtocolError("Unknown or duplicate control IDs; do not program this layout")
    return ids


@dataclass(frozen=True)
class Binding:
    bank: int
    control: int
    layer: int
    function: bytes

    def __post_init__(self):
        if self.bank not in (0, 1) or self.layer not in (0, 1) or self.control not in V2_CONTROLS.values():
            raise ProtocolError("Unsupported V2 bank, control or layer")
        if not isinstance(self.function, bytes) or len(self.function) != 7:
            raise ProtocolError("A binding function has seven bytes")

    @classmethod
    def response(cls, payload: bytes, *, bank: int, control: int, layer: int):
        if len(payload) != 10 or payload[:2] != bytes((bank, control)):
            raise ProtocolError("Binding response has incorrect identity")
        # Response byte 2 is status metadata. The request supplies the layer.
        return cls(bank, control, layer, payload[3:])

    def read_command(self) -> Command:
        return Command(2, 0x8C, bytes((self.bank, self.control, self.layer)) + bytes(7))

    def write_command(self) -> Command:
        if self.bank != 1:
            raise ProtocolError("Active-bank writes have not been verified")
        return Command(2, 0x0C, bytes((self.bank, self.control, self.layer)) + self.function)
