"""Opt-in V3 receiver macro experiment; allocation/binding require user approval.

No production capability is enabled. Never formats storage, overwrites a macro,
or retries an uncertain upload. Incomplete objects without verified ownership
remain journaled for investigation rather than being deleted speculatively.
"""

import argparse
from copy import deepcopy
import math
from pathlib import Path
import secrets
from uuid import uuid4

from . import dpi_probe as base
from . import macro_memory as memory
from .hardware import read_journal, transport
from .hid import BindingHID
from .macro_reads import catalog, validate_request
from .model import Action, Step
from .native_macro import compile_macro, metadata
from .onboard import Location, Programmer, durable_json
from .protocol import ProtocolError
from .service import socket_path


KIND = 'v3-native-macro-experiment'
ACTION = Action('macro', steps=(Step('down', 'KEY_F24'), Step('wait', milliseconds=80), Step('up', 'KEY_F24')))
NAME = 'Gillete F24 validation'
CONTROL = 0x4B


class MacroHID(BindingHID):
    def execute(self, command):
        if command.category == 6:
            validate_request(command)
            return self._exchange(command)
        return super().execute(command)


def open_mouse():
    discovered = transport(base.connected(0xE8))
    return MacroHID(discovered.path, 0xE8)


def snapshot(io):
    state = base.capture(io)
    if state['product'] != 0xE8 or state['assigned'] != [1] or state['active'] != 1:
        raise ProtocolError('First native macro experiment requires V3 receiver with only bank 1 assigned')
    # Include even unassigned banks and unknown controls when checking references.
    state['all_records'] = [{**Location(bank, control, layer).json(),
                             'raw': io.read_binding_record(bank, control, layer).hex()}
                            for bank in range(6) for control in state['controls'] for layer in (0, 1)]
    validate_snapshot(state)
    base.guard(io, state)
    return state


def validate_snapshot(state):
    base.validate_state(state)
    if state['product'] != 0xE8 or state['assigned'] != [1] or state['active'] != 1:
        raise ProtocolError('Unsupported native macro experiment profile inventory')
    wanted = {(b, c, l) for b in range(6) for c in state['controls'] for l in (0, 1)}
    seen = {}
    try:
        for entry in state['all_records']:
            key = tuple(entry[n] for n in ('bank', 'control', 'layer'))
            raw = bytes.fromhex(entry['raw'])
            if (any(type(v) is not int for v in key) or key not in wanted or key in seen
                    or len(raw) != 10 or raw[:2] != bytes(key[:2]) or raw[2] not in (0, 1)):
                raise ValueError('Invalid complete binding record')
            seen[key] = raw.hex()
        if set(seen) != wanted or any(seen[tuple(e[n] for n in ('bank', 'control', 'layer'))] != e['raw']
                                     for e in state['records']):
            raise ValueError('Incomplete or inconsistent binding snapshot')
    except (KeyError, TypeError, ValueError) as error:
        raise ProtocolError('Invalid macro snapshot') from error


def normalized(state):
    result = base.stable_state(state)
    result['all_records'] = sorted((r['bank'], r['control'], r['layer'], r['raw'][6:])
                                   for r in state['all_records'])
    return result


def references(state, identifier):
    for entry in state['all_records']:
        function = bytes.fromhex(entry['raw'])[3:]
        if function[0] in (3, 4, 5) and int.from_bytes(function[2:4], 'big') == identifier:
            return True
    return False


def prepare_document(io):
    before = snapshot(base.ReadBudget(io))
    inventory = catalog(io)
    compiled = compile_macro(ACTION)
    if inventory['ids'] or inventory['available_bytes'] < compiled.allocation_bytes or inventory['slots'] < 1:
        raise ProtocolError('First macro test requires an empty catalog and already-free storage; no defragmentation')
    for _ in range(128):
        identifier = secrets.randbelow(32767) + 1
        if not references(before, identifier):
            break
    else:
        raise ProtocolError('Could not choose an unreferenced fresh macro ID')
    guid = str(uuid4())
    return {'version': 1, 'kind': KIND, 'status': 'prepared-read-only', 'before': before,
            'catalog_before': inventory, 'identifier': identifier, 'guid': guid,
            'action': ACTION.json(), 'name': NAME, 'data': compiled.data.hex(),
            'metadata': metadata(compiled, guid, NAME).hex(), 'binding': compiled.binding(identifier).hex(),
            'original_state_restored': False, 'native_playback_verified': False}


