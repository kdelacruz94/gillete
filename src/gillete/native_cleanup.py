"""Explicit unused managed-macro reclamation; never formats or changes bindings.

Caller owns the HID lock. Each deletion has a new complete reference scan,
byte-exact ownership proof, identity guard and durable intent. Old recovery
dependencies may be retired only through explicit review acknowledgement.
"""

from copy import deepcopy
import json
from pathlib import Path

from . import native_profile_transaction as tx
from . import native_history as history
from .protocol import ProtocolError


KIND = 'native-managed-macro-cleanup'


def snapshot(io, stopped=lambda: False):
    before = tx.probe.snapshot(tx.state.ReadBudget(io, stopped))
    if before['firmware'] != '0101':
        raise ProtocolError('Managed native cleanup is validated only for V3 receiver firmware1.1')
    return before


def references(before, identifier):
    return [{key: entry[key] for key in ('bank', 'control', 'layer')}
            for entry in before['all_records']
            if (raw := bytes.fromhex(entry['raw']))[3] in (3, 4, 5, 15)
            and int.from_bytes(raw[5:7], 'big') == identifier]


def prepare(io, directory, *, stopped=lambda: False):
    before = snapshot(io, stopped)
    inventory = tx.catalog(io)
    receipts, owners = history.scan(directory, before, stopped=stopped)
    rows = []
    reads = tx.library.LibraryReads(io, stopped)
    for identifier in inventory['ids']:
        linked = references(before, identifier)
        row = {'id': identifier, 'name': f'Macro {identifier}', 'references': linked,
               'deletable': False, 'reason': 'No matching managed save artifact', 'undo': []}
        candidates = owners.get(identifier, [])
        asset = None
        if candidates:
            name = tx.memory.read_name(reads, identifier)
            matching = [a for a in candidates if a.metadata == name]
            if matching:
                size = tx.memory.data_size(reads, identifier)
                data = tx.memory.read_data(reads, identifier, size)
                asset = next((a for a in matching if a.data == data), None)
            row['reason'] = 'Object differs from recorded managed data'
        if asset:
            row.update(name=asset.name, reason='Assigned on the mouse' if linked else 'Unused managed macro',
                       deletable=not linked,
                       asset={'id': identifier, 'data': asset.data.hex(), 'metadata': asset.metadata.hex(),
                              'estimated_bytes': asset.allocation_bytes})
            row['undo'] = [{'path': entry['path'], 'profile': entry['profile'],
                            'mapping_dependency': identifier in entry['dependency_ids']}
                           for entry in receipts['records'] if identifier in entry['catalog_ids']]
        rows.append(row)
    tx.state.guard(io, before)
    return {'version': 1, 'kind': KIND, 'status': 'prepared-read-only',
            'before': before, 'catalog_before': inventory, 'history': receipts['stamp'], 'rows': rows}


def proposal(prepared, selected, *, acknowledge_undo=False):
    """Pure selection/admission: also used to disable an oversized GUI choice."""
    if (not isinstance(prepared, dict) or type(prepared.get('version')) is not int
            or prepared.get('version') != 1 or prepared.get('kind') != KIND
            or prepared.get('status') != 'prepared-read-only'):
        raise ProtocolError('A fresh read-only managed-library review is required')
    tx.probe.validate_snapshot(prepared['before'])
    if isinstance(selected, (list, tuple)) and not selected:
        raise ProtocolError('Choose at least one unused managed macro')
    if (not isinstance(selected, (list, tuple)) or not selected or len(selected) > 128
            or any(type(i) is not int for i in selected) or len(set(selected)) != len(selected)
            or type(acknowledge_undo) is not bool):
        raise ProtocolError('Choose an explicit nonempty set of managed macro IDs')
    available = {row['id']: row for row in prepared['rows'] if row['deletable']}
    if not set(selected) <= available.keys():
        raise ProtocolError('Assigned, changed or unmanaged macros cannot be deleted')
    rows = [deepcopy(available[i]) for i in sorted(selected)]
    impacted = sorted({e['path'] for row in rows for e in row['undo']})
    if impacted and not acknowledge_undo:
        raise ProtocolError('Acknowledge the affected undo records before reclaiming their original macro data')
    document = {key: deepcopy(prepared[key]) for key in ('version', 'kind', 'before', 'catalog_before', 'history')}
    document.update(status='armed', rows=rows, selected=sorted(selected), affected_undo=impacted,
                    undo_acknowledged=acknowledge_undo, deleted_ids=[], unchanged_state_verified=False)
    worst = dict(document, after=document['before'], catalog_after=document['catalog_before'])
    if len(json.dumps(worst, indent=2).encode()) > tx.MAX_JOURNAL_BYTES - 32768:
        raise ProtocolError('Selected macro backup is too large for one receipt; choose fewer macros')
    return document


