"""Experimental asset-aware profile saves; production UI remains gated.

Caller owns the exclusive HID transport. All new objects precede binding
writes. Restore never deletes existing catalog entries or unverified objects.
"""

from copy import deepcopy

from . import dpi_probe as state
from . import macro_memory as memory
from . import native_macro_probe as probe
from .hardware import read_journal
from .macro_reads import catalog
from .model import Profile
from .native_macro_plan import preview_profile
from .onboard import Location, Programmer, durable_json
from .protocol import ProtocolError


KIND = 'native-macro-profile-transaction'


def referenced_ids(before):
    return sorted({int.from_bytes(raw[5:7], 'big') for entry in before['all_records']
                   if (raw := bytes.fromhex(entry['raw']))[3] in (3, 4, 5, 15)})


def originals(before):
    return {Location(e['bank'], e['control'], e['layer']): bytes.fromhex(e['raw']) for e in before['all_records']}


def plan(profile, before, inventory):
    return preview_profile(profile, before['product'], 1, {w: raw[3:] for w, raw in originals(before).items()},
                           catalog_ids=inventory['ids'], referenced_ids=referenced_ids(before),
                           available_bytes=inventory['available_bytes'], slot_capacity=inventory['slots'])


def artifacts(preview):
    return {'bindings': [{**w.json(), 'function': value.hex()} for w, value in sorted(preview.bindings.items())],
            'assets': [{'identifier': a.identifier, 'data': a.data.hex(), 'metadata': a.metadata.hex()}
                       for a in preview.assets]}


def prepare(io, profile):
    before = probe.snapshot(state.ReadBudget(io))
    inventory = catalog(io)
    preview = plan(profile, before, inventory)
    if preview.issues:
        raise ProtocolError('; '.join(preview.issues))
    return {'version': 1, 'kind': KIND, 'status': 'prepared-read-only', 'before': before,
            'catalog_before': inventory, 'profile': profile.json(), 'artifacts': artifacts(preview),
            'validation_pending': preview.validation_pending, 'warnings': preview.warnings,
            'original_state_restored': False}


def validate(document):
    try:
        if type(document['version']) is not int or document['version'] != 1 or document['kind'] != KIND:
            raise ValueError('Unknown profile transaction')
        probe.validate_snapshot(document['before'])
        preview = plan(Profile.parse(document['profile']), document['before'], document['catalog_before'])
        if preview.issues or artifacts(preview) != document['artifacts']:
            raise ValueError('Profile artifacts differ from their compiled source')
        return preview
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ProtocolError('Invalid native profile transaction: ' + str(error)) from error


def recovery(document, preview):
    old = originals(document['before'])
    groups = {(w.bank, w.control) for w, target in preview.bindings.items() if old[w][3:] != target}
    return {'version': 1, 'product': 0xE8, 'serial': document['before']['serial'],
            'entries': [{**w.json(), 'before': old[w][3:].hex(), 'after': preview.bindings[w].hex(),
                         'reply_flag_before': old[w][2]}
                        for w in sorted(old) if (w.bank, w.control) in groups]}


def ensure_recovery(path, expected):
    if path.exists():
        stored = read_journal(path)
        if any(stored.get(k) != v for k, v in expected.items()):
            raise ProtocolError('Binding recovery differs from parent profile originals')
    else:
        durable_json(path, expected)


def verify_asset(io, asset):
    if (memory.data_size(io, asset.identifier) != len(asset.data)
            or memory.read_name(io, asset.identifier) != asset.metadata
            or memory.read_data(io, asset.identifier, len(asset.data)) != asset.data):
        raise ProtocolError(f'Native macro {asset.identifier} ownership/data readback mismatch')


def restore(io, document, path):
    preview = validate(document)
    document['original_state_restored'] = False
    state.guard(io, document['before'])
    expected = recovery(document, preview)
    changed = False
    for entry in expected['entries']:
        current = io.read_binding_record(entry['bank'], entry['control'], entry['layer'])
        if current[3:].hex() not in (entry['before'], entry['after']):
            raise ProtocolError('An affected binding changed externally; refusing to overwrite it')
        changed |= current.hex() != (bytes((entry['bank'], entry['control'], entry['reply_flag_before']))
                                      + bytes.fromhex(entry['before'])).hex()
    recovery_path = path.with_name('profile-binding-recovery.json')
    if changed:
        ensure_recovery(recovery_path, expected)
        Programmer(io, recovery_path, document['before']['serial'], set(document['before']['controls'])).restore()
    current = probe.snapshot(state.ReadBudget(io))
    if probe.normalized(current) != probe.normalized(document['before']):
        raise ProtocolError('Protected state changed; no native objects deleted')
    inventory = catalog(io)
    old_ids = set(document['catalog_before']['ids'])
    owned = {a.identifier for a in preview.assets}
    if not old_ids <= set(inventory['ids']) or set(inventory['ids']) - old_ids - owned:
        raise ProtocolError('External macro catalog change; no native objects deleted')
    failures = []
    for asset in preview.assets:
        if asset.identifier not in inventory['ids']:
            continue
        try:
            if asset.identifier in referenced_ids(current):
                raise ProtocolError('A binding still references a new macro')
            verify_asset(io, asset)
            document.update(status='deleting-owned-unreferenced-asset', deleting_id=asset.identifier)
            durable_json(path, document)
            state.guard(io, document['before'])
            io._exchange(memory.delete(asset.identifier))
        except (OSError, ValueError) as error:
            failures.append(str(error))
    document['catalog_after'] = catalog(io)
    if failures or set(document['catalog_after']['ids']) != old_ids:
        raise ProtocolError('Native profile recovery incomplete: ' + '; '.join(failures))
    document['after'] = probe.snapshot(state.ReadBudget(io))
    if probe.normalized(document['after']) != probe.normalized(document['before']):
        raise ProtocolError('Original profile state did not verify after cleanup')
    document['original_state_restored'] = True


