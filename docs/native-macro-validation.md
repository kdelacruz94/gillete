# Native macro validation

2026-11-10. The compiler and experiment pass offline checks. The user's V3
receiver has now physically accepted allocation, upload, counted-once F24
playback (83.001-ms measured hold for 80-ms requested delay) and cleanup.
Power-cycle persistence, HyperShift and repetition remain unverified.
Production Save to Mouse capabilities remain unchanged.

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

V2, wired V3, HyperShift macros, power-cycle persistence, native repetition
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
