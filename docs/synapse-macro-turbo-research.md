# Synapse macro and turbo source findings

Research date: 2026-11-05. Offline first-party source inspection; no device
queries, setters, input capture, service changes or playback measurements.
Source acquisition and model identities are documented in
[the middleware report](synapse-middleware-research.md).

## Turbo conversion is now established at the client level

Both target models' official middleware factory `56415` uses the same
conversion for keyboard and mouse turbo:

- Encoding: `interval = floor(1000 / Number(keysPerSecond))`.
- Decoding: `keysPerSecond = round(1000 / interval)`.
- An omitted rate uses `floor(1000 / 7)`.
- Keyboard data contains modifiers, key usage and a two-byte interval.
- Mouse data contains button ID and a two-byte interval.

The byte helpers exported by entry-module `52975` store the high byte before
the low byte and combine the pair in that order. Factory `50540` identifies
keyboard turbo as function `0d`, mouse turbo as `0e`; their data lengths are
four and three respectively. The fixed seven-byte stored binding additionally
contains function ID, length and trailing padding.

| Raw interval | Integer value | Synapse decoder rate | Relevant encoding |
| --- | ---: | ---: | --- |
| `008e` | 142 | 7 presses/s | Default or explicit 7 presses/s produces 142. |
| `003e` | 62 | 16 presses/s | Explicit 16 presses/s produces 62. |
| `0014` | 20 | 50 presses/s | Explicit 50 presses/s produces 20. |

Consequently the four preserved V2 turbo bindings with `008e` can now be
described as **Synapse's encoding of 7 presses/s**. This conclusion comes from
both first-party encoders and decoders, rather than the conflicting upstream
formulas in the earlier report. It does not measure the mouse's actual repeat
frequency or prove its press/release duty cycle, initial delay, held behavior,
toggle behavior, or response to disconnect/focus loss.

The conversion is lossy: integer division during encoding and rounding during
decoding can change a rate on a round trip. Unknown or existing intervals
should retain their exact raw bytes. The mapper performs no visible local
validation before this conversion; that is not permission to send zero,
negative, infinite or overflowing rates. Gillete needs its own explicit valid
range before implementing a firmware encoder.

Source anchors: factory `56415`, UTF-16 `[472115,494627)` in the V2 chunk
and `[470601,493113)` in the V3 chunk. Within the preserved extracted
expression, mouse decoder `p` is near character 3460, keyboard decoder `E`
near 5750, keyboard encoder logic near 12500, and mouse encoder logic near
8300. The named methods and hashes below are authoritative; approximate
positions are navigation aids only.

## Macro binding format is confirmed directly

Factory `56415` maps a selected macro GUID to its numeric catalog ID and
places that ID in the first two data bytes, big-endian. Its playback switch
and factory `50540`'s enumeration establish:

| Function | Data bytes | Source playback option |
| --- | --- | --- |
| `03` | ID:u16be, repeat-count:u8 | Once uses count 1; fixed count uses the supplied count. |
| `04` | ID:u16be | Continuous while held. |
| `05` | ID:u16be | Continuous toggle. |
| `0f` | ID:u16be | Sequence. |

The binding stores a reference and playback option, not the actual events or
timings. Its GUID lookup can leave the newly allocated byte array at zero
when no matching catalog entry is found. That supplies a possible client-side
route to a zero reference; it does not establish why this user's old V2
assignments have reference zero. The zero reference remains unresolved and is
not a global disabled marker. The old MapleStory sequences are retired by
user decision, with original raw records preserved for restoration.

## Storage capability is gated separately from mapping support

The V2 model explicitly overrides the onboard `macros` feature to false but
includes macro mappings among supported groups. The V3 model enables the
onboard engine without an explicit macro override in its startup options.
Both shared feature-default builders offer a macro-enabled onboard default.

The runtime startup obtains the injected `isObm.yes` options, copies them into
the onboard initialization call, then forces macros and polling false on its
BLE path. The actual engine subclass is lazy chunk `7116`, module `27116`.
Its `init` assigns the incoming macro option to the engine's macro flag.
The shared engine in factory `51294` starts with macro support enabled, but
the subclass assignment makes the incoming effective option decisive.

This traces the option from model startup through the runtime call to the
storage engine. It supports investigating V3 firmware macro storage and
explains why V2 mapping support cannot be treated as onboard sequence support.
It does not observe the final injected options on a connected V3, allocation,
upload, binding, or playback. Those remain unverified. In particular,
Bluetooth behavior is outside the current implementation scope.

The storage engine's macro loader checks that macro flag before reading
storage information, count, catalog IDs, names and data. The shared protocol
factory `7755` includes the class-`06` builders underlying those operations.
The existing read-only `firmware_probe` is still the next physical step for
V3; do not jump directly to allocation, deletion or upload. Macro event
serialization and the complete upload/rollback dependency graph still need
a separate focused pass before a native-write experiment is ready. The
follow-up below establishes their source format and dependencies. A native
write experiment still needs a verified catalog and recovery design.

## Event records and read-only inspection

Both retained protocol bundles define these event opcodes in module `41022`.
Factory `51294` implements their serializer and reader:

| Opcode | Following bytes | Interpretation supported by the source |
| --- | --- | --- |
| `01` / `02` | HID usage:u8 | Key make / break; retain the raw usage rather than converting it through Windows scancodes. |
| `08` | Mask:u8 | Full held state of five mouse buttons in bits 0..4. |
| `0a` | `01` / `ff` | One positive / negative wheel notch. |
| `11`..`14` | 1..4 bytes, big-endian | Delay integer, with increasing width. |
| `15` | X:u16be, Y:u16be | Raw cursor coordinates; coordinate mode and physical behavior are unverified. |

