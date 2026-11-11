"""Pure native macro asset previews; not connected to production programming.

The caller supplies a complete catalog and references from all mouse banks.
Every planned object is new; no existing ID is overwritten or reclaimed.
Execution still needs an asset-aware transaction and hardware acceptance.
"""

from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from .compile_onboard import SoftwareOnly, compile_profile, encode_action
from .macro_reads import MAX_ID, MAX_IDS
from .model import MODELS
from .native_macro import compile_macro, metadata
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


@dataclass
class MacroProfilePreview:
    bindings: dict
    assets: tuple[MacroAsset, ...]
    issues: list[str]
    warnings: list[str]
    validation_pending: list[str]

    @property
    def required_bytes(self):
        return sum(asset.allocation_bytes for asset in self.assets)


def _ids(values, *, references=False):
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ProtocolError('Macro IDs must be an explicit collection')
    if (len(values) > (948 if references else MAX_IDS)
            or any(type(value) is not int or not (0 if references else 1) <= value <= MAX_ID for value in values)
            or len(set(values)) != len(values)):
        raise ProtocolError('Invalid, duplicate or oversized macro ID inventory')
    return set(values)


def preview_profile(profile, product, bank, baseline, *, catalog_ids, referenced_ids,
                    available_bytes, slot_capacity):
    """Compile a dependency preview without changing the profile or hardware.

    `referenced_ids` must include every normal/HyperShift binding, even unknown
    controls and unassigned banks. Zero references are preserved, never allocated.
    This return type deliberately has no writable/apply interface.
    """
    if type(product) is not int or product != 0xE8:
        raise ProtocolError('Native macro asset planning currently requires the verified V3 receiver')
    catalog = _ids(catalog_ids)
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
            identifier = next((value for value in range(1, MAX_ID + 1) if value not in reserved), None)
            if identifier is None:
                raise SoftwareOnly('No fresh unreferenced native macro ID remains')
            reserved.add(identifier)
            digest = sha256(compiled.data).hexdigest()
            guid = str(uuid5(NAMESPACE_URL, f'org.gillete/macro/{profile.id}/{digest}/{compiled.items}'))
            # Truncate on a character boundary, leaving room for a useful suffix.
            prefix = profile.name.encode('utf-8')[:80].decode('utf-8', errors='ignore')
            name = f'{prefix} macro {len(assets) + 1}'
            assets[key] = MacroAsset(identifier, guid, name, compiled.data,
                                     metadata(compiled, guid, name), compiled.items, compiled.allocation_bytes)
        if action.playback != 'once':
            pending.append('Native count/held/toggle playback and cancellation need hardware validation.')
        if action.kind == 'macro' and action.playback == 'count':
            warnings.append(f'Counted native playback includes its {compiled.trailing_gap_ms}-ms gap '
                            'after the final iteration; software playback omits that final gap.')
        if sum(step.kind == 'down' for step in action.steps) > 1:
            pending.append('Multi-key native macro sequencing needs hardware validation.')
        return compiled.binding(assets[key].identifier)

    model = MODELS[1]
    plan = compile_profile(profile, model, bank, baseline, encoder=encode)
    result = MacroProfilePreview(plan.targets, tuple(assets.values()), list(plan.issues),
                                 list(dict.fromkeys(warnings)), [])
    if len(catalog) + len(result.assets) > min(slot_capacity, MAX_IDS):
        result.issues.append('Planned macros exceed native slot capacity or the readable catalog limit.')
    if result.required_bytes > available_bytes:
        result.issues.append(f'Native macros require {result.required_bytes} already-free bytes; '
                             f'only {available_bytes} are available. No format or defragmentation is planned.')
    identifiers = {asset.identifier for asset in result.assets}
    if any(where.layer == 1 and function[0] in (3, 4, 5)
           and int.from_bytes(function[2:4], 'big') in identifiers for where, function in result.bindings.items()):
        pending.append('Native HyperShift macro execution needs hardware validation.')
    if len(result.assets) > 1:
        pending.append('Multiple native macro assets and shared references need hardware validation.')
    if result.assets:
        pending.append('Production Save to Mouse needs an asset-aware upload and recovery transaction.')
    result.validation_pending = list(dict.fromkeys(pending))
    return result
