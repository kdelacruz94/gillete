"""Journaled temporary driver-mode ownership; never changes stored bindings."""

from pathlib import Path

from .hardware import read_journal
from .onboard import durable_json
from .protocol import Command, ProtocolError


class ModeLease:
    def __init__(self, io, journal: Path):
        self.io, self.path = io, journal
        self.document = None

    def mode(self):
        return self.io.execute(Command(0, 0x84, bytes(2)))

    def set_mode(self, value: bytes):
        if value not in (b'\0\0', b'\x03\0'):
            raise ProtocolError('Only normal and driver modes are supported')
        self.io._exchange(Command(0, 4, value))
        if self.mode() != value:
            raise ProtocolError('Device mode readback mismatch')

    def record(self, status):
        self.document['status'] = status
        durable_json(self.path, self.document)

    def enter(self):
        if self.path.exists():
            raise ProtocolError('Mode journal already exists; recover it before starting another session')
        serial = self.io.device_serial()
        original = self.mode()
        if original != b'\0\0':
            raise ProtocolError('Mouse is already in another mode; no ownership was taken')
        self.document = {'version': 1, 'kind': 'driver-mode', 'product': self.io.product,
                         'serial': serial, 'before': original.hex(), 'status': 'prepared'}
        durable_json(self.path, self.document)
        try:
            self.set_mode(b'\x03\0')
            self.record('driver-mode-active')
        except BaseException:
            # Even an acknowledgment timeout may follow a successful mode SET.
            self.restore()
            raise

    def restore(self):
        document = self.document if self.document is not None else read_journal(self.path)
        if (document.get('kind') != 'driver-mode' or document.get('product') != self.io.product
                or document.get('serial') != self.io.device_serial() or document.get('before') != '0000'):
            raise ProtocolError('Mode recovery identity or original mode is invalid')
        self.document = document
        current = self.mode()
        if current not in (b'\0\0', b'\x03\0'):
            raise ProtocolError('Unexpected current mode; recovery journal retained')
        if current != b'\0\0':
            self.set_mode(b'\0\0')
        self.record('normal-mode-restored')

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, *_):
        self.restore()
