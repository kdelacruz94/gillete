"""Pure source-backed macro compilation; no I/O or capability enablement."""

from dataclasses import dataclass
from uuid import UUID

from .compile_onboard import MOUSE, USAGES, SoftwareOnly
from .macro_inspection import MAX_BYTES, inspect
from .model import Action, Step
from .protocol import ProtocolError


@dataclass(frozen=True)
class CompiledMacro:
    data: bytes
    items: int
    playback: str
    count: int
    trailing_gap_ms: int

    @property
    def allocation_bytes(self):
        return ((len(self.data) + 256 + 255) // 256) * 256

    def binding(self, identifier):
        if type(identifier) is not int or not 1 <= identifier <= 32767:
            raise ProtocolError('Native macros need a nonzero 15-bit ID')
        count = self.count if self.playback == 'count' else 1
        kind = {'once': 3, 'count': 3, 'held': 4, 'toggle': 5}[self.playback]
        payload = identifier.to_bytes(2, 'big') + (bytes((count,)) if kind == 3 else b'')
        return bytes((kind, len(payload))) + payload + bytes(5 - len(payload))


def delay(value):
    if type(value) is not int or not 0 <= value <= 0x7FFFFFFF:
        raise SoftwareOnly('Native delay exceeds the unambiguous signed 32-bit range')
    width = max(1, (value.bit_length() + 7) // 8)
    return bytes((16 + width,)) + value.to_bytes(width, 'big')


def compile_macro(action: Action) -> CompiledMacro:
    if action.kind not in ('macro', 'turbo'):
        raise SoftwareOnly('Expected a timed macro or turbo action')
    if action.playback == 'count' and action.count > 255:
        raise SoftwareOnly('Native counted playback is limited to 255 iterations')
    if action.kind == 'turbo':
        steps = [*(Step('down', key) for key in action.keys), Step('wait', milliseconds=action.press_ms),
                 *(Step('up', key) for key in reversed(action.keys)),
                 Step('wait', milliseconds=action.interval_ms - action.press_ms)]
        gap = action.interval_ms - action.press_ms
    else:
        steps = list(action.steps)
        gap = action.interval_ms if action.playback != 'once' else 0
        if gap:
            steps.append(Step('wait', milliseconds=gap))
    data, items, held_mouse = bytearray(), 0, 0
    for step in steps:
        if step.kind in ('down', 'up'):
            if step.key in MOUSE:
                bit = 1 << (MOUSE[step.key] - 1)
                held_mouse = held_mouse | bit if step.kind == 'down' else held_mouse & ~bit
                record = bytes((8, held_mouse))
            elif step.key in USAGES:
                record = bytes((1 if step.kind == 'down' else 2, USAGES[step.key]))
            else:
                raise SoftwareOnly(f'{step.key} has no supported native macro encoding')
        elif step.kind == 'wait':
            record = delay(step.milliseconds)
        elif step.axis == 'REL_WHEEL':
            if abs(step.value) > MAX_BYTES // 2:
                raise SoftwareOnly('Native wheel sequence exceeds macro byte limit')
            record = bytes((10, 1 if step.value > 0 else 255)) * abs(step.value)
        else:
            raise SoftwareOnly('Native cursor coordinates and horizontal macro scrolling remain unverified')
        if len(data) + len(record) > MAX_BYTES:
            raise SoftwareOnly('Native macro exceeds the 4096-byte compilation limit')
        data.extend(record)
        items += abs(step.value) if step.kind == 'relative' else 1
    result = inspect(bytes(data))
    if (not data or result['status'] != 'decoded' or result['warnings']
            or any(result['held_at_boundary'].values())):
        raise SoftwareOnly('Native macro must contain valid records and release every held input')
    return CompiledMacro(bytes(data), items, action.playback, action.count, gap)


def metadata(compiled: CompiledMacro, guid: str, name: str) -> bytes:
    if not isinstance(name, str) or not name or '\0' in name or len(name.encode('utf-8')) > 99:
        raise ProtocolError('Native macro name must fit 99 UTF-8 bytes plus a terminator')
    try:
        identity = UUID(guid).bytes_le
    except (ValueError, TypeError, AttributeError) as error:
        raise ProtocolError('Invalid native macro UUID') from error
    encoded = name.encode('utf-8')
    return identity + compiled.items.to_bytes(4, 'little') + encoded + bytes(100 - len(encoded)) + bytes(130)