def validate(document):
    try:
        if type(document['version']) is not int or document['version'] != 1 or document['kind'] != KIND:
            raise ValueError('Unknown macro journal')
        validate_snapshot(document['before'])
        compiled = compile_macro(ACTION)
        if (document['action'] != ACTION.json() or document['name'] != NAME
                or document['data'] != compiled.data.hex()
                or document['metadata'] != metadata(compiled, document['guid'], NAME).hex()
                or document['binding'] != compiled.binding(document['identifier']).hex()
                or references(document['before'], document['identifier'])):
            raise ValueError('Prepared artifact does not match the bounded F24 experiment')
        baseline = document['catalog_before']
        if (baseline['ids'] != [] or baseline['count'] != 0 or baseline['slots'] < 1
                or baseline['available_bytes'] < compiled.allocation_bytes):
            raise ValueError('Invalid empty-catalog baseline')
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ProtocolError('Invalid native macro journal: ' + str(error)) from error


def verify_object(io, document):
    identifier = document['identifier']
    if (memory.data_size(io, identifier) != len(bytes.fromhex(document['data']))
            or memory.read_name(io, identifier).hex() != document['metadata']
            or memory.read_data(io, identifier, len(bytes.fromhex(document['data']))).hex() != document['data']):
        raise ProtocolError('Native macro metadata/data did not match independent readback')


def restore(io, document, path):
    """Restore bindings before deleting; retain uncertain allocations as evidence."""
    validate(document)
    document['original_state_restored'] = False
    base.guard(io, document['before'])
    originals = {Location(e['bank'], e['control'], e['layer']): bytes.fromhex(e['raw'])
                 for e in document['before']['all_records'] if e['bank'] == 1 and e['control'] == CONTROL}
    candidate = bytes.fromhex(document['binding'])
    changed = False
    for where, raw in originals.items():
        current = io.read_binding_record(where.bank, where.control, where.layer)
        if current[3:] not in (raw[3:], candidate) or (where.layer == 1 and current[3:] != raw[3:]):
            raise ProtocolError('Side 12 changed outside this experiment; refusing to overwrite it')
        changed |= current != raw
    if changed:
        # Rebuild recovery solely from validated parent originals, never trust a
        # partially written secondary binding journal to select restore bytes.
        binding_path = path.with_name('binding-recovery.json')
        recovery = {'version': 1, 'product': 0xE8, 'serial': document['before']['serial'],
                    'entries': [{**w.json(), 'before': raw[3:].hex(), 'after': raw[3:].hex(),
                                 'reply_flag_before': raw[2]} for w, raw in originals.items()]}
        durable_json(binding_path, recovery)
        Programmer(io, binding_path, document['before']['serial'], set(document['before']['controls'])).restore()
    current = snapshot(base.ReadBudget(io))
    if normalized(current) != normalized(document['before']):
        raise ProtocolError('Original settings/bindings differ; no macro deletion attempted')
    inventory = catalog(io)
    if set(inventory['ids']) - {document['identifier']}:
        raise ProtocolError('Macro catalog changed outside this experiment; no deletion attempted')
    if document['identifier'] in inventory['ids']:
        if references(current, document['identifier']):
            raise ProtocolError('A binding still references the test macro; no deletion attempted')
        # Full bytes prove ownership. Allocation ACK loss before UUID upload is
        # deliberately left unresolved, even though the ID was previously free.
        verify_object(io, document)
        document['status'] = 'deleting-owned-unreferenced-macro'
        durable_json(path, document)
        base.guard(io, document['before'])
        io._exchange(memory.delete(document['identifier']))
    after_catalog = catalog(io)
    baseline = document['catalog_before']
    if (after_catalog['ids'] or after_catalog['slots'] != baseline['slots']
            or after_catalog['maximum_bytes'] != baseline['maximum_bytes']):
        raise ProtocolError('Macro deletion did not verify')
    document['catalog_after'] = after_catalog
    # Deletion can leave reclaimable blocks; record counters without formatting.
    document['after'] = snapshot(base.ReadBudget(io))
    if normalized(document['after']) != normalized(document['before']):
        raise ProtocolError('Complete original state did not verify after cleanup')
    document['original_state_restored'] = True


