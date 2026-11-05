"""Decode the two keyboard report layouts observed on these Naga receivers.

The 61-byte boot-keyboard descriptor uses 8-byte unnumbered input reports.
The 314-byte composite descriptor's report 1 uses one modifier byte followed
by fourteen keyboard usages. Non-keyboard reports are ignored, not guessed.
"""

from .protocol import ProtocolError


def keyboard_usages(report: bytes, *, numbered: bool) -> frozenset[int] | None:
    if numbered:
        if not report or report[0] != 1:
            return None
        if len(report) != 16:
            raise ProtocolError("Unexpected composite keyboard input length")
        modifiers, keys = report[1], report[2:]
    else:
        if len(report) != 8:
            raise ProtocolError("Unexpected boot keyboard input length")
        modifiers, keys = report[0], report[2:]
    if any(key in (1, 2, 3) for key in keys):
        raise ProtocolError("Keyboard rollover/error report")
    return frozenset({key for key in keys if key} | {0xE0 + bit for bit in range(8) if modifiers & (1 << bit)})
