"""Serialized button-triggered DPI/native controls for an owned HID session.

These commands run only for explicit mapped button presses. Focus switching
does not call them or write settings. Durable recovery covers uncertain writes.
"""

from pathlib import Path
from uuid import uuid4

from .onboard import durable_json
from .device_action_support import decode_wheel_mode
from .protocol import Command, ProtocolError
from .settings import SettingsPlan, SettingsTransaction, Stages, encode_dpi, query


class Controls:
    def __init__(self, io, snapshot, state: Path):
        self.io, self.snapshot, self.state = io, snapshot, state

    def read(self, category, operation, payload):
        return self.io.execute(Command(category, operation, payload))

    def write_checked(self, category, setter, getter, before, after, query):
        if before == after:
            return
        path = self.state / f'setting-{uuid4().hex}.json'
        document = {'version': 1, 'kind': 'device-setting', 'product': self.io.product,
                    'serial': self.snapshot.serial, 'category': category, 'setter': setter,
                    'getter': getter, 'query': query.hex(), 'before': before.hex(), 'after': after.hex(),
                    'status': 'prepared'}
        durable_json(path, document)
        try:
            self.io._exchange(Command(category, setter, after))
            if self.read(category, getter, query) != after:
                raise ProtocolError('Device setting readback mismatch')
            document['status'] = 'applied-readback-verified'
            durable_json(path, document)
        except BaseException:
            # Include an uncertain SET in recovery even if its ACK was lost.
            try:
                if self.io.device_serial() != self.snapshot.serial:
                    raise ProtocolError('Device identity changed before setting rollback')
                self.io._exchange(Command(category, setter, before))
                if self.read(category, getter, query) != before:
                    raise ProtocolError('Setting rollback readback mismatch')
                document['status'] = 'rolled-back-readback-verified'
                durable_json(path, document)
            except BaseException as error:
                raise ProtocolError(f'Setting recovery required: {path}') from error
            raise

    def dpi(self, direction):
        if direction not in ('up', 'down'):
            raise ProtocolError('Unknown DPI direction')
        before = {name: self.io.execute(query(name)) for name in ('stages', 'dpi')}
        stages = Stages.decode(before['stages'], self.io.product)
        target = min(len(stages.values), max(1, stages.active + (1 if direction == 'up' else -1)))
        after = {'stages': b'\1' + bytes((target,)) + before['stages'][2:],
                 'dpi': encode_dpi(before['dpi'], stages.values[target - 1], self.io.product)}
        path = self.state / f'settings-{uuid4().hex}.json'
        SettingsTransaction(self.io, path, self.snapshot.serial, self.snapshot.active, mode=3).apply(SettingsPlan(before, after))

    def native(self, target):
        if self.io.product not in (0xE7, 0xE8):
            raise ProtocolError('Native device controls are supported only on the V3')
        if target == 'onboard_profile_cycle':
            if self.snapshot.assigned == (self.snapshot.bank,):
                return
            # Switching hardware banks also replaces the stored fallback map.
            # Keep this unavailable until that full transition is implemented.
            raise ProtocolError('Multiple onboard-bank cycling is not integrated with the service yet')
        if target != 'wheel_mode_cycle':
            raise ProtocolError('Unsupported native control')
        query = bytes((1, 0))
        before = self.read(2, 0xB0, query)
        mode = decode_wheel_mode(before)
        self.write_checked(2, 0x30, 0xB0, before, bytes((1, (mode + 1) % 3)), query)


def restore_setting(io, path, document):
    signature = (document.get('category'), document.get('setter'), document.get('getter'))
    if signature not in {(4, 6, 0x86), (2, 0x30, 0xB0)}:
        raise ProtocolError('Unsupported device-setting recovery')
    if document.get('serial') != io.device_serial() or document.get('product') != io.product:
        raise ProtocolError('Setting journal belongs to another mouse')
    before, query = bytes.fromhex(document['before']), bytes.fromhex(document['query'])
    if signature[0] == 4:
        Stages.decode(before, io.product)
        if query != b'\1' + bytes(37):
            raise ProtocolError('Invalid DPI recovery table')
    elif io.product not in (0xE7, 0xE8) or query != b'\1\0' or before not in (b'\1\0', b'\1\1', b'\1\2'):
        raise ProtocolError('Invalid wheel-mode recovery')
    category, setter, getter = signature
    io._exchange(Command(category, setter, before))
    if io.execute(Command(category, getter, query)) != before:
        raise ProtocolError('Setting restore readback mismatch')
    document['status'] = 'restored-readback-verified'
    durable_json(path, document)
    return document
