# Native macro validation

2026-11-10. The compiler and experiment pass offline checks. The user's V3
receiver has now physically accepted allocation, upload, counted-once F24
playback (83.001-ms measured hold for 80-ms requested delay) and cleanup.
The same macro and stored/active binding also survived the user's reported
off/on cycle, with 81.001-ms observed playback and complete cleanup afterward.
Shared once-only macro playback on normal/HyperShift sides11/12 has also been
observed; originals and the empty catalog were verified after recovery from
a malformed-reply cleanup error. The later combined experiment accepted once-only
keyboard sequences and counted single-key macros on the V3 receiver firmware1.1,
sole assigned active slot1. Held/toggle/turbo, counted multi-key, physical
F13–F23 desktop mapping and battery-removal retention remain unverified.
Keep stored software decoding now handles the accepted sequence/count families;
its combined live transition still needs acceptance. Later sections record the
individual results and gates.

## First-party wire findings

Preserved V3 protocol factory `7755` and storage engine `51294` distinguish
allocation command bytes from storage reservation: `06:08` carries the actual
serialized event length, while admission estimates
`ceil((event length + 256) / 256) * 256` bytes. Secondary OpenSynapse code uses
rounded blocks in that argument; Gillete follows the first-party builder and
caller pair.

| Command | Payload |
| --- | --- |
| `06:08` | ID:u16be, actual event length:u32be |
| `06:0c` | ID:u16be, metadata offset:u16be, total metadata length:u16be, at most 64 bytes |
| `06:09` | ID:u16be, data offset:u32be, chunk length:u8, at most 72 bytes |
| `06:8c` | ID:u16be, metadata offset:u16be, zeros through declared size `6+n` |
| `06:03` | ID:u16be |

Metadata reads verify ID, offset and complete response length without assuming
the two-byte size field means total or chunk size. Writes use total size 250.
The GUID has Windows mixed endianness (`UUID.bytes_le`); event count is
little-endian. New metadata contains the name and zeroed reserved fields;
existing metadata is never edited or reconstructed.