The four-byte delay reader uses JavaScript bitwise operations and can produce
a signed value when the top bit is set. The diagnostic reports the unsigned
stored bits and flags that ambiguity. It never schedules such a delay.

Synapse's reader includes repair logic for a missing final key release and
can append mouse releases. Those are client-generated events, not evidence of
stored bytes. Gillete's `macro_inspection` preserves actual records and held
state without repairs. It stops at unknown opcodes, incomplete records,
unsupported mouse-mask bits or wheel values, retains the entire remainder,
and never resynchronizes by guessing the next boundary. Power/media record
sizes remain unsupported; their source cases do not establish a safe size.
The parser does not produce executable Gillete Actions or enable playback.

The optional read-only catalog now includes this interpretation beside the
unchanged raw hex. It keeps the existing 4096-byte per-macro / 8192-byte total
capture bounds and issues no additional requests. First-party `createMacroId`
uses the entry helper's random u16 masked with `32767`. Accordingly the
candidate reader now accepts enumerated IDs 1..32767 instead of the previous
upstream-client-derived 1..255 restriction. It still refuses reference zero,
unlisted IDs and larger values; the macro-count bound remains 128. This does
not claim that every possible firmware ID has been supported.

## Upload dependencies and the reclamation boundary

Factory `51294`'s `addMacro` chooses a catalog ID, serializes the requested
items, and estimates allocation in 256-byte blocks including 256 bytes for
metadata. It reads free/reclaimable storage, then calls `addMacroLocal`, which
allocates the event-data size, writes the name/metadata structure, and writes
event data in chunks of at most 72 bytes with a seven-byte header. Name data
is handled in chunks of at most 64 bytes with a six-byte header.

The macro metadata structure is 250 bytes: GUID (16), little-endian item
count (4), name bytes (100), extra/reserved data (16), timestamp bytes (16),
hash bytes (32), and trailing reserved bytes (66). Preserve raw metadata and
unknown fields if restoration is ever required. Names, macro events and
profile bindings are separate dependencies, not one atomic write.

The insufficient-contiguous-space path can call `defragStorage`: it reads
missing macro details, invokes `formatDevice`, then reconstructs profile
information/settings/bindings and macros from its client cache. This is a
broad storage rewrite. Gillete must not copy that fallback into an initial
native-macro experiment. A first experiment should require adequate
already-free space, use a fresh verified nonzero ID, journal all touched
dependencies and bind the button only after readback verification. Cleanup
must restore the original binding first and avoid deleting shared/referenced
data.

The source also logs and catches some metadata/data-write errors rather than
propagating them through every layer. A successful client return alone would
not prove an uploaded macro. Independent readback plus physical execution
and persistence checks are necessary. No allocation, deletion, format,
defragmentation or upload was attempted during this research.

## Evidence and validation

The preserved factory `56415` SHA-256 values are:

- V2: `0d8c69bed2abf3bf0e2166c14172b0640f759be3f440525ee8a3818caf503c38`.
- V3: `29a620199862bb8450df29a79a63ee34f9d5f6cf1c831c0553465af943b7af06`.

The playback-encoder and decoder excerpts are byte-identical between these
two extracted factories; other parts use different minified local names.
Factory `50540` numeric enums and entry-module `52975` byte helpers were
checked separately, avoiding an inference from function names alone.

Additional published subclass chunks acquired from the original entry
scripts' literal chunk tables:

- V2 `7116.1001d47a3165945e4b32.js`, SHA-256
  `7a55bca64492cd4ef9b7af18b5ff5e01f68b9d57ea116206792c04d9fc34265d`.
- V3 `7116.862a88de3bdaf6baa207.js`, SHA-256
  `c8191017e971c6f72fe4ba145a7a62e2007fc5b2b727057cec6b3124925df3e3`.

REA focused analysis parent
`ev_39677dcaa80b9b0b52f02c4dfd8a608ac549bf7416844357f2177b08aaca644f`
parsed the V3 extracted factories `56415`/`50540` and original chunk `7116`:
three JavaScript files, 53,636 text bytes, zero parse failures. The complete
evidence is retained in ignored
`evidence/synapse-official.local/macro-focused-evidence.json`. Selection leaves
other files and external dependencies outside that graph; static analysis
does not prove runtime dispatch or hardware behavior. The packet and option
interpretations above also include direct inspection of the preserved source.

[V2 mapping/protocol bundle](https://apps.razer.com/synapse/products/180/mw/6120.3d50bdcbd9f80022ae9e.js),
[V2 byte helpers/model configuration](https://apps.razer.com/synapse/products/180/mw/main.16b5a8f74ad8b0a866c5.js),
[V2 engine subclass](https://apps.razer.com/synapse/products/180/mw/7116.1001d47a3165945e4b32.js).

[V3 mapping/protocol bundle](https://apps.razer.com/synapse/products/231/mw/763.ba31528f9f94864c15b6.js),
[V3 byte helpers/model configuration](https://apps.razer.com/synapse/products/231/mw/main.b99e76de0de2ff5029fc.js),
[V3 engine subclass](https://apps.razer.com/synapse/products/231/mw/7116.862a88de3bdaf6baa207.js).
