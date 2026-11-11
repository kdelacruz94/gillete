# Remaining native protocols: lifecycle, reclamation and V3 polling

Research date: 2026-11-10. Baseline supplied by parent: `344e875`, including managed native macro cleanup. This report changes no capability or mutation scope. Cleanup may leave recyclable bytes; reclaiming them is a separate operation. All physical tests remain deferred. Research used retained first-party shipped JavaScript as inert text, manifests, existing REA evidence and repository notes; no bundles were executed or downloaded, and no device, service, VM or GUI was accessed. Research was performed without child agents, as explicitly requested (overriding the research skill's delegation default).

**Result:** profile packet construction is resolved, but new-slot firmware contents and safe lossless recovery are not. Synapse's traced `defragStorage` is a format/rebuild workflow with preservation gaps. V3 has a conditional high-speed polling route, separate from Gillete's current interval command; shared builder support alone cannot admit higher rates on either transport.

Evidence vocabulary: **source** means directly inspected shipped code; **inference** means a conclusion from that code; **prior observation** refers to existing recorded hardware results, not a measurement in this pass; **unknown** requires additional evidence. Model-specific declarations and callers are distinguished from shared builders throughout.

## Source ledger and reproducibility

Paths below are relative to ignored `evidence/synapse-official.local/desktop-web/`. Original URLs are the linked filenames. `acquisition.json`, manifests, `selected-factories/ranges.json`, and the saved extraction script identify the artifacts. Hashes below were recomputed locally.

| Ref | Original official artifact | SHA-256 |
| --- | --- | --- |
| B180 | [180/mw/6120.3d50bdcbd9f80022ae9e.js](https://apps.razer.com/synapse/products/180/mw/6120.3d50bdcbd9f80022ae9e.js) | `3ae8f05e074c1367877c9096b9886a387d410e011526162b89e6dbc450fc995a` |
| B231 | [231/mw/763.ba31528f9f94864c15b6.js](https://apps.razer.com/synapse/products/231/mw/763.ba31528f9f94864c15b6.js) | `92852b282732ad4b884e560055ce38b51352821c30bc4c4e3c70ceb03b73ebda` |
| M180 | [180/mw/main.16b5a8f74ad8b0a866c5.js](https://apps.razer.com/synapse/products/180/mw/main.16b5a8f74ad8b0a866c5.js) | `ba4e8c1dbfdb45dab0701207b7de674a945270cfc903e10dab7fb4f2f4f54415` |
| M231 | [231/mw/main.b99e76de0de2ff5029fc.js](https://apps.razer.com/synapse/products/231/mw/main.b99e76de0de2ff5029fc.js) | `e351aaca9bac75e6fe8797d399e1c13c28168bf154237b8be770290da139ba13` |
| E180 | [180/mw/7116.1001d47a3165945e4b32.js](https://apps.razer.com/synapse/products/180/mw/7116.1001d47a3165945e4b32.js) | `7a55bca64492cd4ef9b7af18b5ff5e01f68b9d57ea116206792c04d9fc34265d` |
| E231 | [231/mw/7116.862a88de3bdaf6baa207.js](https://apps.razer.com/synapse/products/231/mw/7116.862a88de3bdaf6baa207.js) | `c8191017e971c6f72fe4ba145a7a62e2007fc5b2b727057cec6b3124925df3e3` |

Manifest identities: 180 commit `db06e6eb85b1ee8b20e8cba272e1d0cffaa9b657`; 231 commit `66a7dd5b6934e928e3869c2938409843498473a4`, buildVersion `2611020949`. These identify the retained published model resources, not connected firmware versions.

Factory ranges are **half-open UTF-16 code-unit ranges in the original bundle**, not UTF-8 byte ranges. Extracted factories add wrapping parentheses/semicolon; method offsets quoted later are search aids in those extracted files. Hash plus original range is the canonical anchor.

| Factory | Role | B180 range | B231 range |
| --- | --- | --- | --- |
| 7755 | Protocol methods and transport | `[767811,963031)` | `[766297,961730)` |
| 51294 | Shared onboard engine | `[574419,624364)` | `[572905,622850)` |
| 56415 | Mapping/event conversion | `[472115,494627)` | `[470601,493113)` |
| 50540 | Mapping enums | `[641460,646616)` | `[639946,645102)` |
| 25947 | Task makers | `[1522489,1728182)` | `[1520491,1733167)` |
| 96571 / 55753 | Task runners (different IDs by build) | `[1728189,1903726)` | `[1733174,1912398)` |

Extracted factory SHA-256 checks: 180/7755 `5d26a126b5caadab6a53b50f5f2ec7c4557a268d0d49c019c149fa24a6254dad`; 231/7755 `aa73e935674552c325559ba38f6090cd95835ff1723b7b678b2cc217cf0711b4`; 180/51294 `7b1d3d4a1f616a7b47de8581bddda4e16421dd50c44b71c53f80d6a4ec882775`; 231/51294 `3abe13f49d6ec2083c106703e4ab8ddafb2d967a98e369785ace8c9b121162d7`. The format/defrag source bodies compare identically across the two extracted engine factories.

Additional B231 anchors outside those extracted factories: polling wrappers factory 84816 begins near 646096; command definitions factory 30580 around 663k–669k; rate enums factory 32135 around 669k–672k; high-speed predicate at original text offset ~2249170; polling dispatch wrappers ~2302663. Use literal names and export bindings alongside offsets; numeric/minified identities are build-local.

REA reuse: inspected saved `macro-focused-evidence.json` through `inspect_analysis_view`, parent `ev_39677dcaa80b9b0b52f02c4dfd8a608ac549bf7416844357f2177b08aaca644f`, summary receipt `ev_59016f2f5a630962344efc4f69dae8a63a149e637dd1aaffb0c4718d7c732041`. Parent analyzed only V3 factories 56415/50540 and E231 (three parsed files, zero parse failures); 14 inventoried files were outside its selection and graph/semantic coverage is partial. **It does not independently cover this report's full lifecycle/polling trace.** Those findings are direct static inspection of the hash/range-bound sources above. Prior App Engine artifact parent `ev_a5cf1288f271e8957f75ef9090bf460e00146072bed28bde15c953d861e9e95b` supplies acquisition context, not firmware behavior. See [middleware research](synapse-middleware-research.md) for its extraction/signature limitations.

## 1. Profile lifecycle

### Exact construction

Both retained factory-7755 implementations expose the following shared methods. Sizes mean the protocol's declared data length, inside the fixed report envelope, not total USB transfer length. No size override is passed by create/delete/select/reset; their effective declared length stays one byte.

| Method / command | Declared / effective data length | Request content |
| --- | --- | --- |
| `getNumberOfProfiles`, `05:80` | 1 / 1 | zero; response byte 0 is count |
| `getProfileIDList`, `05:81` | 80 / 80 | zeros; parser names response byte 0 `total` and slices IDs accordingly |
| `createNewProfile`, `05:02` | 1 / 1 | `[id]` |
| `deleteProfile`, `05:03` | 1 / 1 | `[id]` |
| `getActiveProfileID`, `05:84` | 1 / 1 | zero; response byte 0 is active ID |
| `setActiveProfileID`, `05:04` | 1 / 1 | `[id]` |
| `setProfileReset`, `05:0b` | 1 / 1 | `[id]` |
| `getMaxProfilesSupported`, `05:8a` | 1 / 1 | zero; response byte 0 is maximum |
| `getProfileName`, `05:88` | 80 / caller override | `id:u8, offset:u16be, size:u16be`, zero remainder |
| `setProfileName`, `05:08` | 80 / caller override | same header followed by content, padded array to at least 80 |

Source: B231/7755 declarations ~18333 and methods ~98900–103000; B180 equivalent named methods. The generic `sendCommand` accepts the fourth `packetSizeSet` argument (default -1). `_createDataSend` (B231 original ~808949, factory7755) allocates90 bytes, places the definition size in byte5, replaces it with a positive override, and copies only that many argument bytes before checksum calculation. Thus an 80-byte allocated/padded input array is not evidence that metadata requests declare 80 useful bytes.

For the non-`rzDevice30` name-structure path, 51294 writes 250 bytes in chunks 64/64/64/58, offsets 0/64/128/192; effective sizes are 69/69/69/63, each with header `id, offset:u16be, 00 fa`. Reads use those same effective lengths but put zero in the size field. This is a **client construction**, not an accepted Naga transaction capture. The separate rzDevice30 branches use different framing/chunk sizes and are not a substitute Naga route.

The 250-byte profile structure is GUID16 (mixed endian), UTF-8 name100, owner/padding128, hash6. The reader extracts only 64 owner bytes. A decode/re-encode cycle therefore cannot promise byte preservation. Macro metadata also totals 250 bytes but has GUID, item count, name, reserved areas, timestamp and hash; do not interchange layouts. [B231/51294 `setProfileNameStructure` ~28473, `getProfileNameStructure`; B180 equivalents.]

### Creation, initialization and backup are distinct

`setProfileNameStructure(..., skipCreate=false)` submits `createNewProfile(id)` **before** its metadata chunks. `_writeKeyMappingHash` passes true; ordinary `setProfileName` does not. `addProfileNameStructure` skips ID1, but the generic name wrapper does not. ID1 has no proven writable metadata contract; prior wired metadata query for ID1 failed. Renaming/restoring must not silently recreate a slot. This confirms the existing metadata follow-up rather than establishing a new safe setter.

**New trace:** E231 `addProfile` (~18175 onwards) checks for an existing assigned ID and deletes it if found. It then calls name/create, scalar DPI/stages, scroll mode, brightness, ordinary polling, high-speed polling and debounce initialization, subject to options and supplied values. It builds an in-memory profile and visits supplied mappings. A normal-layer mapping equal to the generic default can be recorded in JSON without a firmware write; a matching HyperShift mapping is explicitly written. Different mappings are written. It does not begin by cloning/backing up the target bank. [E231 `addProfile`, `setSingleButtonMapping`; B231/51294 `addProfileDPI`, `addProfileNameStructure`.]

**Inference:** Synapse relies on some firmware defaults for new slots. Neither `05:02` nor this caller supplies a full bank image. Static source does **not** establish whether create clears, clones, retains stale bytes, resets bindings, or initializes DPI/other namespaces before those later writes. A generic mapping table is not a captured factory bank. Even the DPI helper's profile-looking first argument is not proof of independent banks for every selector on these mice.

E231 `loadProfilesFromDevice` (~5488) loads macro catalog/details metadata, maximum/count/list, assigned profiles' decoded names (skipping the first list entry), optional DPI/scroll/brightness/polling/high-speed/debounce, and both binding layers. It enumerates assigned profiles, not every unassigned bank, and produces decoded `obmJson`, not a full raw backup. Its first-entry skip and the explicit writer ID1 skip must not be generalized into support for ID1 names.

Prior Naga observation remains authoritative: `05:80` count1, `05:81` body `05 01`, active ID1. Leading 5 is capacity/max-ID information in this inventory, not five assigned IDs. M231's `OBMSlots:4` and shared parser's `total` are application conventions; neither overrides the captured inventory. [Prior [remaining protocol research](remaining-protocol-research.md#v3-profiles-capacity-is-not-assignment-or-selection); M231 DeviceInfo.]

### Smallest future acceptance sequence — conditional, not run or authorized here

1. Establish exact PID/route/firmware; wired E7 transport first needs its own read-only acceptance. Preserve active ID, mode, count/list/capacity, raw both-layer bindings and settings for all assigned slots, macro catalog/raw metadata/events and all readable unassigned candidate-bank state. Keep opaque bytes/flags. Resolve failed reads and ambiguous bank addressing before mutation.
2. Choose one confirmed unassigned, user-disposable non-ID1 slot. If its prior contents cannot be read/restored, require an explicit later decision accepting that loss; do not call the experiment fully reversible. Journal the complete baseline and recovery limits.
3. Submit **only** `05:02 [id]`; validate status and re-read inventory/active ID. Read new-slot content immediately, before name/settings writes, to establish create semantics. Compare every protected assigned bank and catalog. Never retry a timed-out create blindly; determine assignment first.
4. Only after bank semantics and recovery are established, select that slot with `05:04 [id]`, inspect active/stored state and independently validate selection effect. Restore the original active ID before deleting only the owned new slot with `05:03 [id]`. Verify inventory, raw banks, settings, metadata and macros afterward. Name writes and initialization are separate acceptance steps, not prerequisites for this minimal lifecycle test.

Unrecoverable today from these artifacts: actual initial firmware bank bytes; unreadable unassigned contents; unsupported/opaque settings; missing ID1 metadata; discarded profile owner bytes if only decoded JSON was saved; host-only macro sequences from zero references. The user's retired V2 MapleStory macros need no recovery. Existing readback/cleanup evidence does not settle any of these lifecycle unknowns.

## 2. Defrag is format/rebuild, with preservation gaps

Source chain: B180/B231 factory51294 `addMacro` memory-pressure checks → `defragStorage` (~41772 in extracted V3) → `formatDevice` (~41100) → protocol7755 `FormatStorage` (~98454). Firmware-backed accounting compares requested space against available + recyclable, defrags when available alone is insufficient, then queries storage again. Calculated accounting also invokes defrag for mice; a keyboard branch adjusts accounting instead. This is broader than deleting a managed test macro.

`formatDevice` does the following:

- With `options.resetProfile`, submits `05:0b [assignedId]` for each assigned profile.
- Otherwise submits `05:03 [id]` for list indices 1 through count-1, sparing the **first listed** profile (not an explicit ID1 comparison).
- If the final result is success or empty and macros are enabled, calls `FormatStorage`. Errors are caught; this is not an atomic all-or-nothing transaction or a verified rollback.

`FormatStorage` sends `06:0a`, declared/effective six bytes, payload `00 00 00 02 00 00`: macro ID0, reserved/status byte0, action `MemoryFormat=2`, trailing zeros. It waits 100 ms in the shipped code and queries `06:8a` with the same six-byte request up to three times, returning early on successful reply with data status byte2 equal to2. These timing/retry facts describe the client, not a recommended destructive experiment. `RawDataCheck=1` and `DataCheckByID=3` are other management actions; neither is a compaction action in this enum. [B231/7755 management declarations ~16150, `Ko`/`xo`, `FormatStorage`; B231 factory41022 enum ~697593.]

The builders name class06 macro memory management; **format's firmware-wide physical erase boundaries remain unknown**. Separately, the caller explicitly changes the class05 profile namespace, then rewrites class04 DPI, class02 assignments and class06 macro allocation/name/data. Do not describe the overall operation as macro-only.

Before formatting, `defragStorage` loads details for catalog macros whose decoded `macroItems` are empty. After success it:

- For each cached profile whose ID is not1, recreates name metadata (default hash zeros), DPI/stages and both layers of cached assignments.
- Converts every cached catalog macro's decoded items to a new byte array, allocates its ID/data size and writes GUID/name/item count metadata and event bytes through `addMacroLocal`.

It does **not** call the broader E231 `addProfile` initialization here. Although loaders can capture brightness, polling, high-speed polling, scroll mode and debounce, the traced defrag rebuild does not restore those fields, active ID, or a full bank image. It skips ID1 rebuild even on the resetProfile branch that resets it. Metadata is reconstructed from decoded fields: profile owner/padding and original hash are not preserved losslessly; macro rebuild omits saved timestamp/hash arguments, so `addMacroLocal` defaults them to empty strings. Reserved/extraInfo and raw event bytes are not used as restoration inputs. Opaque events cannot be assumed to survive decoding/conversion. [B231/51294 `defragStorage`, `addMacroLocal` ~38548, `setMacroNameStructure` ~32525; E231 loaders.]

An unnamed or unassigned **macro** can be included if it exists in the enumerated catalog; the loop does not filter by binding usage/name. That does not guarantee preservation if metadata decoding failed. An unassigned **profile bank**, orphan macro allocation, free/recyclable region, opaque padding or unenumerated object is not covered by the cached lists. No raw flash image is captured. Consequently this workflow cannot currently support Gillete's promise to preserve arbitrary Synapse state.

**Bounded negative finding:** inspected the two retained full protocol bundles B180/B231 and E180/E231, selected factory51294 memory-pressure/defrag callers, factory7755 management builders, and searched retained model JavaScript for defrag/compact/reclaim/format/memory-management candidates. The sole case-insensitive `compact` match in each full protocol bundle is an unrelated object-inspection option (`compact:false`), not a storage operation. No separate firmware-only macro compaction builder/caller was identified in that scope. This does not establish absence from firmware, native DLLs, unfetched lazy chunks, other published versions or dynamically supplied extensions. A command tuple/string alone would also not prove a safe model-specific path.

Prerequisites for reclamation: a complete raw inventory and restorability contract across all affected namespaces; exact create/reset/delete effects and ID1 behavior; a lossless macro codec or raw restoration path; restoration of omitted settings/metadata/active ID; verified ordering and failure recovery with per-step journaling; model/firmware-specific capture and physical acceptance under a later explicit scope. Alternatively obtain first-party evidence of a narrower compaction command and validate its scope independently. Until then retain recyclable bytes after managed cleanup. Do not automatically import Synapse's format/rebuild path.

## 3. V3 polling: distinct encodings and conditional dispatch

Gillete `src/gillete/settings.py` currently admits only125/500/1000 using one-byte interval values08/02/01 with `00:05/85`. That is the ordinary polling family, not a way to represent rates above1000. [Repository settings module; B231/84816 ordinary getter/setter.]

| Shared method family | Get / set | Declared/effective length | Payload / supported client values |
| --- | --- | ---: | --- |
| Ordinary device polling | `00:85 / 00:05` | 1 | interval code, shared enum supports1000/500/333/250/200/125/100 |
| Profile polling | `00:8e / 00:0e` | 2 | profile ID then ordinary interval code |
| USB high-speed polling | `00:c0 / 00:40` | 2 | profile ID then high-speed code |

High-speed codes: **8000→01, 4000→02, 2000→04, 1000→08, 500→10, 250→20, 125→40** (hex). Getter request initializes `[profileId,0]`; setter `[profileId,code]`. Reply decoding uses data0 as profile ID, data1 as code. Setter rejects unsupported rates; shared getter defaults unknown codes to8000, so copying that decoder would falsely admit unknown replies. Linux must retain/reject unfamiliar values. [B231/30580 tuples; 32135 `Gy`; 84816 exports `W7→Y`, `_5→Z`, response decoder `j`, ~655560–656850; 7755 public forwarding methods.]

**Model-specific source:** M231 DeviceInfo (~244759) explicitly declares product231/E7, dongle232/E8, BLE233/E9, claimInterface3, `supportInGamePollingRate:true`, OBMSlots4 and supportedFeature.pollingRate=true. Startup (~275951) injects `isObm.yes.pollingRate=true` and separately enables `highSpeedPollingRate/yes` (~276405). Thus V3 has a real feature route to the broader builders, not just an unused shared enum. This does not certify all rates on either transport.

**Exact dispatch:** B231 task runner55753 `pt` (~44700; original ~1778020) evaluates the high-speed predicate; a requested rate>1000 is clamped to1000 when false. It reads current rate, skips an equal value, writes, reads again and rejects a mismatch. The read/write helpers (original ~2302663/2303041) default selector/profile to1 and choose:

1. Predicate true → `get/setUSBHighSpeedPollingRate`.
2. Otherwise `isObm.yes.pollingRate` true → `get/setProfilePollingRate`.
3. Otherwise → ordinary `get/setPollingRate`.

The predicate (export `oD`, local `Qe`, original ~2249170) returns true for the special-platform branch with `yes.isHyperpollingDevice`, or wired model productId with that flag. For dongleId it admits `(duallinkConnected && hyperPollingMaster && yes)` or `(yes.isHyperpollingWireless && !duallinkConnected)`. These are separate **connection-dependent choices of the same high-speed builder**, not independently proven E7/E8 command numbers. The two `isHyperpolling*` parameter values and actual connection state are not established by M231's bare `useFeature(...,"yes")`; their effective injected configuration was not recovered from the inspected retained model assets. Wired/receiver high-speed reachability therefore remains conditional. No unconditional 8k Naga claim follows from it.

E231's constructor defaults `pollingRate=false` and `highSpeedPollingRate=false`, but `init` copies passed options. Startup passes `isObm.yes` options; its BLE path forces macros=false and pollingRate=false. Per-profile loaders/setters run only when their corresponding option is truthy. The startup high-speed feature switch and onboard-engine highSpeedPollingRate option are distinct: enabling one does not prove the other is true. BLE is outside the requested E7/E8 acceptance scope. [E231 init ~1200–2450, defaults ~25704; B231 startup ~1427000.]

Required evidence before higher-rate admission: retained effective feature parameters and first-party Windows traffic for labeled125/500/1000/2000/4000/8000 selections on E7 and E8 separately, including physical vs logical PID routing, profile selector, dual-link/master status and firmware versions. Confirm which values the UI actually offers, exact setter/getter replies and fallback/clamping. Later physical acceptance must measure output cadence, persistence, independent profile behavior and restoration; configuration readback alone does not prove8000 reports/s. Wired descriptor/transport uncertainty from prior notes still applies.

**Follow-up, 2026-11-11:** [the feature-parameter trace](synapse-polling-feature-flags.md)
now resolves normal startup's two named parameters as absent/falsy: the model
registers a frozen empty `yes` object. E8's separate dual-link/master branch can
still select high-speed polling. Its live logical PID/cache state is unobserved.
The earlier parameter gap above is therefore narrowed, not a reason to infer
unconditional 8k support or wired firmware rejection. A Windows trace would
attribute Synapse routing; direct Linux command-effect/cadence/restoration
acceptance on an exact transport can independently establish Linux support.
Cached Linux enumeration currently shows 1ms endpoint intervals on the attached
B4/E8 receivers; it is not a motion-cadence measurement. Production gates stay
unchanged pending actual acceptance.

## Admission matrix and delta

| Capability | Concrete new source fact | Present admission / missing evidence |
| --- | --- | --- |
| V2/V3 create/select/delete | One-byte commands; metadata writer creates; addProfile can delete existing slot and omits some default-equal writes | Keep gated; exact initial bank contents, namespace side effects and recovery unmeasured |
| Profile names |250 bytes, dynamic69/63 sizes, ID1 skip and creation side effect | Prior metadata note confirmed; raw restoration and ID1 contract unresolved |
| Reclamation |06:0a action2 plus06:8a status; caller deletes/resets profiles and partially rebuilds | No compaction admission; lossless backup/restore prerequisites unmet |
| V3 ordinary polling | Current interval encoding remains distinct | Retain existing admitted125/500/1000 scope |
| V3 profile polling |00:0e/8e fallback when onboard polling enabled | Candidate only; selector independence and hardware acceptance unmeasured |
| V3 high-speed polling |00:40/c0, seven exact rate codes, model feature enable and conditional dispatch/clamp | Do not expand settings allowlist; effective flags/route and physical rates unresolved |
| V2 native macro storage | M180 explicitly disables onboard macros despite macro mapping group | Preserve existing limitation; shared format/allocate builders do not override it |
| V3 managed macro cleanup | Parent implementation may leave recyclable bytes | No automatic format/rebuild; prior accepted bounded playback/cleanup stays separate |

Compared with [middleware research](synapse-middleware-research.md), [macro/turbo research](synapse-macro-turbo-research.md), [remaining protocol research](remaining-protocol-research.md) and [progress](progress.md), the material additions are the initializer's omitted default writes, exact format management payload and rebuild losses, and V3's distinct high-speed codes/predicate/fallback chain. Profile metadata side effects and the capacity/count conflict were already known and are retained here, not presented as newly measured results.

Status: question1 **partially answered** (builders/callers resolved; firmware initial state/recovery unknown); question2 **partially answered** (shipped defrag workflow resolved within bounded search; safe reclamation unavailable); question3 **partially answered** (protocol/model conditional route resolved; effective flag values and E7/E8 rate acceptance unknown). No hardware or Windows runtime result was produced in this pass.

## Implementation follow-up

`polling_reads.py` and the explicit `firmware_probe --product 00e8 --sections polling`
option now prepare receiver-only observation of the two source-backed getter
families. They require assigned selectors, validate length/echo and retain unknown
codes without Synapse's 8000 Hz fallback. Successful reads are compared again;
failed requests are not retried. Baseline firmware, mode, identity, profile
inventory, active-mirror/active-slot bindings and ordinary saved settings are compared.
The normal read transport, polling settings allowlist and every setting command
remain unchanged. Neither the candidate diagnostic nor a live polling write was
run during implementation. Desktop diagnostics expose these limits and keep
native storage compaction unavailable.
