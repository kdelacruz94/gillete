# Remaining protocol research

Research date: 2026-11-05. Scope: offline source/capture analysis only. Read
`progress.md`, `feasibility.md`, and the transport, framing, inventory,
stored-action and input decoders. No device access, physical test, mode/settings
change, service/configuration change, commit or publication was performed. Both
mice remain restored. Current user decisions supersede the original pending
questions: hardware testing is deferred, and the old V2 MapleStory macros on
HyperShift+sides1/2/4/10 do not need recovery. See `progress.md`.

Evidence labels: **observed** = bytes in a recording; **source** = upstream
implementation/transcription; **inferred** = interpretation not measured on
these mice; **unresolved** = needs additional evidence. Upstream contributor
hardware is not this user's hardware. Preserve the actual Synapse assignments,
including opaque functions and response flags; never replace them with factory
mappings.

Follow-up: [official Synapse middleware research](synapse-middleware-research.md)
now preserves first-party model-specific bundles. Both contain a selector-0
scalar DPI setter/readback path and concrete profile-management builders.
The V2 model explicitly disables the onboard macro-storage feature while
still accepting macro mappings. These source findings refine the next tests;
they do not establish physical setter or persistence acceptance.

## 1. V2 stored functions

### Class `05` is a macro family, not a disabled/default marker

**New source evidence:** OpenSynapse names function IDs `03/04/05/0f` as
`MacroTypeI/II/III/IV`. Its mapping encoder associates these with counted
playback, hold, toggle, and sequence respectively. In particular, **function
`05` = MacroTypeIII, interpreted as toggle**, with two data bytes. This refers
to the function inside an `02:8c` binding, not USB command class `05` for
profile management. The encoder says its mapping switch was transcribed from
Synapse middleware chunk 6120/module 56415. This is implementation/provenance
evidence, not a captured V2 playback experiment. [M1][M2]

Consequently, shifted sides 1, 2, 4 and 10 containing `05 02 00 00 00 00 00`
can be described as **“macro-toggle family; reference 0x0000; unresolved.”**
The binding contains a reference, not the keystroke sequence or its delays.
OpenSynapse's separate macro protocol treats IDs as big-endian 16-bit values;
its service rejects ID zero, and its ID-list parser also rejects zero. These
are client restrictions: they **do not establish firmware's meaning for zero
on PID `00b4`**. A missing/unuploaded macro, host-resolved reference or special
sentinel remain possible; none is proven. Nor does equality of four references
prove the four controls execute the same host-side action. Do not decode them
as disabled, inherited normal mappings, or an empty playable macro. [M3][M4][M6]

**Can Linux query it without Synapse? Partially, in principle.** An upstream
read-only macro-memory protocol now supplies concrete candidate queries:

| Command | Declared size | Candidate purpose/payload |
| --- | ---: | --- |
| `06:8e` | 14 | Storage capacity/free-space counters; zero arguments |
| `06:80` | 2 | Macro count; zero arguments |
| `06:8b` | 4+2n, n<=32 | ID list; two-byte big-endian list offset; command maximum80 |
| `06:88` | 6 | Data size for an enumerated two-byte macro ID |
| `06:89` | 7+n, n<=72 | Memory chunk: ID:u16be, offset:u32be, length:u8; command maximum80 |