def current_matches(io, document, directory, remaining, *, stopped=lambda: False):
    current = snapshot(io, stopped)
    if tx.probe.normalized(current) != tx.probe.normalized(document['before']):
        raise ProtocolError('Mouse mappings/settings changed; prepare a new storage review')
    receipts, _ = history.scan(directory, current, stopped=stopped)
    if receipts['stamp'] != document['history']:
        raise ProtocolError('Native save history changed; prepare a new storage review')
    inventory = tx.catalog(io)
    if (set(inventory['ids']) != remaining
            or any(inventory[k] != document['catalog_before'][k] for k in ('slots', 'maximum_bytes'))):
        raise ProtocolError('Macro catalog changed; prepare a new storage review')
    return current


def apply(io, prepared, selected, path, directory, *, acknowledge_undo=False,
          stopped=lambda: False, progress=lambda message: None):
    """Delete only the reviewed objects. Never retry an uncertain setter."""
    path = Path(path)
    if path.exists():
        raise ProtocolError('Choose a fresh cleanup receipt path')
    document = proposal(prepared, selected, acknowledge_undo=acknowledge_undo)
    # Reconstruct all ownership and dependency facts from live state/history;
    # a forged/stale GUI payload is never sufficient authority for a delete.
    fresh = prepare(io, directory, stopped=stopped)
    for key in ('catalog_before', 'history', 'rows'):
        if fresh[key] != prepared[key]:
            raise ProtocolError('Managed library changed after review; read it again')
    if tx.probe.normalized(fresh['before']) != tx.probe.normalized(prepared['before']):
        raise ProtocolError('Mouse state changed after storage review')
    tx.durable_json(path, document)  # Includes complete selected metadata/data backups.
    remaining = set(document['catalog_before']['ids'])
    try:
        for count, row in enumerate(document['rows'], 1):
            if stopped(): raise InterruptedError('Managed macro cleanup stopped')
            progress(f'Checking unused macro {count} of {len(document["rows"])}… Keep the mouse awake.')
            current = current_matches(io, document, directory, remaining, stopped=stopped)
            identifier = row['id']
            if references(current, identifier):
                raise ProtocolError('A current mapping references the selected macro; no deletion was submitted')
            raw = row['asset']
            if (tx.memory.data_size(io, identifier) != len(bytes.fromhex(raw['data']))
                    or tx.memory.read_name(io, identifier).hex() != raw['metadata']
                    or tx.memory.read_data(io, identifier, len(bytes.fromhex(raw['data']))).hex() != raw['data']):
                raise ProtocolError('Managed macro changed before deletion')
            tx.state.guard(io, document['before'])
            if stopped(): raise InterruptedError('Managed macro cleanup stopped')
            document.update(status='deleting-managed-macro', deleting_id=identifier)
            tx.durable_json(path, document)
            if stopped(): raise InterruptedError('Managed macro cleanup stopped before deletion')
            io._exchange(tx.memory.delete(identifier))
            remaining.remove(identifier)
            inventory = tx.catalog(io)
            if set(inventory['ids']) != remaining:
                raise ProtocolError('Deletion did not verify or another catalog change occurred')
            document['deleted_ids'].append(identifier)
            tx.durable_json(path, document)
        after = current_matches(io, document, directory, remaining, stopped=stopped)
        final_catalog = tx.catalog(io)
        if set(final_catalog['ids']) != remaining:
            raise ProtocolError('Catalog changed during final cleanup verification')
        document.update(status='cleanup-readback-verified', after=after, catalog_after=final_catalog,
                        unchanged_state_verified=True,
                        transport_health=dict(getattr(io, 'reply_health', {})))
        tx.durable_json(path, document)
        return document
    except BaseException as error:
        document.update(status='cleanup-incomplete', error=str(error) or type(error).__name__,
                        transport_health=dict(getattr(io, 'reply_health', {})))
        try:
            observed = tx.catalog(io)
            document.update(catalog_observed=observed,
                absent_selected_ids=sorted(set(document['selected']) - set(observed['ids'])))
        except (OSError, ValueError) as observation_error:
            document['observation_error'] = str(observation_error)
        try: tx.durable_json(path, document)
        except (OSError, ValueError): pass  # Armed receipt retains all selected bytes.
        raise
