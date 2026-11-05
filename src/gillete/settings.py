"""DPI/stage/polling codecs and durable transactions for the current mouse.

The leading DPI byte selects storage, not an onboard profile number. Stage
selection is a one-based ordinal, independent of each record's identifier.
Original opaque fields are retained. Coupled DPI values are recovered together.
"""

from dataclasses import dataclass
from pathlib import Path

from .onboard import durable_json
from .protocol import Command, ProtocolError


DPI_MAX = {0xB4: 30000, 0xE7: 50000, 0xE8: 50000}
POLLING = {125: 8, 500: 2, 1000: 1}
# In dependency order: a stage-table write can also update scalar DPI.
SPECS = {'stages': (4, 6, 0x86, b'\1' + bytes(37)),
         'dpi': (4, 5, 0x85, b'\1' + bytes(6)),
         'polling': (0, 5, 0x85, bytes(1))}


def query(name):
    category, _, getter, payload = SPECS[name]
    return Command(category, getter, payload)


def validate_pair(pair, product):
    if product not in DPI_MAX:
        raise ProtocolError('Unsupported mouse settings')
    if len(pair) != 2 or any(type(v) is not int or not 100 <= v <= DPI_MAX[product] for v in pair):
        raise ProtocolError(f'DPI must be 100–{DPI_MAX[product]} on each axis')
    return tuple(pair)


def decode_dpi(raw, product):
    if len(raw) != 7 or raw[0] != 1:
        raise ProtocolError('Unrecognized stored DPI response')
    return validate_pair((int.from_bytes(raw[1:3], 'big'), int.from_bytes(raw[3:5], 'big')), product)


def encode_dpi(before, pair, product):
    decode_dpi(before, product)
    x, y = validate_pair(pair, product)
    return before[:1] + x.to_bytes(2, 'big') + y.to_bytes(2, 'big') + before[5:]


@dataclass(frozen=True)
class Stages:
    active: int
    values: tuple[tuple[int, int], ...]
    identifiers: tuple[int, ...]

    @classmethod
    def decode(cls, raw, product):
        if len(raw) != 38 or raw[0] != 1 or not 1 <= raw[1] <= raw[2] <= 5:
            raise ProtocolError('Unrecognized stored DPI stage table')
        values, identifiers = [], []
        for i in range(raw[2]):
            offset = 3 + i * 7
            identifiers.append(raw[offset])
            values.append(validate_pair((int.from_bytes(raw[offset+1:offset+3], 'big'),
                                         int.from_bytes(raw[offset+3:offset+5], 'big')), product))
        if len(set(identifiers)) != len(identifiers):
            raise ProtocolError('Duplicate DPI stage identifiers')
        return cls(raw[1], tuple(values), tuple(identifiers))


def encode_stages(before, values, active, product):
    original = Stages.decode(before, product)
    if type(active) is not int or not 1 <= active <= len(values) <= 5:
        raise ProtocolError('Choose 1–5 DPI stages and an active stage within them')
    values = tuple(validate_pair(pair, product) for pair in values)
    result = bytearray(before)
    result[1:3] = bytes((active, len(values)))
    base = original.identifiers[0]
    if len(values) > len(original.values) and (base not in (0, 1) or original.identifiers != tuple(range(base, base + len(original.values)))):
        raise ProtocolError('Cannot add stages to an unrecognized identifier sequence')
    for i, (x, y) in enumerate(values):
        offset = 3 + i * 7
        if i >= len(original.values):
            result[offset] = base + i
        result[offset+1:offset+5] = x.to_bytes(2, 'big') + y.to_bytes(2, 'big')
    # Preserve reserved bytes and inactive records instead of resetting them.
    return bytes(result)


def decode_polling(raw, product):
    if product not in DPI_MAX or len(raw) != 1 or raw[0] not in POLLING.values():
        raise ProtocolError('Unrecognized receiver polling rate')
    return next(hz for hz, value in POLLING.items() if value == raw[0])


def validate_value(name, raw, product):
    return {'dpi': decode_dpi, 'stages': Stages.decode, 'polling': decode_polling}[name](raw, product)


@dataclass(frozen=True)
class SettingsDraft:
    dpi: tuple[int, int] | None = None
    stages: tuple[tuple[int, int], ...] | None = None
    active: int | None = None
    polling: int | None = None


@dataclass
class SettingsPlan:
    before: dict[str, bytes]
    after: dict[str, bytes]

    @property
    def changes(self):
        return {name: value for name, value in self.after.items() if value != self.before[name]}


