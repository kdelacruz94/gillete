# Managed native macro storage

2026-11-10. Implemented and verified offline on simulated devices and native Qt
widgets. No live cleanup or mouse mutation was performed. User-directed hardware
testing remains deferred. The existing accepted V3 delete primitive is reused;
this integrated UI/history workflow still needs live acceptance.

The mouse-memory panel enables **Manage native macro storage…** after a V3 E8,
firmware1.1 read with slot1 active and solely assigned. Review is read-only. It
uses the selected-mouse ownership preflight, then rediscovers and exclusively
opens the transport. A running idle service or another enabled mouse is allowed.
Starting/stopping/active/pending sessions for this model block access.

## Ownership and selection

`native_history` scans only `native-*/profile.json` beneath the app's configured
onboard state directory. It hashes every discovered receipt and validates the
matching unit's compiled native artifacts. Only finished receipts can establish
ownership; interrupted saves need recovery first. Foreign units supply no owned
objects. Missing, corrupt, linked or oversized receipts cannot authorize cleanup.
The scan is bounded to256 receipts,1MiB each and20seconds between file checks;
older history may be archived manually outside that namespace. No receipt is
rewritten, removed or automatically archived.

`native_cleanup.prepare` captures all reported controls in all six banks, both
layers, selector-zero DPI, settings and profile identity. Every macro-reference
family03/04/05/0f protects its referenced object, including unknown controls,
unassigned banks and active mirrors. Referenced objects cannot be selected.

For catalog IDs matching an uploaded artifact from a validated receipt, review
reads complete metadata and event data and compares the bytes exactly. A name,
UUID prefix or ID alone is insufficient. Changed objects remain unselectable;
communication failure aborts review instead of being mistaken for a mismatch.
Unmanaged IDs are listed but their bodies need not be read or interpreted.

The table starts with nothing selected. It lists affected original catalogs and
mapping dependencies, profile names and recovery paths. A separate acknowledgement
is required if selected deletion can affect those originals; it resets whenever
the selection changes. Copies of receipts outside the managed directory may
also depend on those objects. This is explicit abandonment of that original data,
not a promise that old journals will remain restorable after pruning.

## Deletion and interruption

Apply reconstructs the entire preview from live state and validated local
history. A stale or forged selection, changed mappings/settings, changed body,
new/modified receipt or catalog change blocks initial admission. Before every
delete it takes another complete reference/protected-state snapshot, checks
history fingerprints and catalog geometry/IDs, independently checks metadata/data,
and verifies identity, firmware, normal mode and assigned profiles. The app's
exclusive HID lock excludes cooperating writers; this is not a firmware-atomic
transaction against arbitrary noncooperating external writers.

A new private1MiB-bounded receipt reaches durable storage before the first SET.
It includes the exact selected metadata/event bytes and original protected state.
Each delete intent is durable before submission, with cancellation checked again
after that write. Only class06/op03 deletion is sent; no binding, mode, DPI,
format, defragmentation or upload command is issued. Every deletion and the
final protected-state/catalog result are read back. The receipt records confirmed
deleted IDs and whether mappings/settings verified unchanged.

The asynchronous progress window supports Stop. Cancellation, disk failure,
changed state or an uncertain reply stops remaining deletions. The error path
attempts a fresh read-only catalog observation and records absent selected IDs;
it never repeats a delete. Interrupted cleanup receipts are not resume authority.
Reopen storage review to choose remaining objects against their current state.
The cleanup file's full bytes are evidence, not an automatic re-upload/undo API.

Deleting an unused object frees its catalog slot but can leave its bytes in the
reported reclaimable pool. The UI reports actual already-free and reclaimable
values separately. It does not promise immediate byte reclamation or bypass the
native-save requirement for sufficient already-free space. Safe compaction remains
a separate protocol/acceptance requirement.

Offline checks cover shared/active/unassigned references, modified/foreign
objects, old undo dependencies, acknowledgement, source/state/catalog changes,
disk failures, lost deletion replies, cancellation at durable intent and between
objects, exact private backups, UI cancellation and worker sequencing. Live
acceptance must still verify the selected deletion, unchanged active mappings,
observed storage counters and interrupted-operation handling on the user's unit.
