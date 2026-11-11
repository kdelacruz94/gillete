"""User-requested onboard inspection, preview and journaled programming.

Opening the editor does not call this module. All operations rediscover the
physical transport and verify serial identity; a preview is never authority to
overwrite changes made later by another app.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from .compile_onboard import CONTROL_IDS, OnboardPlan, compile_profile
from .devices import Device, discover
from .hid import BindingHID, CONFIG_INTERFACE
from .model import Profile
from .onboard import Location, Programmer, durable_json
from .protocol import Command, DeviceUnavailable, ProtocolError
from .settings import SettingsDraft, SettingsTransaction, SPECS, plan as settings_plan, query as settings_query


def journal_directory() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "gillete/onboard"


def transport(device: Device) -> BindingHID:
    # Rediscovery avoids trusting a stale /dev/hidraw number after hotplug.
    matches = [d for d in discover() if d.usb_path == device.usb_path and d.product_id == device.product_id]
    if not matches:
        raise DeviceUnavailable("Mouse disconnected or moved; refresh connected devices")
    if len(matches) != 1:
        raise ProtocolError('Mouse transport identity is ambiguous')
    if device.product_id not in CONFIG_INTERFACE:
        raise ProtocolError("This transport's configuration interface still needs validation")
    nodes = [i for i in matches[0].interfaces if i["kind"] == "hidraw"
             and i["number"] == CONFIG_INTERFACE[device.product_id]]
    if not nodes:
        raise DeviceUnavailable('Mouse configuration interface is not available yet')
    if len(nodes) != 1:
        raise ProtocolError("Configuration interface is missing or ambiguous")
    return BindingHID(nodes[0]["path"], device.product_id)


def profile_slots(io) -> tuple[tuple[int, ...], int]:
    count = io.execute(Command(5, 0x80, b""))[0]
    raw = io.execute(Command(5, 0x81, b""))
    maximum, identifiers = raw[0], tuple(v for v in raw[1:] if v)
    if (not 1 <= maximum <= (1 if io.product == 0xB4 else 5)
            or not 1 <= count <= maximum or len(identifiers) != count
            or len(set(identifiers)) != count or any(v > maximum for v in identifiers)):
        raise ProtocolError("Inconsistent assigned-profile inventory")
    # The single-slot V2 rejects the active-profile getter. It reports one
    # assigned slot, 1; no selectable alternative is implied.
    active = 1 if io.product == 0xB4 and identifiers == (1,) else io.execute(Command(5, 0x84, b""))[0]
    if active not in identifiers:
        raise ProtocolError("Active profile is absent from the assigned inventory")
    return identifiers, active


def inventory(io) -> set[int]:
    first = io.execute(Command(2, 0x84, bytes(22)))
    count = first[0]
    if not 1 <= count <= 79:
        raise ProtocolError("Invalid button inventory size")
    raw = first if len(first) == count + 1 else io.execute(Command(2, 0x84, bytes(count + 1)))
    ids = set(raw[1:])
    if raw[0] != count or len(ids) != count or 0 in ids:
        raise ProtocolError("Inconsistent button inventory")
    return ids


@dataclass
class Snapshot:
    product: int
    model: str
    serial: str
    bank: int
    assigned: tuple[int, ...]
    active: int
    controls: set[int]
    records: dict[Location, bytes]
    settings: dict[str, str]
    metadata: dict[str, str] = field(default_factory=dict)
    native_macros: dict[int, str] = field(default_factory=dict)

    @property
    def baseline(self):
        return {w: raw[3:] for w, raw in self.records.items()}

    def plan(self, profile: Profile) -> OnboardPlan:
        return compile_profile(profile, self.model, self.bank, self.baseline)


def snapshot_document(snapshot):
    return {'product': snapshot.product, 'model': snapshot.model, 'serial': snapshot.serial,
            'bank': snapshot.bank, 'assigned': list(snapshot.assigned), 'active': snapshot.active,
            'controls': sorted(snapshot.controls), 'settings': snapshot.settings, 'metadata': snapshot.metadata,
            'records': [{**where.json(), 'raw': raw.hex()} for where, raw in sorted(snapshot.records.items())],
            **({'native_macros': {str(i): raw for i, raw in snapshot.native_macros.items()}}
               if snapshot.native_macros else {})}


def load_snapshot(document):
    from .stored_native import load_bodies
    return Snapshot(document['product'], document['model'], document['serial'], document['bank'],
                    tuple(document['assigned']), document['active'], set(document['controls']),
                    {Location(r['bank'], r['control'], r['layer']): bytes.fromhex(r['raw']) for r in document['records']},
                    document['settings'], document.get('metadata', {}),
                    load_bodies(document.get('native_macros', {})))


def read_records(io, model, bank):
    records = {}
    for layer in (0, 1):
        for control in CONTROL_IDS[model].values():
            where = Location(bank, control, layer)
            raw = io.read_binding_record(bank, control, layer)
            if len(raw) != 10 or raw[:2] != bytes((bank, control)) or raw[2] not in (0, 1):
                raise ProtocolError("Unknown binding response; snapshot aborted")
            records[where] = raw
    return records


def inspect(device: Device, bank: int | None = None) -> Snapshot:
    with transport(device) as io:
        io.require_normal_mode()
        serial = io.device_serial()
        assigned, active = profile_slots(io)
        bank = active if bank is None else bank
        if bank not in assigned:
            raise ProtocolError("Only assigned onboard slots can be edited")
        controls = inventory(io)
        if not set(CONTROL_IDS[device.model].values()) <= controls:
            raise ProtocolError("The mouse inventory does not match this layout")
        records = read_records(io, device.model, bank)
        settings = {}
        for name in SPECS:
            try:
                settings[name] = io.execute(settings_query(name)).hex()
            except (OSError, ProtocolError) as error:
                settings[name + "_error"] = str(error)
        metadata = {}
        metadata_queries = [('battery', Command(7, 0x80, bytes(2))), ('firmware', Command(0, 0x81, bytes(2)))]
        if device.product_id in (0xE7, 0xE8):
            metadata_queries.append(('wheel_mode', Command(2, 0xB0, b'\1\0')))
        for name, command in metadata_queries:
            try:
                metadata[name] = io.execute(command).hex()
            except (OSError, ProtocolError) as error:
                metadata[name + '_error'] = str(error)
        snapshot = Snapshot(io.product, device.model, serial, bank, assigned, active, controls, records, settings, metadata)
        from . import stored_native
        try:
            snapshot.native_macros = stored_native.read(io, snapshot)
        except (OSError, ValueError) as error:
            # Missing bodies never become executable defaults. Explicit host
            # overrides remain possible even when this optional read fails.
            metadata['native_macro_error'] = str(error)
        return snapshot


def apply(device: Device, snapshot: Snapshot, profile: Profile, journal: Path) -> dict:
    plan = snapshot.plan(profile)
    if not plan.writable:
        raise ProtocolError("Onboard save is blocked: " + "; ".join(plan.issues))
    with transport(device) as io:
        io.require_normal_mode()
        if io.product != snapshot.product or io.device_serial() != snapshot.serial or device.model != snapshot.model:
            raise ProtocolError("The mouse differs from the preview")
        assigned, active = profile_slots(io)
        if (assigned, active) != (snapshot.assigned, snapshot.active):
            raise ProtocolError("Onboard profile selection changed; prepare a new preview")
        if inventory(io) != snapshot.controls or read_records(io, snapshot.model, snapshot.bank) != snapshot.records:
            raise ProtocolError("Mouse bindings changed after inspection; prepare a new preview")
        return Programmer(io, journal, snapshot.serial, snapshot.controls).apply(plan.targets)


def apply_settings(device: Device, snapshot: Snapshot, draft: SettingsDraft, journal: Path) -> dict:
    proposed = settings_plan(snapshot, draft)
    if snapshot.bank != snapshot.active:
        raise ProtocolError('Inspect the active onboard slot before editing device settings')
    with transport(device) as io:
        if io.product != snapshot.product or device.model != snapshot.model:
            raise ProtocolError('The mouse differs from the settings preview')
        return SettingsTransaction(io, journal, snapshot.serial, snapshot.active).apply(proposed)


def read_journal(path: Path) -> dict:
    with path.open("rb") as file:
        raw = file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ProtocolError("Oversized recovery journal")
    document = json.loads(raw)
    if (not isinstance(document, dict) or document.get('version') != 1
            and not (document.get('version') == 2 and document.get('kind') == 'native-macro-profile-transaction')):
        raise ProtocolError("Unsupported recovery journal")
    return document


def backup(snapshot: Snapshot, path: Path):
    """Save both layers of the inspected slot, including undecoded functions."""
    if any(raw[3] in (3, 4, 5, 15) and raw[4] in (2, 3) and int.from_bytes(raw[5:7], 'big')
           for raw in snapshot.records.values()):
        raise ProtocolError('This slot references native macro data. Assignment-only backups cannot restore '
                            'that data; keep the full native profile recovery journal and exported Linux profile.')
    durable_json(path, {'version': 1, 'product': snapshot.product, 'serial': snapshot.serial,
                       'status': 'slot-backup', 'power_cycle_verified': False,
                       'entries': [{**where.json(), 'before': raw[3:].hex(), 'after': raw[3:].hex(),
                                    'reply_flag_before': raw[2]} for where, raw in sorted(snapshot.records.items())]})


def restore(device: Device, journal: Path) -> dict:
    document = read_journal(journal)
    if document.get('kind') == 'native-macro-profile-transaction':
        from .native_profile_review import restore_review
        return restore_review(device, journal)
    with transport(device) as io:
        serial = io.device_serial()
        if document.get("product") != io.product or document.get("serial") != serial:
            raise ProtocolError("This recovery journal belongs to a different mouse")
        if document.get("kind") == "driver-mode":
            from .driver_mode import ModeLease
            lease = ModeLease(io, journal)
            lease.restore()
            return lease.document
        if document.get('kind') == 'device-setting':
            from .device_controls import restore_setting
            io.require_normal_mode()
            return restore_setting(io, journal, document)
        if document.get('kind') == 'device-settings':
            return SettingsTransaction(io, journal, serial, document.get('active_profile')).restore(document)
        if document.get("kind") is not None:
            raise ProtocolError("Unknown recovery journal kind")
        return Programmer(io, journal, serial, inventory(io)).restore()