The upstream implementation bounds chunks to 72 bytes and has a separate event
codec. **Implementation follow-up:** its service overrides the command maxima
with the dynamic declared sizes above; the definitions alone are insufficient
to construct an ID-page/memory query. The candidate Gillete reader follows
these sizes. Its original upstream-client-derived byte-ID restriction has
since been widened to enumerated IDs 1..32767 using first-party Synapse's
15-bit ID generator; zero remains excluded. See the
[event-format/upload follow-up](synapse-macro-turbo-research.md#event-records-and-read-only-inspection).
It preserves the ID page's extra size field without assigning it a guessed
meaning. [M7] However, its macro-capable mouse allowlist includes `0067/008d/0093/0075/0a22`,
**not V2 HyperSpeed `00b4` or V3 `00e7/00e8`**; its protocol documentation is
for protocol-25 devices. This is a research route, not an established Naga V2
API. Gillete's ordinary transport still allowlists no class-`06` queries. The
new opt-in `firmware_probe` uses a separate bounded read-only transport; its
implementation/tests have not established physical Naga support. It starts
with storage/count, enumerates before reading memory, validates
echoes/lengths/status and stops that family on rejection. Do not
blindly dereference zero or copy upstream allocation/delete/write flows. Even a
successful empty catalog would not explain the zero reference or recover a
host-only Synapse macro. [M3][M4][M5]

### Turbo: payload meaning is stronger than timing evidence

**First-party follow-up:** [Synapse macro/turbo research](synapse-macro-turbo-research.md)
now establishes both target builds' client conversion:
`floor(1000 / keysPerSecond)` when encoding and
`round(1000 / interval)` when decoding. `008e` is Synapse's encoding for its
default 7 presses/s. This supersedes the unresolved *client formula* below;
actual mouse playback timing and held/toggle behavior remain unmeasured.

The preserved values parse structurally as follows. This is supported by the
upstream function codec and the captures below, **not yet by measured V2
playback**. Keep the complete original seven bytes. [S1]

| Existing binding | Structural interpretation |
| --- | --- |
| Normal tilt left `0d04004b008e00` | Keyboard turbo, modifiers `00`, usage `4b` (PgUp), parameter `008e` |
| Normal tilt right `0d04004e008e00` | Keyboard turbo, modifiers `00`, usage `4e` (PgDn), parameter `008e` |
| Shifted left click `0e0301008e0000` | Mouse turbo, button `01` (left click), parameter `008e` |
| Shifted side 7 `0d04001c008e00` | Keyboard turbo, modifiers `00`, usage `1c` (Y), parameter `008e` |

**Direct capture inspection:** the pinned OpenSnek archive contains BLE HCI
recordings, not V2 USB playback captures. REA inspected their identities/counts;
offline `tshark` extraction established these precise packets:

| Capture | Relevant recorded evidence |
| --- | --- |
| `right-click-turbo.pcapng` | Frame 702, t=15.549305: binding payload `01 02 00 0e 03 01 00 8e 00 00`; frame 949, t=20.822841: `01 02 00 0e 03 01 00 3e 00 00`. Matching transaction/status-`02` notifications follow at 704 and 951. |
| `basic-rebind.pcapng` | Frame 1882, t=40.763563: `01 03 00 0d 04 00 08 00 8e 00`; matching transaction/status-`02` notification at 1884. |
| `all-key-binding-functions.pcapng` | All fourteen 10-byte binding payloads are clearing shifted slots 4/5; none establishes a class-`05` macro or playback semantics. Its filename overstates the useful coverage. |

All ATT traffic in these three recordings uses vendor handles `003d/003f`
(writes/write responses/notifications). They contain **no separate HID input
notification stream establishing repeated down/up output**. Therefore the
timestamps above measure configuration traffic, not press cadence. The
captures prove parameter changes and successful protocol replies, not press
duration, initial delay, held/toggle behavior, release cancellation or firmware
execution without Synapse. [C1][C2][C3]

Two contradictions matter:

- The BLE protocol note prints the `003e` example as `... 01 3e 00 ...` and
  calls it right-click. The actual recorded bytes are `... 01 00 3e ...`;
  shared button-ID sources identify `01` as left click. Use the bytes, not the
  filename/example label. [S2][S1]
- OpenSnek linearly maps raw `1..255` to `20..1` presses/s; `008e` yields 9
  presses/s in that helper. OpenSynapse instead emits an interval from
  `1000 / pressesPerSecond`; uncoil labels the mouse field milliseconds based
  on Synapse logs (`0068 0014` tilt example). A 142-ms interpretation would
  suggest about 7.04/s, but **neither formula nor that calculation is a V2
  measurement**. The uncoil log summary is corroboration of an interval
  interpretation, not an output-timing capture. Do not import either helper
  as a validated timing model. [S1][M2][U1]

**Implementation boundary:** descriptive decoding can expose class/type,
key/button, raw parameter and unresolved macro reference now. Automatic software
execution must remain blocked for these functions unless the user explicitly
maps replacements or playback is established. Existing keep-stored behavior is
correct; discovering a family name is insufficient to compile an equivalent
software action.

**Later evidence needed, not run here:** passively record the V2's unchanged
normal-mode raw HID output, with all host remappers accounted for, during short
presses, several-second holds, release and HyperShift release. Measure initial
delay, down/up duty cycle, intervals/jitter and post-release output. To establish
the whole rate encoding rather than just `008e`, obtain labeled Synapse slider
settings plus matching binding bytes and output traces at several rates, using
a disposable profile with full backup/restore. For class `05`, recover macro
content/playback configuration from an existing Synapse export/log/artifact if
not queryable onboard. Absence of Linux output alone cannot prove “disabled.”

## 2. V3 Pro wired `1532:00e7`

### Feature-report transport: a specific routing discrepancy

**Source:** the pinned Linux fork uses request and response `wIndex=0` for
`00e7`, with a 31,000-us reply wait. Receiver `00e8` explicitly uses index `3`
and 99,900 us. The common helper makes EP0 class/interface transfers:
SET `bmRequestType=21, bRequest=09, wValue=0300`; GET
`bmRequestType=a1, bRequest=01, wValue=0300`; 90-byte bodies. Thus feature
report **ID is 0**, distinct from the Razer transaction byte. [R1][R2][R3]

**Observed upstream wired replies:** OpenSnek's 2026-10-18 wired `reads.txt`
contains successful transaction-`1f` responses for firmware, polling, DPI/stages
and other queries; lines 31–35 report the same 33-control inventory. Firmware
query size is **4**, reply `01 01 00 00`. The metadata log records status `03`
for `05:88` on slot 1. The raw logs do **not** identify a Linux hidraw node or
record `wIndex`. OpenSnek uses report ID 0 and chooses a collection capable of
a 90-byte feature report. [W1][W2][S3]

**Important new descriptor evidence:** the original upstream issue's paired
HID dumps advertise the same 90-byte unnumbered feature report on interface
`03` for **both** PIDs; neither interface-`00` descriptor advertises a feature
report. This does not prove the fork's direct EP0 index-0 route is wrong, or
that Linux hidraw interface `03` will execute wired commands. It does mean
“wired config iface00” is a **candidate from driver source, not yet a verified
Gillete transport mapping**. Do not add `00e7` to `CONFIG_INTERFACE` based only
on that switch or copy receiver iface03 without validation. [D1][R1]

### Input layout: exact descriptor differences, bounded conclusions

The issue identifies USB device 023 as wired and 022 as receiver. Decode by
`bInterfaceNumber`/dump suffix, **not listing order**: wired configuration lists
interfaces in order `0,2,1,3`. This explains why its published descriptor-length
list `79,61,159,22` can misleadingly look like interfaces 1/2 are swapped. [D1]

| Interface | Receiver `00e8` | Wired `00e7` | Derived layout/support boundary |
| --- | --- | --- | --- |
| `00`, pointer | 85-byte descriptor | 79-byte descriptor | Both unnumbered 8-byte input: buttons byte0; padding byte1; signed pan byte2, wheel byte3; signed LE16 X/Y at 4/6. Padding is declared as `3+8` bits vs `11` bits; field offsets agree. |
| `01`, composite keyboard/vendor | 314-byte descriptor | 159-byte descriptor | Both report IDs `01..05`, each 15-byte payload + ID = 16 bytes. ID1: modifier byte + fourteen usages. ID4/5: fifteen opaque bytes. Wired omits receiver ID`0a` (9-byte mouse report), IDs`08/09` notifications, and ID1 LED output. |
| `02`, boot keyboard | 61 bytes | Byte-identical 61 bytes | Unnumbered 8-byte input: modifiers, reserved, six usages; 1-byte LED output. |
| `03`, configuration | 22 bytes | Byte-identical 22 bytes | Unnumbered 90-byte feature body; no input report. |

These are **descriptor-derived schemas**, not physical button correlations or
proof the device is in driver mode. Pointer tilt bits `20/40` fall in
descriptor padding; raw firmware/driver observations are needed for them.
The fork handles both PIDs in the same raw-event branch: pointer tilt edges
become F15/F16; 16-byte report4 codes `20/21/22/23/59/d2` become keyboard usages
`68/69/6a/6b/6c/6d`. Depending on the bound driver, Gillete may see original
report4 or rewritten report1. [D1][R4]

Naga Control's 2026-09-28 contributor capture reports equal **evdev** signatures
on both transports for 19 special/side controls: interface01 special keys,
interface00 tilt and interface02 side keys. That supports role compatibility
but does not establish raw HID byte equality, all 25 controls, simultaneous
holds, underside profile release, or this user's wired firmware. Gillete's
decoder currently selects by model/interface alone; any differing wired frame
must get an explicit transport/descriptor-specific path rather than a relaxed
generic parser. [N1][L1]

### Minimum future read-only validation, then separate activation acceptance

1. **Descriptor-only baseline:** with the cable connected, identify the exact
   USB ancestor/PID, firmware context and bound drivers; save all four HID
   descriptors and hashes. Reconfirm interface numbers/report lengths. Detect
   the simultaneously attached receiver; do not select solely by shared serial.
2. **Bounded query-only route test:** use the existing hidraw method without
   driver detach, grabs, service startup or mode setter. Start with interface00
   as the Linux-fork candidate, transaction `1f`, report ID0; send only known
   getters (`00:81` size4, then `00:84` size2 and `00:85` size1). Require a
   completed status2 reply, correct transaction/class/command, frame length,
   reserved fields and checksum. A status0 request echo is not success. If it
   fails, test the descriptor-backed interface03 candidate once under the same
   constraints; record which exact route succeeds. Allow delayed GET polling;
   do not sweep transaction IDs or replay SETs on timeout. The hidraw envelope
   is 91 bytes including its leading zero report ID, not a 91-byte USB body.
3. **Readback boundary:** on a proven route, read `02:84` with enough room for
   count+33 IDs, `05:80/81/84`, both binding layers for the active assigned slot,
   and supported DPI/polling getters. Preserve opaque function bytes/flags.
   Record normal mode before/after and unchanged bindings/settings. This earns
   only read-only wired inspection support, not permission to save or activate.
4. **Separate later driver-mode acceptance:** descriptors and normal-mode
   reads cannot prove driver-mode input behavior. Only a separately authorized,
   journaled/restored mode capture can establish every control's down/up,
   wheel sign, motion, simultaneous holds, release and driver-rewrite behavior.
   No existing authorization to wake V2 or test settings authorizes this wired
   mode test. Keep software activation and writes gated until their own
   evidence is collected.

### V3 profiles: capacity is not assignment or selection

The receiver's actual log shows count `01`, list `05 01` (maximum ID5, only
ID1 assigned), active `01`. Its section headed “active 1 -> 2 -> restore 1”
actually records **active after 2 = 1**, so the heading is not evidence of a
successful switch. The capture summary explicitly reports selection of
unassigned ID2 rejected. Reading/writing settings in bank5 does not assign it.
Naga metadata rejection is observed even though the Basilisk CRUD spec describes
successful metadata/create/delete on other hardware. [P1][P2]

