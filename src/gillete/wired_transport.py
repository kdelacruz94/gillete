"""Proven wired getters and journaled mode changes; no saved-state setters."""

from . import wired_probe as wired
from .hardware import read_journal
from .hid import BindingHID, ReadOnlyHID
from .model import MODELS
from .protocol import ProtocolError


class ModeCaptureHID(wired.WiredQueryHID, BindingHID):
    def __init__(self, path, journal, serial):
        super().__init__(path)
        self.journal, self.expected_serial = journal, serial

    def _exchange(self, command):
        if command.operation < 0x80:
            if ((command.category, command.operation) != (0, 4)
                    or command.payload not in (b'\0\0', b'\3\0') or command.transaction != 0x1F):
                raise ProtocolError('Wired capture allows only journaled normal/driver-mode changes')
            document = read_journal(self.journal)
            if (type(document.get('version')) is not int or document['version'] != 1
                    or document.get('kind') != 'driver-mode' or document.get('product') != wired.PRODUCT
                    or document.get('serial') != self.expected_serial or document.get('before') != '0000'):
                raise ProtocolError('Wired capture allows only journaled normal/driver-mode changes')
            if document.get('status') not in ('prepared', 'driver-mode-active'):
                raise ProtocolError('An active wired lease is required; a completed lease cannot change modes')
        else:
            wired.validate_query(command)
        return ReadOnlyHID._exchange(self, command)


def read_state(io):
    return wired.WiredProbe(io, {'queries': []}, max_requests=256, seconds=60).state(MODELS[1])


class SessionHID(ModeCaptureHID):
    """Mode-only transport bound to its owner's active journal."""
    def __init__(self, path, state, serial, firmware, *, journal=None):
        super().__init__(path, state / 'unclaimed-mode.json', serial)
        self.state, self.expected_firmware = state, firmware
        self.claimed_journal = journal

    def __enter__(self):
        super().__enter__()
        try:
            if self.execute(wired.BOOTSTRAP['firmware']).hex() != self.expected_firmware:
                raise ProtocolError('Wired firmware or identity changed; no mode change admitted')
            serial = self.device_serial()
            if self.expected_serial is not None and serial != self.expected_serial:
                raise ProtocolError('Wired firmware or identity changed; no mode change admitted')
            self.expected_serial = serial
            return self
        except BaseException:
            self.__exit__()
            raise

    def _exchange(self, command):
        if command.operation < 0x80:
            candidates = []
            for path in self.state.glob('mode-*.json'):
                document = read_journal(path)
                if (document.get('kind') == 'driver-mode' and document.get('product') == wired.PRODUCT
                        and document.get('serial') == self.expected_serial
                        and document.get('status') in ('prepared', 'driver-mode-active')):
                    candidates.append(path)
            if len(candidates) != 1:
                raise ProtocolError('Exactly one active owned wired mode journal is required')
            if self.claimed_journal is not None and candidates[0].resolve() != self.claimed_journal.resolve():
                raise ProtocolError('Requested wired journal is not the active owned lease')
            self.journal = candidates[0]
        return super()._exchange(command)