def apply(io, prepared, path, *, stopped=lambda: False):
    """Leave a verified saved profile in place, retaining explicit undo data.

    This experimental entry point does not clear physical validation gates or
    enable production Save to Mouse. No command-line/hardware runner uses it.
    """
    preview = validate(prepared)
    if prepared.get('status') != 'prepared-read-only' or path.exists() or path.with_name('profile-bindings.json').exists():
        raise ProtocolError('Fresh profile preparation/journal required')
    if probe.normalized(probe.snapshot(state.ReadBudget(io, stopped))) != probe.normalized(prepared['before']):
        raise ProtocolError('Mouse changed since profile preparation')
    if catalog(io) != prepared['catalog_before']:
        raise ProtocolError('Macro catalog changed since profile preparation')
    document = deepcopy(prepared)
    document['status'] = 'armed'
    durable_json(path, document)
    ensure_recovery(path.with_name('profile-binding-recovery.json'), recovery(document, preview))
    try:
        def send(command, phase):
            if stopped(): raise InterruptedError('Native profile save cancelled')
            state.guard(io, document['before'])
            document['status'] = phase
            durable_json(path, document)
            io._exchange(command)
        for asset in preview.assets:
            send(memory.allocate(asset.identifier, len(asset.data)), f'allocating-{asset.identifier}')
            for raw, size, builder, name in ((asset.metadata, memory.NAME_CHUNK, memory.name_chunk, 'metadata'),
                                             (asset.data, memory.CHUNK_SIZE, memory.memory_chunk, 'events')):
                for offset in range(0, len(raw), size):
                    send(builder(asset.identifier, offset, raw[offset:offset + size]),
                         f'uploading-{asset.identifier}-{name}-{offset}')
            verify_asset(io, asset)
        wanted = set(prepared['catalog_before']['ids']) | {a.identifier for a in preview.assets}
        if set(catalog(io)['ids']) != wanted:
            raise ProtocolError('Unexpected catalog after profile assets upload')
        if probe.normalized(probe.snapshot(state.ReadBudget(io, stopped))) != probe.normalized(prepared['before']):
            raise ProtocolError('Asset upload changed protected state')
        if stopped(): raise InterruptedError('Native profile save cancelled')
        document['status'] = 'saving-profile-bindings'
        durable_json(path, document)
        Programmer(io, path.with_name('profile-bindings.json'), prepared['before']['serial'],
                   set(prepared['before']['controls'])).apply(preview.bindings)
        for where, target in preview.bindings.items():
            if io.read_binding(where.bank, where.control, where.layer) != target:
                raise ProtocolError('Saved profile binding did not verify')
            if io.read_binding(0, where.control, where.layer) != target:
                raise ProtocolError('Active profile binding did not verify')
        for asset in preview.assets: verify_asset(io, asset)
        after = probe.snapshot(state.ReadBudget(io))
        expected = deepcopy(prepared['before'])
        for field in ('records', 'all_records'):
            for entry in expected[field]:
                where = Location(1 if entry['bank'] == 0 else entry['bank'], entry['control'], entry['layer'])
                if where in preview.bindings:
                    entry['raw'] = entry['raw'][:6] + preview.bindings[where].hex()
        if probe.normalized(after) != probe.normalized(expected):
            raise ProtocolError('Profile save changed unrelated protected state')
        document.update(status='saved-readback-verified', saved_state=after)
        durable_json(path, document)
        return document
    except BaseException as failure:
        document['failure'] = str(failure) or type(failure).__name__
        try:
            restore(io, document, path)
            document['status'] = 'failed-restored'
        except BaseException as recovery_error:
            document.update(status='recovery-required', recovery_error=str(recovery_error))
        try: durable_json(path, document)
        except OSError: pass  # Initial originals/recovery are already durable.
        raise


def undo(io, path):
    """Recover/undo a saved or interrupted profile from its durable originals."""
    document = read_journal(path)
    validate(document)
    try:
        restore(io, document, path)
        document['status'] = 'restored-readback-verified'
        document.pop('recovery_error', None)
        durable_json(path, document)
        return document
    except BaseException as error:
        document.update(status='recovery-required', recovery_error=str(error))
        try: durable_json(path, document)
        except OSError: pass
        raise
