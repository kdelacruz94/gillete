"""Pure native macro asset previews; writes belong to the transaction layer.

The caller supplies a complete catalog and references from all mouse banks.
Existing byte-identical objects may be reused; no existing ID is overwritten.
Execution belongs to the asset-aware transaction and its capability gates.
"""

from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from .compile_onboard import SoftwareOnly, compile_profile, encode_action
from .macro_reads import MAX_ID, MAX_IDS
from .model import MODELS
from .native_macro import compile_macro, metadata
from .native_profile_support import action_issue
from .protocol import ProtocolError


@dataclass(frozen=True)
class MacroAsset:
    identifier: int
    guid: str
    name: str
    data: bytes
    metadata: bytes
    items: int
    allocation_bytes: int
    reused: bool = False


@dataclass
class MacroProfilePreview:
    bindings: dict
    assets: tuple[MacroAsset, ...]
    issues: list[str]
    warnings: list[str]
    validation_pending: list[str]

    @property
    def required_bytes(self):
        return sum(asset.allocation_bytes for asset in self.uploads)

    @property
    def uploads(self):
        return tuple(asset for asset in self.assets if not asset.reused)


def _ids(values, *, references=False):
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ProtocolError('Macro IDs must be an explicit collection')
    if (len(values) > (948 if references else MAX_IDS)
            or any(type(value) is not int or not (0 if references else 1) <= value <= MAX_ID for value in values)
            or len(set(values)) != len(values)):
        raise ProtocolError('Invalid, duplicate or oversized macro ID inventory')
    return set(values)


def preview_profile(profile, product, bank, baseline, *, catalog_ids, referenced_ids,
                    available_bytes, slot_capacity, reusable=()):
    """Compile a dependency preview without changing the profile or hardware.

    `referenced_ids` must include every normal/HyperShift binding, even unknown
    controls and unassigned banks. Zero references are preserved, never allocated.
    This return type deliberately has no writable/apply interface.
    """
    if type(product) is not int or product != 0xE8:
        raise ProtocolError('Native macro asset planning currently requires the verified V3 receiver')
    catalog = _ids(catalog_ids)
    if (len(reusable) > MAX_IDS or any(not isinstance(a, MacroAsset) or a.identifier not in catalog for a in reusable)
            or len({a.identifier for a in reusable}) != len(reusable)):
        raise ProtocolError('Invalid native macro reuse inventory')
    reserved = catalog | _ids(referenced_ids, references=True)
    if (type(available_bytes) is not int or not 0 <= available_bytes <= 64 * 1024 * 1024
            or type(slot_capacity) is not int or not 1 <= slot_capacity <= 65535
            or len(catalog) > slot_capacity):
        raise ProtocolError('Invalid native macro storage inventory')
    if any(not isinstance(value, bytes) or len(value) != 7 for value in baseline.values()):
        raise ProtocolError('Native macro preview requires raw seven-byte baseline bindings')
    assets, warnings, pending = {}, [], []

    def encode(action, model):
        if action.kind not in ('macro', 'turbo'):
            return encode_action(action, model)
        compiled = compile_macro(action)
        key = (compiled.data, compiled.items)
        if key not in assets:
            digest = sha256(compiled.data).hexdigest()
            guid = str(uuid5(NAMESPACE_URL, f'org.gillete/macro/{profile.id}/{digest}/{compiled.items}'))
            # Truncate on a character boundary, leaving room for a useful suffix.
            prefix = profile.name.encode('utf-8')[:80].decode('utf-8', errors='ignore')
            name = f'{prefix} macro {len(assets) + 1}'
            raw_metadata = metadata(compiled, guid, name)
            existing = next((a for a in sorted(reusable, key=lambda a: a.identifier)
                             if a.data == compiled.data and a.metadata == raw_metadata and a.items == compiled.items), None)
            identifier = existing.identifier if existing else next((value for value in range(1, MAX_ID + 1)
                                                                     if value not in reserved), None)
            if identifier is None:
                raise SoftwareOnly('No fresh unreferenced native macro ID remains')
            reserved.add(identifier)
            assets[key] = MacroAsset(identifier, guid, name, compiled.data,
                                     raw_metadata, compiled.items, compiled.allocation_bytes, existing is not None)
        if issue := action_issue(action):
            pending.append(issue)
        if action.kind == 'macro' and action.playback == 'count':
            warnings.append(f'Counted native playback includes its {compiled.trailing_gap_ms}-ms gap '
                            'after the final iteration; software playback omits that final gap.')
            warnings.append('Native counted playback runs to completion on the mouse; '
                            'focus-based cancellation requires Linux service playback.')
        return compiled.binding(assets[key].identifier)

    model = MODELS[1]
    plan = compile_profile(profile, model, bank, baseline, encoder=encode)
    result = MacroProfilePreview(plan.targets, tuple(assets.values()), list(plan.issues),
                                 list(dict.fromkeys(warnings)), [])
    if len(catalog) + len(result.uploads) > min(slot_capacity, MAX_IDS):
        result.issues.append('Planned macros exceed native slot capacity or the readable catalog limit.')
    if result.required_bytes > available_bytes:
        result.issues.append(f'Native macros require {result.required_bytes} already-free bytes; '
                             f'only {available_bytes} are available. No format or defragmentation is planned.')
    result.validation_pending = list(dict.fromkeys(pending))
    return result
