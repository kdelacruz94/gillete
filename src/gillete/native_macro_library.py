"""Bounded inert fingerprints for existing dependencies and byte-exact reuse."""

from hashlib import sha256
import time

from .dpi_probe import ReadBudget
from . import macro_memory as memory
from .macro_reads import MAX_IDS, MAX_MACRO_BYTES
from .native_macro_plan import MacroAsset
from .protocol import ProtocolError


class LibraryReads(ReadBudget):
    def __init__(self, io, stopped=lambda: False):
        super().__init__(io, stopped)
        self.remaining, self.deadline = 8192, time.monotonic() + 240


def fingerprint(io, identifier, *, metadata=None):
    size = memory.data_size(io, identifier)
    raw_name = memory.read_name(io, identifier) if metadata is None else metadata
    data = memory.read_data(io, identifier, size)
    return {'id': identifier, 'metadata': raw_name.hex(), 'size': size, 'sha256': sha256(data).hexdigest()}


def validate(entries, catalog_ids):
    try:
        if not isinstance(entries, list) or len(entries) > MAX_IDS:
            raise ValueError('Invalid library snapshot size')
        seen = set()
        for entry in entries:
            if (set(entry) != {'id', 'metadata', 'size', 'sha256'} or type(entry['id']) is not int
                    or entry['id'] not in catalog_ids or entry['id'] in seen
                    or type(entry['size']) is not int or not 1 <= entry['size'] <= MAX_MACRO_BYTES
                    or len(bytes.fromhex(entry['metadata'])) != 250
                    or len(entry['sha256']) != 64 or len(bytes.fromhex(entry['sha256'])) != 32):
                raise ValueError('Invalid library fingerprint')
            seen.add(entry['id'])
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise ProtocolError('Invalid native macro library snapshot') from error


def reusable(entries, templates):
    result = []
    for entry in entries:
        for asset in templates:
            if (entry['metadata'] == asset.metadata.hex() and entry['size'] == len(asset.data)
                    and entry['sha256'] == sha256(asset.data).hexdigest()):
                result.append(MacroAsset(entry['id'], asset.guid, asset.name, asset.data, asset.metadata,
                                         asset.items, asset.allocation_bytes, True))
                break
    return result


def capture(io, catalog_ids, templates, required_ids):
    reads = LibraryReads(io)
    expected_metadata = {a.metadata for a in templates}
    entries = []
    for identifier in sorted(catalog_ids):
        name = memory.read_name(reads, identifier)
        if identifier in required_ids or name in expected_metadata:
            entries.append(fingerprint(reads, identifier, metadata=name))
    return entries


def verify(io, entries, *, stopped=lambda: False):
    reads = LibraryReads(io, stopped)
    for entry in entries:
        if fingerprint(reads, entry['id']) != entry:
            raise ProtocolError(f'Existing native macro {entry["id"]} changed; no dependency overwrite is permitted')