Use count/list/active as an internally consistent inventory, retaining Gillete's
narrow zero-declared-size response exception. Query these again on wired;
the wired capture does not establish its assigned list or profile switching.
Expose selection only for assigned IDs, after a separate authorized selection
test verifies ACK, active getter and effective bank0 bindings. Do not implement
Naga profile creation/deletion by treating the Basilisk spec as portability
proof. DPI's leading storage selector is independently `VARSTORE=1`; the
OpenSnek profile-addressed DPI experiments are not sufficient to establish
independent per-profile DPI semantics on Gillete's firmware. [L2][P2][R5]

### DPI selector follow-up

Tracing the fork's actual packet builder changes the interpretation of its
caller. Although the caller selects NOSTORE for V2 HyperSpeed and VARSTORE for
V3, `razer_chroma_misc_set_dpi_xy` ignores its `variable_storage` argument and
always emits VARSTORE. The getter does emit the passed selector. Thus this fork
does **not** demonstrate nonpersistent scalar DPI writes on either target.
The opt-in diagnostic only compares selectors1/0 with `04:85` and verifies the
returned selector; no setter is admitted. Even successful differing reads
would require a separate reversible write/persistence test before using this
path for focus-driven sensitivity. [R5]

## Evidence and reproducibility

Pinned upstream source/capture links below identify the exact revisions.
Private ignored evidence is in `evidence/remaining-protocol-research.local/`
(directory 0700, files 0600): original three pcapng files, complete REA bundle,
selected ATT frames/counts and descriptor hashes in `capture-analysis.json`,
descriptor-only issue extract, and source digests in `source-manifest.json`.
No serials or incidental input are reproduced in this report.