def exercise(io, prepared, path, observe, *, ready=lambda: None, stopped=lambda: False):
    validate(prepared)
    if prepared.get('status') != 'prepared-read-only' or path.exists() or path.with_name('binding.json').exists():
        raise ProtocolError('Fresh preparation and run journal required')
    if normalized(snapshot(base.ReadBudget(io, stopped))) != normalized(prepared['before']):
        raise ProtocolError('Mouse changed since preparation')
    if catalog(io) != prepared['catalog_before']:
        raise ProtocolError('Macro catalog changed since preparation')
    document = deepcopy(prepared)
    document['status'] = 'armed'
    durable_json(path, document)
    fatal = None
    try:
        def send(command, phase):
            if stopped():
                raise InterruptedError('Native macro test cancelled')
            base.guard(io, document['before'])
            document['status'] = phase
            durable_json(path, document)
            io._exchange(command)  # Exactly one SET attempt, including ACK loss.
        identifier = document['identifier']
        send(memory.allocate(identifier, len(bytes.fromhex(document['data']))), 'allocating')
        for field, chunk_size, builder in [('metadata', memory.NAME_CHUNK, memory.name_chunk),
                                            ('data', memory.CHUNK_SIZE, memory.memory_chunk)]:
            raw = bytes.fromhex(document[field])
            for offset in range(0, len(raw), chunk_size):
                send(builder(identifier, offset, raw[offset:offset + chunk_size]), f'uploading-{field}-{offset}')
        verify_object(io, document)
        if catalog(io)['ids'] != [identifier]:
            raise ProtocolError('Unexpected catalog after upload')
        if normalized(snapshot(base.ReadBudget(io, stopped))) != normalized(document['before']):
            raise ProtocolError('Upload changed protected mouse settings')
        document['status'] = 'binding-side-12'
        durable_json(path, document)
        Programmer(io, path.with_name('binding.json'), document['before']['serial'],
                   set(document['before']['controls'])).apply({Location(1, CONTROL, 0): bytes.fromhex(document['binding'])})
        if io.read_binding(0, CONTROL, 0).hex() != document['binding']:
            raise ProtocolError('Active binding did not mirror the stored macro binding')
        document['status'] = 'awaiting-key-observation'
        durable_json(path, document)
        ready()
        observation = observe(stopped)
        if (not isinstance(observation, dict) or set(observation) != {'f24_down', 'f24_up', 'hold_ms'}
                or any(type(observation[k]) is not bool for k in ('f24_down', 'f24_up'))
                or type(observation['hold_ms']) not in (int, float)
                or not math.isfinite(observation['hold_ms']) or not 0 <= observation['hold_ms'] <= 180000):
            raise ProtocolError('Expected explicit F24 press/release observations and measured duration')
        document['observation'] = observation
        document['native_playback_verified'] = observation['f24_down'] and observation['f24_up']
        if not document['native_playback_verified']:
            raise ProtocolError('Native F24 playback was not observed')
    except BaseException as error:
        document['experiment_error'] = str(error) or type(error).__name__
        if not isinstance(error, Exception): fatal = error
    finally:
        try:
            restore(io, document, path)
        except BaseException as error:
            document['recovery_error'] = str(error) or type(error).__name__
            if not isinstance(error, Exception): fatal = error
        document['status'] = ('recovery-required' if not document['original_state_restored'] else
                              'test-failed-restored' if document.get('experiment_error') else 'native-macro-restored')
        durable_json(path, document)
    if fatal: raise fatal
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'run', 'recover'))
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    directory = args.directory
    try:
        if socket_path().exists():
            raise ProtocolError('Stop the Gillete service before an isolated macro test')
        if args.operation == 'prepare':
            if directory.exists(): raise ProtocolError('Choose a fresh experiment directory')
            with open_mouse() as io: document = prepare_document(io)
            directory.mkdir(parents=True, mode=0o700)
            durable_json(directory / 'prepared.json', document)
        elif args.operation == 'run':
            prepared = read_journal(directory / 'prepared.json')
            root = directory / 'run'
            root.mkdir(mode=0o700)
            # No input grab or injection: the observer opens only this V3's
            # keyboard evdev interface and records F24 transitions.
            from .native_macro_observer import Observer
            with base.cancellation() as stopped, Observer(base.connected(0xE8)) as observer, open_mouse() as io:
                def ready():
                    observer.arm()
                    print('READY: tap V3 side 12 once. Native F24 macro active; '
                          'restores after press/release or 180 seconds.', flush=True)
                document = exercise(io, prepared, root / 'journal.json', observer.observe, stopped=stopped,
                                    ready=ready)
        else:
            path = directory / 'run/journal.json'
            document = read_journal(path)
            with open_mouse() as io: restore(io, document, path)
            document['status'] = 'recovered-original-state'
            durable_json(path, document)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Native macro experiment: {document["status"]}', flush=True)
    for field in ('experiment_error', 'recovery_error'):
        if document.get(field): print(document[field], flush=True)
    return 0 if document['status'] in ('prepared-read-only', 'native-macro-restored', 'recovered-original-state') else 1


if __name__ == '__main__':
    raise SystemExit(main())