def plan(snapshot, draft: SettingsDraft) -> SettingsPlan:
    before, after = {}, {}
    names = set()
    if draft.dpi is not None or draft.stages is not None or draft.active is not None:
        names.update(('dpi', 'stages'))
    if draft.polling is not None:
        names.add('polling')
    for name in SPECS:
        if name in names:
            if name not in snapshot.settings:
                raise ProtocolError(f'Read {name} successfully before editing settings')
            raw = bytes.fromhex(snapshot.settings[name])
            validate_value(name, raw, snapshot.product)
            before[name] = after[name] = raw
    if draft.dpi is not None:
        after['dpi'] = encode_dpi(before['dpi'], draft.dpi, snapshot.product)
    if draft.stages is not None or draft.active is not None:
        old = Stages.decode(before['stages'], snapshot.product)
        after['stages'] = encode_stages(before['stages'], draft.stages if draft.stages is not None else old.values,
                                        draft.active if draft.active is not None else old.active, snapshot.product)
    if draft.polling is not None:
        if type(draft.polling) is not int or draft.polling not in POLLING:
            raise ProtocolError('Supported receiver polling rates are 125, 500 and 1000 Hz')
        after['polling'] = bytes((POLLING[draft.polling],))
    changed = {name for name in after if after[name] != before[name]}
    included = changed | ({'dpi', 'stages'} if changed & {'dpi', 'stages'} else set())
    return SettingsPlan({k: v for k, v in before.items() if k in included},
                        {k: v for k, v in after.items() if k in included})


def describe(name, value, product):
    decoded = validate_value(name, value, product)
    if name == 'dpi':
        return f'{decoded[0]} × {decoded[1]} DPI'
    if name == 'polling':
        return f'{decoded} Hz'
    return ', '.join(f'{i}: {x} × {y}' + (' (selected)' if i == decoded.active else '')
                     for i, (x, y) in enumerate(decoded.values, 1))


class SettingsTransaction:
    def __init__(self, io, journal: Path, serial, active_profile, mode=0):
        self.io, self.path, self.serial = io, journal, serial
        self.active_profile, self.mode = active_profile, mode

    def guard(self):
        if self.io.product not in DPI_MAX or not self.serial or self.io.device_serial() != self.serial:
            raise ProtocolError('Settings identity differs from the preview')
        if self.mode not in (0, 3) or self.io.execute(Command(0, 0x84, bytes(2))) != bytes((self.mode, 0)):
            raise ProtocolError('Mouse input mode changed before settings operation')
        active = 1 if self.io.product == 0xB4 else self.io.execute(Command(5, 0x84, b''))[0]
        if type(self.active_profile) is not int or not 1 <= self.active_profile <= 5 or active != self.active_profile:
            raise ProtocolError('Active onboard profile changed before settings operation')

    def validate(self, values):
        if set(values) not in ({'dpi', 'stages'}, {'polling'}, {'dpi', 'stages', 'polling'}):
            raise ProtocolError('Invalid or incomplete coupled settings plan')
        for name, raw in values.items():
            validate_value(name, raw, self.io.product)

    def read(self, values):
        return {name: self.io.execute(query(name)) for name in SPECS if name in values}

    def write(self, values, selected=None):
        for name, (category, setter, _, _) in SPECS.items():
            if name in values and (selected is None or name in selected):
                self.io._exchange(Command(category, setter, values[name]))
        # Check the entire coupled group after the last write, not only the ACK
        # or each immediate response. A later command may alter an earlier one.
        if self.read(values) != values:
            raise ProtocolError('Device settings readback mismatch')

    def record(self, document, status):
        document['status'] = status
        durable_json(self.path, document)

    def apply(self, proposed: SettingsPlan):
        if not proposed.changes:
            return {'status': 'unchanged'}
        self.validate(proposed.before)
        self.validate(proposed.after)
        if proposed.before.keys() != proposed.after.keys():
            raise ProtocolError('Settings plan fields differ')
        if self.path.exists():
            raise ProtocolError('Settings journal already exists; use a new path')
        self.guard()
        if self.read(proposed.before) != proposed.before:
            raise ProtocolError('Mouse settings changed after inspection; prepare a new preview')
        document = {'version': 1, 'kind': 'device-settings', 'product': self.io.product,
                    'serial': self.serial, 'active_profile': self.active_profile,
                    'power_cycle_verified': False, 'status': 'prepared',
                    'before': {k: v.hex() for k, v in proposed.before.items()},
                    'after': {k: v.hex() for k, v in proposed.after.items()}}
        durable_json(self.path, document)
        try:
            selected = set(proposed.changes)
            if 'stages' in selected:
                selected.add('dpi')
            self.write(proposed.after, selected)
            self.record(document, 'applied-readback-verified')
        except BaseException as original:
            try:
                self.guard()
                self.write(proposed.before)
            except BaseException as recovery:
                raise ProtocolError(f'Settings recovery required: {self.path}') from recovery
            try:
                self.record(document, 'rolled-back-readback-verified')
            except OSError:
                # The prepared journal already holds every original byte.
                pass
            raise original
        return document

    def restore(self, document):
        if (document.get('version') != 1 or document.get('kind') != 'device-settings'
                or document.get('serial') != self.serial or document.get('product') != self.io.product
                or document.get('active_profile') != self.active_profile):
            raise ProtocolError('Invalid settings recovery identity')
        try:
            before = {k: bytes.fromhex(v) for k, v in document['before'].items()}
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ProtocolError('Malformed settings recovery values') from error
        self.validate(before)
        self.guard()
        self.write(before)
        self.record(document, 'restored-readback-verified')
        return document