REA parent Evidence IDs: right-click turbo
`ev_313fd8f585fcbf1288708bf905fec118a01523dd074cdb3bcf09077fa9360406`;
basic rebind `ev_8840dbb8b8b33841457cd5c724e6a7e7f7b30aeae6ab1a2b6eb0248d0a55f455`;
all-functions `ev_4fd33883dfd91cde0c59d16f884190c7c54d08fc16d9d22d6bbc9c2060e718af`.
REA establishes recording identity/coverage; the ATT and HID interpretations
above are separate offline derivations. Saved traffic cannot establish process
identity, causality or missing runtime behavior. No REA native target was opened.
Offline verification: all 12 raw wired `reads.txt` reply frames passed Gillete's
length/reserved-field/checksum validator. This is parser compatibility, not a
hardware acceptance test.

[M1]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Protocols/ViperObmProtocol.cs#L9-L29
[M2]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Protocols/RazerHidMappingActions.cs#L226-L252
[M3]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Macros/RazerOnboardMacroProtocol.cs#L46-L99
[M4]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Macros/RazerOnboardMacroService.cs#L78-L111
[M5]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Macros/RazerOnboardMacroDevices.cs#L3-L19
[S1]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/OpenSnek/Sources/OpenSnekCore/ButtonBindingSupport.swift#L221-L275
[S2]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/docs/protocol/BLE_PROTOCOL.md#L946-L955
[S3]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/OpenSnek/Sources/OpenSnekHardware/USBHIDControlSession.swift#L184-L207
[C1]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/ble/right-click-turbo.pcapng
[C2]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/ble/basic-rebind.pcapng
[C3]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/ble/all-key-binding-functions.pcapng
[U1]: https://github.com/justinthevoid/uncoil/blob/e6733807811de0bc1c00a8a7737417146660779e/docs/PROTOCOL.md#L281-L296
[R1]: https://github.com/Rainexn0b/openrazer/blob/26b0eeb5ed70d638fa3528851adcd5e58369a7f5/driver/razermouse_driver.c#L47-L134
[R2]: https://github.com/Rainexn0b/openrazer/blob/26b0eeb5ed70d638fa3528851adcd5e58369a7f5/driver/razercommon.c#L20-L98
[R3]: https://github.com/Rainexn0b/openrazer/blob/26b0eeb5ed70d638fa3528851adcd5e58369a7f5/driver/razermouse_driver.h#L136-L140
[R4]: https://github.com/Rainexn0b/openrazer/blob/26b0eeb5ed70d638fa3528851adcd5e58369a7f5/driver/razermouse_driver.c#L6637-L6695
[R5]: https://github.com/Rainexn0b/openrazer/blob/26b0eeb5ed70d638fa3528851adcd5e58369a7f5/driver/razerchromacommon.c#L1211-L1240
[W1]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/usb/2026-10-18-naga-v3-pro-wired/reads.txt#L1-L35
[W2]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/usb/2026-10-18-naga-v3-pro-wired/metadata.txt#L1-L3
[D1]: https://github.com/openrazer/openrazer/issues/2885
[N1]: https://github.com/Rainexn0b/naga-control/blob/824fac8a3951471af15a80586ac4c65d07c6bf00/docs/integration-findings.md#L300-L340
[L1]: ../src/gillete/reports.py
[L2]: ../src/gillete/protocol.py
[P1]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/usb/2026-10-17-naga-v3-pro/probe-log.txt#L54-L64
[P2]: https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/usb/2026-10-17-naga-v3-pro/README.md#L33-L36
[M6]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Macros/RazerOnboardMacroProtocol.cs#L213-L255
[M7]: https://github.com/A1mAssist/OpenSynapse/blob/eaaf3eaa63d38434ee7b8d47d4091f8f12c5400e/src/OpenSynapse.Windows/Macros/RazerOnboardMacroService.cs#L232-L295
