"""Read-only desktop preparation for native macro dependency previews."""

from . import hardware
from . import native_profile_transaction as tx
from .model import MODELS
from .native_macro_probe import MacroHID
from .onboard import Location
from .protocol import ProtocolError
from .service import socket_path
from .settings import SPECS


def eligible(snapshot):
    return (snapshot is not None and snapshot.product == 0xE8 and snapshot.model == MODELS[1]
            and snapshot.bank == snapshot.active == 1 and tuple(snapshot.assigned) == (1,))


def prepare_review(device, snapshot, profile):
    if not eligible(snapshot) or device.product_id != snapshot.product or device.model != snapshot.model:
        raise ProtocolError('Native macro review currently requires the V3 receiver with only active slot 1 assigned')
    if socket_path().exists():
        raise ProtocolError('Disable Gillete software control before reading native macro memory')
    # Rediscover this exact physical transport; never use a cached hidraw path.
    selected = hardware.transport(device)
    with MacroHID(selected.path, selected.product) as io:
        document = tx.prepare(io, profile)
    before = document['before']
    if (before['serial'] != snapshot.serial or before['firmware'] != snapshot.metadata.get('firmware')
            or before['controls'] != sorted(snapshot.controls)
            or before['settings'] != {name: snapshot.settings.get(name) for name in SPECS}
            or any(bytes.fromhex(entry['raw']) != snapshot.records.get(Location(entry['bank'], entry['control'], entry['layer']))
                   for entry in before['records'] if entry['bank'] == snapshot.bank)):
        raise ProtocolError('Mouse state changed since inspection; read the mouse again before native macro review')
    preview = tx.validate(document)
    if not preview.assets:
        raise ProtocolError('This profile has no native macro candidates; use the ordinary Save to Mouse preview')
    return document
