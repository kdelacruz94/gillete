"""Explicit desktop undo preserving unrelated current assignments/settings."""

from copy import deepcopy

from . import native_profile_transaction as tx
from .onboard import Location, Programmer
from .protocol import ProtocolError


def restore_affected(io, document, path):
    preview = tx.validate(document)
    document.pop('whole_snapshot_verification_note', None)
    document.update(original_state_restored=False, affected_assignments_restored=False,
                    unrelated_state_preserved=False, restoration_scope='affected-bindings', retained_macros=[])
    tx.state.guard(io, document['before'])
    starting = tx.probe.snapshot(tx.state.ReadBudget(io))
    if starting['controls'] != document['before']['controls']:
        raise ProtocolError('Mouse control inventory changed; no mappings were restored')
    inventory = tx.catalog(io)
    if any(inventory[k] != document['catalog_before'][k] for k in ('slots', 'maximum_bytes')):
        raise ProtocolError('Native macro storage geometry changed; no mappings were restored')
    old_catalog = set(document['catalog_before']['ids'])
    current_ids = set(inventory['ids'])
    old = tx.originals(document['before'])
    needed = {int.from_bytes(old[w][5:7], 'big') for w, target in preview.bindings.items()
              if old[w][3:] != target and old[w][3] in (3, 4, 5, 15)
              and int.from_bytes(old[w][5:7], 'big') in old_catalog}
    if not needed <= current_ids:
        raise ProtocolError('An original macro dependency is missing; no mappings were restored')
    dependencies = [e for e in document.get('library_before', []) if e['id'] in needed]
    tx.library.verify(io, dependencies)
    expected = tx.recovery(document, preview)
    current = tx.originals(starting)
    changed = False
    targets = {}
    for entry in expected['entries']:
        where = Location(entry['bank'], entry['control'], entry['layer'])
        raw = current[where]
        if raw[3:].hex() not in (entry['before'], entry['after']):
            raise ProtocolError('An affected mapping changed externally; refusing to overwrite it')
        active = current[Location(0, where.control, where.layer)]
        if active[3:].hex() not in (entry['before'], entry['after']):
            raise ProtocolError('An affected active mapping changed externally; refusing to overwrite it')
        original = bytes((where.bank, where.control, entry['reply_flag_before'])) + bytes.fromhex(entry['before'])
        targets[where] = original[3:]
        changed |= raw != original
    projected = deepcopy(starting)
    for field in ('records', 'all_records'):
        for entry in projected[field]:
            where = Location(1 if entry['bank'] == 0 else entry['bank'], entry['control'], entry['layer'])
            if where in targets: entry['raw'] = entry['raw'][:6] + targets[where].hex()
    if changed:
        recovery_path = path.with_name('profile-binding-recovery.json')
        tx.ensure_recovery(recovery_path, expected)
        Programmer(io, recovery_path, document['before']['serial'], set(document['before']['controls'])).restore()
    restored = tx.probe.snapshot(tx.state.ReadBudget(io))
    if tx.probe.normalized(restored) != tx.probe.normalized(projected):
        raise ProtocolError('Affected mappings or unrelated current state changed during undo')
    document['affected_assignments_restored'] = True
    tx.library.verify(io, dependencies)
    owned = {a.identifier for a in preview.uploads}
    referenced = set(tx.referenced_ids(restored))
    retained = []
    for asset in preview.uploads:
        if asset.identifier not in current_ids: continue
        reason = None
        if asset.identifier in referenced:
            reason = 'Referenced by another current assignment'
        else:
            try: tx.verify_asset(io, asset)
            except tx.AssetMismatch: reason = 'Object content does not match this receipt; left untouched'
        if reason:
            retained.append({'id': asset.identifier, 'reason': reason})
            continue
        document.update(status='deleting-owned-unreferenced-asset', deleting_id=asset.identifier,
                        retained_macros=retained)
        tx.durable_json(path, document)
        tx.state.guard(io, document['before'])
        io._exchange(tx.memory.delete(asset.identifier))
    after_catalog = tx.catalog(io)
    wanted = (current_ids - owned) | {e['id'] for e in retained}
    if set(after_catalog['ids']) != wanted:
        raise ProtocolError('Catalog changed during scoped undo; verification required')
    after = tx.probe.snapshot(tx.state.ReadBudget(io))
    if tx.probe.normalized(after) != tx.probe.normalized(projected):
        raise ProtocolError('Scoped undo did not preserve unrelated current state')
    tx.library.verify(io, dependencies)
    document.update(after=after, catalog_after=after_catalog, retained_macros=retained,
                    unrelated_state_preserved=True)
    if tx.probe.normalized(after) == tx.probe.normalized(document['before']) and set(after_catalog['ids']) == old_catalog:
        try:
            tx.library.verify(io, document.get('library_before', []))
            document['original_state_restored'] = True
        except (OSError, ValueError) as error:
            document['whole_snapshot_verification_note'] = str(error)