Source: [V3 official protocol bundle](https://apps.razer.com/synapse/products/231/mw/763.ba31528f9f94864c15b6.js),
factories `7755`, `51294`, event enumeration `41022`, mapping factory `56415`.
Manifests, original files, hashes and UTF-16 ranges remain in ignored
`evidence/synapse-official.local/desktop-web/231/`. See
[the source research](synapse-macro-turbo-research.md) for event formats and
the format/rebuild fallback explicitly excluded here.

## Compiler limits

`native_macro` compiles balanced keys/chords/delays, five-button mouse state
and vertical wheel notches. Bindings encode once, counts 1..255, held and
toggle. Turbo becomes a balanced sequence with press/inter-press delays.
Streams must fit 4096 bytes and decode without warnings or held inputs.
Cursor movement, horizontal wheel macros, unsupported/media keys and larger
counts remain software-only. Source compatibility is not firmware acceptance.

Repeated software macros put the interval between iterations. Native macros
encode it at the end of the body, including after the last counted iteration.
Future Save to Mouse previews must disclose this difference; the compiler
exposes `trailing_gap_ms`. Production integration must not silently equate the
schedules. Timing and firmware repetition/cancellation remain unverified.

## Exact first experiment

The opt-in `native_macro_probe` requires the verified V3 E8 receiver, normal
mode, bank 1 as the sole assigned bank, an empty catalog and adequate already-free
space. It captures identity, firmware, saved settings, selector-zero DPI and
every reported control in all six banks, including unknown controls and
unassigned banks.

The fixed action is F24 down, wait 80 ms, F24 up: `01 73 11 50 02 73`.
Three events, six event bytes, 512-byte reservation estimate, 250-byte metadata.
A fresh unreferenced nonzero 15-bit ID and UUID are selected. Only normal side
12 temporarily receives function `03`, that ID, repeat count 1. Its original
HyperShift assignment and reply metadata are retained. No mode/DPI change,
input grab, software injection, format or defragmentation is performed.

Before binding, independent getters must match all metadata/event bytes and
protected state. The observer reads only this V3's keyboard input, ignores
pre-READY events, requires F24 down/up on the same interface and records press
duration from monotonic event timestamps. It stops after press/release, 180
seconds, cancellation, event loss or an error. Physical execution and measured
duration are separate evidence. This first test does not establish persistence.

## Journal and recovery

Original state and compiled bytes reach private durable storage before the
first SET. Every allocation/chunk/delete phase is journaled before submission.
Uncertain upload SETs are never automatically resent. The existing Programmer
journals binding changes and preserves original normal/HyperShift functions
and reply flags.

The complete binding-recovery journal is also written before allocation.
Cleanup verifies its original values against the parent and reuses that
durable file. If the disk fills during observation, Programmer can still
restore the button even when subsequent journal updates fail. Macro deletion
then stops if its intent cannot be made durable, retaining an unbound object.

Cleanup restores side 12 first, then reads every bank/control, requires
protected-state equality, checks references/catalog ownership and verifies
all UUID/metadata/event bytes before deleting only the test object. External
assignments/settings or catalog additions stop deletion. An interrupted
allocation with incomplete/unverifiable data remains an unbound orphan with
recovery evidence; it needs investigation before another test. Storage may
become reclaimable after deletion; counters are recorded without compaction.

Recovery reconstructs the fixed artifact from the parent journal, verifies
hardware identity/mode and restores only this experiment's original button.
It does not trust partial secondary journals to choose restoration bytes.
A lost deletion ACK is resolved by a fresh catalog read; deletion is not
resent if the ID is gone. An external side-12 assignment is preserved.

Commands (prepare is read-only; run requires explicit approval for the new
macro-storage writes):

```sh
.venv/bin/python -m gillete.native_macro_probe prepare --directory evidence/v3-native-macro-01.local
.venv/bin/python -m gillete.native_macro_probe run --directory evidence/v3-native-macro-01.local
.venv/bin/python -m gillete.native_macro_probe recover --directory evidence/v3-native-macro-01.local
```

V2, wired V3, HyperShift macros, battery-removal retention, native repetition
and production multi-macro/profile dependency management require separate
acceptance. V2's disabled onboard macro feature remains a material boundary;
this experiment never writes to it.

## Prepared power-cycle follow-up

`prepare --power-cycle` selects a separate user-paced retention purpose with
the same exact F24 stream and single normal side-12 mapping. It uses a fresh
object and snapshot. After READY, the user switches the mouse off, waits two
seconds, switches it on, taps/releases side 12 and reports completing the
cycle. The keyboard observer still measures actual native F24 down/up.

During the same 180-second observation deadline, the run requires a private
`run/power-cycle-report.json` containing exactly `{"power_cycled": true}`.
The assistant writes that only after the user's explicit cycle report.
Then the run checks the catalog, complete metadata/event data and both
stored/active binding before restoring the original button and deleting the
test object. It records `power_cycle_retention_observed` only after those
checks. This is a human-reported off/on observation, not instrumented proof
of battery power loss or a particular NVM implementation.

The preparation command adds `--power-cycle`; run/recover use the prepared
directory without that option. Missing/negative/ambiguous reports, lost data,
changed bindings, event loss, cancellation or timeout cannot claim retention.
Incomplete or conflicting state retains the same conservative recovery rules.

## Focus-loss cancellation remains separate

The shared first-party protocol exposes methods named interruptible macro
settings, but their seven-byte commands are `02:ad` (get) and `02:2d` (set),
not class-06 stop-playback commands. The getter carries one numeric selector;
the setter carries three numeric values and up to four additional key IDs.
The retained V3 bundle provides no call site beyond those method definitions
that establishes their meaning for this mouse. A generic shared method is
insufficient evidence to send it or claim a Naga cancellation feature.

No explicit native stop-playback method was found in the retained macro
protocol/engine factories. This limited source search does not prove firmware
lacks one. Until hardware establishes cancellation, native toggled playback
must not be presented as satisfying the user's stop-on-focus-loss requirement.
The Linux Runner's cancellation applies to its own generated events; it cannot
be assumed to control autonomous firmware playback. Neither these new candidate
commands nor mode/profile changes are introduced as cancellation fallbacks.

## Profile dependency previews

`native_macro_plan.preview_profile` is a pure preview for the V3 receiver.
It consumes the current stored bindings, catalog IDs, references from all
banks, already-free bytes and slot capacity. Identical event streams share
one new asset, while each assignment retains its own playback/count binding.
Fresh IDs avoid both catalog entries and dangling references, including those
on unknown controls or unassigned banks. Existing objects are never overwritten.
The preview includes exact event/metadata bytes and a per-object block estimate.

Planning reuses the ordinary normal/HyperShift resolution and standalone
alternatives, preserving opaque passthrough assignments. It reports unsupported
actions and capacity/free-space failures without formatting or silently
substituting software actions. Names truncate at valid UTF-8 character
boundaries. Repeated playback's trailing-gap difference is explicit.

The preview separately lists remaining physical acceptance and production
integration requirements: HyperShift macros, multiple assets, multi-key
sequences, repetition/cancellation and an asset-aware upload/recovery backend.
It has no writable/apply API. The production compiler and Save to Mouse keep
their existing macro restrictions; this module is not yet connected to those
write paths. V2 and wired V3 are rejected by this experimental native planner.

## Asset-aware transaction implementation

`native_profile_transaction` now connects profile previews to durable allocation,
upload, binding and undo operations. It remains an experimental library with
no production GUI caller; no additional hardware acceptance is claimed. Its snapshot
contract currently requires the verified V3 receiver with bank1 solely assigned.
Supporting other assigned-slot arrangements still requires their validation.

Preparation captures the complete original state and current catalog, compiles
the profile and stores exact artifacts. Apply recompiles those artifacts,
rejects stale state/catalogs, and persists both the parent and original binding
recovery before any allocation. All new objects must independently read back
correctly before button references are saved. It then verifies active and stored
bindings, object data, and that unrelated state was preserved. Success leaves
the saved profile in place with explicit undo data.

Failure/undo restores affected normal/HyperShift groups before deleting new
objects. Existing catalog IDs are never deleted. Reference discovery includes
sequence-family `0f`, unknown controls and unassigned banks. Only fully matching
new metadata/event data can be deleted; ambiguous partial allocations retain
recovery evidence. Existing fully uploaded objects can be cleaned independently
of a partial second allocation. External catalog/binding/state changes block
unsafe cleanup. Lost upload ACKs are not retried. Undo resolves already absent
objects by reading the catalog and is repeatable without resending deletion.

Disk-full injection after binding confirms that already durable recovery still
restores the original button functions. New objects remain unbound when delete
intent cannot be journaled. The ordinary production Save to Mouse path continues
to block macros until this backend, acceptance gates and UI are connected.

## Concrete multi-asset / HyperShift experiment

`native_profile_probe` uses the asset-aware backend for a fixed reversible
experiment. Normal sides11/12 share an F24-down/80-ms/F24-up macro; their
HyperShift mappings share the corresponding F23 macro. It requires an empty
initial macro catalog and the existing ring-finger HyperShift action on both
layers. Exactly those four button mappings may differ; every other assignment,
including the trigger, must remain unchanged.

After READY, the requested order is side12, ring+side12, side11, ring+side11,
releasing each side button and the ring trigger before the next combination.
The read-only keyboard observer requires F24/F23/F24/F23 down/up in that order,
rejects overlapping keys/dropped events, and records each actual duration.
An independent user report is required: `run/sequence-report.json` must contain
exactly `{"sequence_completed": true}`. Key reports cannot identify physical
button labels, so this human confirmation remains separate evidence. The
assistant writes it only after the user confirms performing the full sequence.

The 180-second window starts at READY and includes that confirmation. Completion,
cancellation, timeout or failure calls durable undo, restores original functions
and flags, and removes only verified unreferenced new objects. Final evidence
is split between `run/experiment.json` (physical observation) and
`run/profile.json` (transaction/recovery). `recover` uses the latter to undo
an interrupted run. No service activation, mode change, input grab, key
injection, DPI write, formatting or defragmentation is part of this experiment.

```sh
.venv/bin/python -m gillete.native_profile_probe prepare --directory evidence/v3-native-profile-01.local
.venv/bin/python -m gillete.native_profile_probe run --directory evidence/v3-native-profile-01.local
.venv/bin/python -m gillete.native_profile_probe recover --directory evidence/v3-native-profile-01.local
```

The run requires new approval for uploading two native objects and changing
four saved mappings. A successful observation would establish this exact
two-asset/shared-reference/HyperShift case, without proving native repeating
modes, arbitrary multi-key sequences or V2/wired behavior.

### Physical result

The user confirmed the sequence on 2026-11-10. Actual F24/F23/F24/F23 holds
were about 82/83/82/81 ms, and objects plus saved state verified afterward.
The exact shared-reference/HyperShift case is physically accepted. Automatic
cleanup and the first fresh recovery encountered a report length/checksum error;
another fresh recovery verified complete original state and an empty catalog.
Initial errors remain in private evidence. Production write integration stays
gated pending communication/recovery robustness work; playback success does
not erase that reliability limitation.

## Desktop read-only review

Mouse memory offers Review native macro profile for the eligible V3 receiver
and slot1. A worker compares the inspected snapshot to fresh complete state
and catalog data before showing proposed mappings, shared objects, storage
admission and pending requirements. The dialog cannot save or activate anything.
Software control must be disabled, and stale inspection requires another mouse
read. Ordinary Save to Mouse compilation remains unchanged.

## Malformed replies and diagnostic receipts

The HID transport can discard a malformed reply sample and collect another
GET reply to the single submitted request. Checksum/reserved-field checks
remain strict; malformed data never reaches decoders. Three malformed samples
or the existing response deadline stop collection. Rejections, wrong payload
sizes and short ioctl transfers are not retried. No query or setting command
is resubmitted by this mechanism. Existing transaction readback still determines
whether the intended stored value exists.

Native profile receipts retain payload-free transport counters. A live V3
read-only local fault-injection check confirmed that a mode query can reject
one locally corrupted sample and complete on a second actual GET, with one
query submission. A separate full read matched restored state with zero
malformed frames. Neither result identifies the original USB corruption cause
or physically validates another native profile save under naturally occurring
corruption; continued production integration must retain those evidence limits.

## Initial desktop save/undo gate

The native review now offers an explicit Save to Mouse action when the
production capability gate accepts the prepared profile. It is limited to
the verified E8 receiver, firmware `0101`, only active slot1 assigned, and
single-key keyboard macros played once. Native multi-key sequences, mouse or
movement events, repetition/turbo and other firmware remain blocked pending
their acceptance. Linux service actions and ordinary save alternatives are
preserved. The broad experimental compiler is not itself production authority.

Save rechecks capability/source artifacts and opens a rediscovered exact
transport. It uses the existing asset-aware transaction and full-state stale
checks. The read worker must finish before a separate save worker begins; the
deferred callback is owned by the panel so closing it cancels a pending write.
Recovery routes the native journal kind to asset-aware undo without applying
new-save gates, while retaining original identity/firmware checks.

Native journal writes cannot replace readable originals with a document larger
than the recovery reader's 1-MiB bound. Preparation reserves space for saved
and restored snapshots plus status/error data before allowing hardware writes.
Assignment-only backups reject nonzero native macro references rather than
promise restoration without macro content. Full native receipts and portable
Linux profiles remain the recovery sources. Existing objects are retained for
undo. Byte-identical reuse is implemented below; explicit pruning remains pending.

## Existing-object reuse and dependency fingerprints

Preparation scans bounded catalog metadata for exact matches to this profile's
generated GUID, name, item count and reserved fields, then verifies event length
and SHA-256. Only complete byte-identical objects qualify for reuse. Reused
objects are never allocated, rewritten or deleted by the new transaction.
An unchanged profile can reuse its objects even when no storage/slots remain;
changing one event stream uploads only its replacement. Metadata/name changes
require a new object rather than modifying existing data needed by undo.

New receipts use native transaction version2 with a mandatory `library_before`
snapshot. It fingerprints reused objects and existing macro dependencies of
affected original bindings, including companions. Apply checks these before
any SET. Undo checks catalog/dependency integrity before restoring references,
then verifies again around cleanup. Missing/externally modified dependencies
block restoration rather than installing references to deleted or changed data.
Unrelated objects remain untouched; this is not a backup of the entire library.

The library reader is bounded to 8192 queries, 240 seconds, the existing catalog
limit and 4096 event bytes per object. Raw unknown events are hashed without
being decoded or executed. Reuse relies on the metadata plus event hash; the
journal need not duplicate every original macro body. Artifact validation
recompiles against these snapshots, rejects missing dependency records, and
prevents version1 receipts from claiming version2 reuse semantics. Actual old
version1 receipts remain recoverable with their original evidence limits.

The desktop previews new/reused counts and only newly required storage.
Save errors with an existing parent journal include its recovery path. Explicit
pruning and a physical repeated-save acceptance case remain separate work;
the reuse/state-corruption tests in this step use simulated devices.

## Combined chord, count, retention and repeated-save experiment

`native_sequence_probe` admits only a fixed three-object test profile and an
initially empty catalog. It changes normal/shifted sides11/12 only, preserving
the existing ring-finger HyperShift trigger. Side12 normally emits Ctrl down,
20ms, K down, 40ms, K up, 20ms, Ctrl up, 80ms, M down, 40ms, M up. Shifted
side12 emits F24 three times, each held40ms with a 150ms trailing gap. Both
layers of side11 share a once-only F24 macro held40ms.

After the initial journaled save, it prepares/saves the identical profile in a
separate receipt. Every object must be reused, and the real transport's Razer
setting-command counter must remain unchanged for that second save. The
counter classifies submitted Razer operations, not USB SET_REPORT queries.

A dedicated Qt window must be ready/focused before READY is announced. The
user then switches the mouse off/two seconds/back to 2.4GHz, clicks the window,
and performs side12; ring+side12; side11; ring+side11, leaving one second between
combinations. The raw observer reads only the selected V3 keyboard interfaces.
It requires six ordered chord edges and five F24 pairs (three counted plus
the two side11 combinations). The window independently records logical keys
and modifiers, rejects incidental keys, and consumes editing shortcuts locally.
Acceptance requires actual Ctrl+K, plain M with no leaked Ctrl, exact native
edge order/count, and the user's separate explicit off/on/sequence confirmation.

Within the same three-minute observation window, the assistant writes
`run/user-report.json` containing exactly
`{"power_cycled": true, "sequence_completed": true}` only after the user
confirms both. No input is grabbed or injected. The pad and native observer
retain private evidence; the controller also rechecks all saved state and
macro bytes after the reported cycle. Optional malformed-frame capture retains
at most16 private frames, never accepts them, and cannot prevent transport
recovery if capture storage fails. This tests a reported switch cycle, not
instrumented battery removal/NVM behavior.

Cleanup attempts the repeat receipt first, then the initial receipt, restoring
original assignments and removing verified new objects. Recovery is repeatable
after both have completed and uses the initial receipt as final-state authority.
The runner closes its own window afterward. `prepare` is read-only; `run`
requires explicit approval for three uploads, four mappings and actual Ctrl+K/M
input into the dedicated test window. The window is not opened by preparation.

```sh
.venv/bin/python -m gillete.native_sequence_probe prepare --directory evidence/v3-native-combined-01.local
.venv/bin/python -m gillete.native_sequence_probe run --directory evidence/v3-native-combined-01.local
.venv/bin/python -m gillete.native_sequence_probe recover --directory evidence/v3-native-combined-01.local
```

Production multi-key/count gates are not cleared merely by implementing this
runner. Native infinite held/toggle behavior, mouse/movement macros, V2 storage
and wired transport remain separate acceptance requirements.

## Combined experiment follow-up, 2026-11-11

The approved combined run recorded the correct16 desktop edges and reused all
three objects with zero setting commands, but the raw observer rejected its
key sequence. Both transactions verified restoration and the final catalog
was empty. This is `test-failed-restored`, not physical acceptance of chords or
counted playback. The offending raw event was not retained by that runner.
Future runs retain a bounded private `raw-input.json` tail after cleanup;
acceptance is unchanged. See the dated entry in `progress.md`. The existing
run and human confirmation must not be reused. A fresh preparation/run is needed.

**2026-11-11 follow-up:** the instrumented combined attempt04 subsequently
passed both raw and desktop16-edge validation, reported off/on retention,
post-cycle macro/state readback and three-object repeated-save reuse with zero
setting commands. Both transactions restored, the final catalog was empty and
the selected1600 DPI was preserved. Earlier DPI-button changes caused guarded
aborts; scoped undo removed unreferenced test objects while preserving the
owner's newly selected DPI. See the dated evidence in `progress.md`.

The production gate now admits once-only keyboard sequences and counted
single-key macros on E8/firmware0101/sole assigned slot1. The count byte permits
1–255; three iterations were physically exercised. Counted multi-key sequences,
held/toggle/turbo, mouse/movement and native F13–F23 remain separate gates.
The old unsuccessful combined run remains a failure; its missing raw event
cannot be reconstructed from the later success. Keep-stored software decoding
now handles these keyboard families as described below, without changing native
save gates or claiming combined live transition acceptance.

## Scoped desktop undo

The desktop recovery chooser uses `undo(..., preserve_unrelated=True)`.
It snapshots current state, verifies route/firmware/profile/control/storage
geometry, and checks original dependencies before any inverse write. Only
affected button groups may return to their recorded originals; any third-party
edit to those mappings blocks overwrite. Unrelated current mappings/settings
and unrelated catalog entries are preserved, including later DPI edits.

Cleanup deletes only matching unreferenced objects created by this receipt.
Objects shared by another current mapping, including unknown controls and
sequence-family references on other banks, are retained. An object whose
contents no longer match is retained rather than overwritten/deleted; the
result reports the reason without assuming who changed it. Communication
errors remain recovery-required, not successful object-retention outcomes.

Receipts distinguish `affected_assignments_restored` and
`unrelated_state_preserved` from `original_state_restored`. Whole captured
original-state verification is recorded only when the complete stored snapshot,
catalog and captured dependency evidence match. Otherwise a successful scoped
undo reports `affected-bindings-restored` and lists retained objects. Strict
automatic rollback and hardware acceptance retain their original full-snapshot
contract by default. New save admission also rejects affected active/stored
mapping differences that cannot be reversibly restored through bank1 writes.

## Keep stored in software mode

`stored_native` supplies the narrow execution bridge missing after a native
save. V3 E8/firmware0101 inspection recognizes only exact function03/size3,
nonzero15-bit ID, count1–255 and zero padding. It enumerates the bounded catalog before
dereferencing an ID, reads complete event data, admits only one balanced known
keyboard sequence with bounded delays and no parser warnings, then independently
reads that body's size/data again. Referring binding records must still match.
Once-only sequences may contain known keys/modifiers and multiple chords.
Counted references require exactly one press/release in their body; counted
multi-key/multi-press sequences stay unresolved. No unknown opcode, mouse/cursor
event, held/toggle reference, empty/keyless stream or unsafe delay is executed.

The adapter accepts only identity-validating `MacroRead` getters. Normal
transport execute allowlists remain unchanged. The pass is bounded to384 queries,
40seconds, 4096bytes per object and 8192total bytes. Unsupported bodies remain
unresolved; communication/consistency errors publish no partial body collection
and remain visible in the mouse read. V2/wired/other firmware and snapshots
without eligible references make no macro queries.

Private inspection snapshots can include the validated raw-body extension;
legacy snapshots remain readable. `stored_actions` uses those bodies to resolve
Keep stored through the ordinary cancellable Linux macro runner, preserving
press/release order and delays. Before input ownership, the newly opened service
transport independently rechecks bodies required by reachable Keep stored
actions. Explicit host overrides do not acquire dependencies on unused objects.
Software acceptance restoration also compares captured native bodies.

This does not change native save gates, recover the old V2 zero references,
create a full native library backup or claim new physical integration acceptance.
Offline tests cover simulated getters, normal/shifted shared references, exact
delays, ordinary output cancellation, service preflight, missing/changed objects,
unsupported streams, failed reads and old/new snapshot round trips. No real
mouse query/write or service activation was performed for this implementation.

The sequence/count extension preserves every delay in the stored body, including
its trailing wait after the last iteration. Counted Linux actions set their
additional repeat gap to zero; the runner neither adds its old default 100ms
nor flattens repeated bodies into a large step list. The action model/editor
allow zero additional gap for macros only. Turbo still requires a positive
interval longer than its press duration. Profile copying and JSON round trips
preserve count/delays, and summaries show the actual repeat count.

Deterministic software timelines check the accepted Ctrl+K, M byte shape and
three F24 iterations with 40ms holds/150ms trailing waits, including the final
wait and no doubled gap. Ordinary engine/coordinator tests cancel these actions
on focus loss with balanced outputs and no automatic resume. Zero-gap loops
still yield and cancel. Getters still double-read body data and recheck referring
bindings, including changes to the repeat byte. Missing/changed/unsupported
objects remain unresolved. Other receiver/firmware/wired routes make no new
macro queries, and the normal hardware allowlist/native write gates are unchanged.
