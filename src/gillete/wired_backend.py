"""Validated V3 cable reads/software mode, separate from onboard programming."""

import hashlib

from . import wired_probe as wired
from .devices import discover
from .driver_mode import ModeLease
from .hardware import Snapshot, read_journal
from .model import MODELS
from .onboard import Location
from .protocol import DeviceUnavailable, ProtocolError
from .reports import decode_wired
from .wired_transport import SessionHID, read_state


FIRMWARE = '01010000'
# Exact public descriptors also captured on the development unit, with hid-generic.
DESCRIPTORS = {
    '00': 'a36ca73db8d83b74d926400edbb53fa4ecb9acd22eb531a7e1c8f7dba45a783c',
    '01': '1a8ded231a2df9765104bf1d0de3449f35676de229dab0300892fda05735c40a',
    '02': 'a638a07d99bb58fa0734d44e7b20ac7327bd0b92aec401420ceafbae0c552915',
    '03': '515026d9374d7cc8844da984eecb138b494d031dbef6cad644c48fde924b6021',
}


def node(device):
    if device.product_id != wired.PRODUCT or device.model != MODELS[1]:
        raise ProtocolError('Wired backend requires the V3 cable transport')
    matches = [d for d in discover() if d.product_id == wired.PRODUCT and d.usb_path == device.usb_path]
    if not matches: raise DeviceUnavailable('Wired V3 disconnected or moved; refresh devices')
    if len(matches) != 1: raise ProtocolError('Wired transport identity is ambiguous')
    entries = wired.descriptors(matches[0])
    if (set(entries) != set(DESCRIPTORS) or any(
            hashlib.sha256(bytes.fromhex(entry['raw'])).hexdigest() != DESCRIPTORS[number]
            or entry['hid_driver'] != 'hid-generic' or entry['usb_driver'] != 'usbhid'
            for number, entry in entries.items())):
        raise ProtocolError('This wired driver or descriptor layout has not been validated')
    return entries['00']['node']


def inspect_device(device, bank=None):
    if bank is not None and (type(bank) is not int or bank != 1):
        raise ProtocolError('Only the verified wired slot1 is readable')
    with wired.WiredQueryHID(node(device)) as io:
        current = read_state(io)
    if (current['firmware'] != FIRMWARE or current['assigned'] != [1]
            or current['active'] != 1):
        raise ProtocolError('Wired reads/software control require validated firmware1.1 and sole active slot1')
    return Snapshot(wired.PRODUCT, MODELS[1], current['serial'], 1, (1,), 1, set(current['controls']),
        {Location(r['bank'], r['control'], r['layer']): bytes.fromhex(r['raw'])
         for r in current['records'] if r['bank'] == 1}, current['settings'],
        {'firmware': current['firmware']})


def restore_mode(device, journal):
    document = read_journal(journal)
    if document.get('kind') != 'driver-mode':
        raise ProtocolError('Wired onboard recovery writes remain unverified; only owned input-mode recovery is available')
    with SessionHID(node(device), journal.parent, None, FIRMWARE, journal=journal) as io:
        if document.get('product') != io.product or document.get('serial') != io.expected_serial:
            raise ProtocolError('This recovery journal belongs to a different wired mouse')
        lease = ModeLease(io, journal)
        lease.restore()
        return lease.document


class Backend:
    decode = staticmethod(decode_wired)
    inspect = staticmethod(inspect_device)

    def __init__(self, state):
        self.state = state

    def transport(self, device):
        # Serial is read/validated on opening; ModeLease then binds its journal
        # to that identity. Each SET also requires exactly one active owned lease.
        return SessionHID(node(device), self.state, None, FIRMWARE)
