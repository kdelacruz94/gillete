# Synapse model231 polling feature parameters

Research date: 2026-11-11. Checkout baseline: `7fceecdc1cc7a04c4f1e23f6034387addb8f2d7f`. Focused continuation of [remaining-native-protocols.md, section 3](remaining-native-protocols.md#3-v3-polling-distinct-encodings-and-conditional-dispatch), its source ledger, [middleware research](synapse-middleware-research.md) and the 2026-11-10 lifecycle/polling progress entry.

**Answer:** the retained model231 startup deterministically configures `highSpeedPollingRate.yes` as a frozen empty object. Both `yes.isHyperpollingDevice` and `yes.isHyperpollingWireless` are **absent / `undefined`**, hence falsy in the dispatch predicate. They are not explicit Boolean `false` declarations. This follows from the actual injector implementation, its initialization inputs and the model's startup call, rather than interpreting the word `yes` as a capability. There is no recovered later assignment supplying either flag in the inspected assets.

Consequently the retained source's wired E7 branch and standalone E8 wireless branch do not select the high-speed builder. **E8 can still select it through the separate dual-link + hyperpolling-master branch, which tests the truthiness of the empty `yes` object and does not require either property.** That branch's session inputs are not present in these artifacts. This is a source-configuration conclusion for this build, not an observed running Synapse state or a hardware rejection/acceptance result.

The delegated source investigation wrote only this document and ignored private evidence. Shipped files were read/parsed as inert text; no shipped code, app, runtime, device, input node, service, VM or compositor was executed/accessed. It started no child agents and made no commits, hardware reads/writes or input-remapper changes. All physical testing remains deferred. No new network acquisition was necessary. The parent follow-up below separately records cached Linux USB enumeration metadata.

## Artifact identities and bounds

Original bytes are retained under ignored `evidence/synapse-official.local/desktop-web/`. URLs in this table identify the first-party sources; no current online version is substituted. SHA-256 values were recomputed over original file bytes in this pass.

| Ref | Original model231 artifact | SHA-256 |
| --- | --- | --- |
| M | [main.b99e76de0de2ff5029fc.js](https://apps.razer.com/synapse/products/231/mw/main.b99e76de0de2ff5029fc.js) | `e351aaca9bac75e6fe8797d399e1c13c28168bf154237b8be770290da139ba13` |
| B | [763.ba31528f9f94864c15b6.js](https://apps.razer.com/synapse/products/231/mw/763.ba31528f9f94864c15b6.js) | `92852b282732ad4b884e560055ce38b51352821c30bc4c4e3c70ceb03b73ebda` |
| L | [onLoad.b4643259c9c6623bee50.js](https://apps.razer.com/synapse/products/231/mw/onLoad.b4643259c9c6623bee50.js) | `f0c3c76babde97393f587db664415e98ec3518ce39d9ad6d19aad1e3e53deafd` |
| O | [6285.fb3d28e9b13b4df842c0.js](https://apps.razer.com/synapse/products/231/mw/6285.fb3d28e9b13b4df842c0.js) | `f315a9060e001f01ca52aa1f1f8e7b40b9e10d7a5516f5535ba777446c4aa794` |
| U | [rzUSB.a0303e34ff185f6386cc.js](https://apps.razer.com/synapse/products/231/mw/rzUSB.a0303e34ff185f6386cc.js) | `819802171f703438cfbd88db01a92137ca7c93572383d9825495d4803f8ee4d9` |
| E | [7116.862a88de3bdaf6baa207.js](https://apps.razer.com/synapse/products/231/mw/7116.862a88de3bdaf6baa207.js) | `c8191017e971c6f72fe4ba145a7a62e2007fc5b2b727057cec6b3124925df3e3` |
| I | [model index](https://apps.razer.com/synapse/products/231/mw/) (`231-index.html`) | `e4ea0f3f3d8d6e89439e36a22967336d21991afc6f2def6e6d7d54749dc3e098` |
| V | [manifest.json](https://apps.razer.com/synapse/products/231/mw/manifest.json) (`231-manifest.json`) | `a6d206006dbe8513459b7674f0d274dac0b8d80cf93a69eafe2f5983e3121e55` |

I pins M and buildVersion `2611020949`; I/V identify commit `66a7dd5b6934e928e3869c2938409843498473a4`, middleware dependency `7e0fefc44ba8b7492d527d1747ea297067290ad3`, commonrepository `794652df490107b200734437fe48e68eb626f4cb`, and razer-config `d0766864e758448026262d0bb35e2770c471aead`. M's chunk-name/hash maps bind B/L/O/U/E to this model loader. These identities do not pin device firmware or the native App Engine delivering a session.

Also searched retained common desktop `main.2d6ea509.js` (SHA-256 `203f10b74f612bf481f3a3d36ab4232fcc6bd639d67fbbd63f3e98af0c62adc8`) and `manifest.js` (`814eed4d2bf8c875d2921eada08268ec5ed51e45d5f768585d409b7147b17a83`). The common main embeds release `11303c1bd9c9573891a58e4ab8f5126b78ad5168`, build `2610281118`, branch `master-m16-28octhotfix`; it is a distinct build boundary from model231. It contains no `injector`, `featureFlags` or `highSpeedPollingRate` token and supplies no positive flag assignment. The service-worker manifest helper is not a feature-parameter registry. These negative text searches cannot establish the behavior of all native/remote configuration paths.

All ranges below are **half-open UTF-16 code-unit offsets in the original unmodified artifact**, not UTF-8 byte offsets, reformatted lines or offsets in extracted factories. Private `evidence/synapse-polling-flags.local/locations.json` retains exact selected text, needles, ranges and source hashes.

## Registration → replacement → consumer

| Step | Source location | Direct source fact |
| --- | --- | --- |
| Injector implementation | M factory8683, `[34085,36685)` | Constructor stores `featuresList=e||{}`, clones it into `injectorDefaults`; `useFeature(e,t,n)` ultimately assigns `o[t]=void 0===n?{}:n` and freezes an object value. It may delete one default flag first; it does not merge old parameter fields. |
| Registration defaults | M factory95414, `[214067,214617)` | Builds initial config by shallow `Object.assign`: generic task/calibration/low-battery defaults, derived runtime features, then `runtimeCache.injectorDefaults`. Constructs the injector from that object. No polling feature is declared here. |
| Derived features/accessor | M factory88443, `[214446,216446)` | `G(runtimeCache)` derives onboard/battery/external-battery/camera/side-panel/combo/mapping features, with no high-speed flags. `N$()` returns a shallow copy of `injector.featuresList`; it does not fetch or merge native parameters. |
| Model runtime input | M factory11579, `[258593,259113)` | Literal model231 cache has battery, onboard and side-panel state; no `injectorDefaults`, high-speed flags or native-config accessor supplying them. Thus the last registration input above is absent for this model. |
| Model override | M startup `[275575,276675)` | Calls `useFeature("highSpeedPollingRate","yes")` without third argument, before calling imported L/default (factory36120). In contrast, onboard parameters are explicitly preserved with `getFeatureParam` + `Object.assign` and `pollingRate:true`. |
| Later model override module | O factory38530, definition `[3948,5848)` | Injected `getDeviceOverrides` returns mapping/profile task overrides; no polling parameter override. |
| Consumer | B predicate `Qe`, export `oD`, `[2249186,2250086)` | Reads `N$().highSpeedPollingRate` directly and tests the two properties and dual-link status. No intervening registration-default merge. |

**Derived value, not executed:** immediately following that successful startup assignment, the selected shape is `{highSpeedPollingRate:{yes:{}}}`. Neither parameter exists in the registered inputs. When replacing a registered default, the no-argument assignment discards its selected parameters rather than merging them; an independently assigned non-default flag can instead trigger the injector's duplicate-assignment error. The normal model inputs above contain neither case for this feature. `yes` itself is truthy; both named properties read as `undefined`. Freezing protects the inner object from ordinary property writes; it does not freeze the whole injector or prove that external code could never replace its entries.

L/default `[481,4581)` initializes transport/event/storage/update paths and calls shared startup helpers. There is no `useFeature`/`inject`/feature-configuration setter in L. Searches of retained model JS find the two flag spellings only in B's predicate, not a writer; B contains no `useFeature` or `injectDataFromObject` call. M's `injectData` calls supply cache/override dependencies, not a native feature object. No positive native feature-injection path was identified. This is bounded source coverage, not a claim that unseen scripts or an independently versioned host cannot alter the injector.

## What connection state can still change

B factory34340 exports `BA→Je` (dual-link status), consumed as `U.BA()` by Qe. The relevant path is:

1. M startup enables `rzDeviceType.rzDevice25.isDualLinkDevice=true` (same startup range above). B `K`, `[1236560,1237020)`, reads this configured gate. It says the model participates in dual-link, not that it is currently paired.
2. B `[1237726,1238036)` defines storage key `duallink-devices`; `[1244881,1245882)` initializes `ve` from its JSON and includes the pairing-cache update path. Pairing records carry `productId`, `dongleId`, container information and a `master` object. `ye` records master information from that window's DeviceInfo. The key is runtime pairing state, not the high-speed feature flags.
3. B `Oe`, `[1254745,1254955)`, finds the first cached record whose productId or dongleId matches the argument, otherwise returns a master with productId0. This lookup itself does not filter by containerId; do not substitute a cleaner hypothetical lookup.
4. B `Je`, `[1267562,1268112)`, returns both status flags false unless `rzDevice.productId===DeviceInfo.dongleId` and K is true. A nonzero cached master productId makes `duallinkConnected=true`; membership in `[UMA,ZIA,ZIA_REFRESH]` makes `hyperPollingMaster=true`. B near1236330 defines those IDs as **179, 164, 241**. The predicate does not inspect `supports8KHzPollingRate` stored on a master record.
5. Shared dual-link startup/events refresh pairing state (`Ge` near1256000, including storage listeners); this static cache-derived result is not an independent physical-link or firmware measurement. URL `containerId` near1236161 and native-discovered device descriptors affect surrounding selection and transport, but do not supply the two missing feature properties.

U factory79012 statically wraps USB/HID enumeration and connect/disconnect events (approximately `[1860,7200)`); its `_onConnect` consumes native device.productId/container metadata and calls HID enumeration. No high-speed feature-flag assignment appears in U. The physical descriptor, logical `rzDevice.productId`, dual-link routing and cached master must therefore be distinguished. None was acquired from a running system here.

With the recovered model configuration, Qe reduces as follows:

| Logical session route/state | Qe result | Reason |
| --- | --- | --- |
| E7 / productId231 | false | Wired test requires absent `isHyperpollingDevice`; receiver branches do not match. |
| E8 / productId232, no cached master | false | Standalone wireless test requires absent `isHyperpollingWireless`. |
| E8, nonzero master outside179/164/241 | false | Dual-link master test fails; standalone wireless branch is excluded while dual-link is true. |
| E8, cached master179/164/241 | true | Dual-link and master gates plus truthy `yes={}` suffice. Neither named flag is needed. |

These are static conditional results, assuming normal initialization and the inspected injector shape. No session state is asserted. The earlier report's “special-platform” Ip branch is specifically `controllerDevice` truthiness (B factory89788 near2202806), not a native platform probe; it also requires absent `isHyperpollingDevice` and cannot rescue this model's empty parameters.

B `[2302563,2303563)` dispatches true to USB high-speed methods and otherwise, with M's `isObm.yes.pollingRate=true`, to profile polling. The task runner's >1000 clamp/read-write-read behavior and exact command encodings remain as documented in the previous report; they are not repeated or revalidated on hardware here.

The onboard engine's `options.highSpeedPollingRate` is a **different** input. Shared startup B `[1426750,1427950)` copies `isObm.yes`, adds scrollWheel, applies BLE restrictions and passes it to E/init. M explicitly supplies ordinary polling, not that onboard high-speed option. E copies the supplied option at roughly `[1200,2450)`, so its initial false can become `undefined`; neither this loader option nor the high-speed feature object establishes the other. Do not conflate onboard backup/loading behavior with Qe's live task routing.

## Evidence type, coverage and next input

**Direct shipped-source evidence:** original-byte hash checks, bounded text inspection and build-local call/export relationships above. **Derived:** the absent-property values and conditional route table. **Unobserved:** effective running host state, physical connection, native-injected replacements if any, firmware acceptance, supported rate list, cadence and persistence.

REA was used without target execution. Reused the saved macro parent `ev_39677dcaa80b9b0b52f02c4dfd8a608ac549bf7416844357f2177b08aaca644f` via its authenticated evidence-file summary (three selected macro/onboard files, zero parse failures, 14 unselected files); it does not cover this flag trace. A new static JavaScript analysis selected M/L/O: parent `ev_cc9738e2fc5eeebc53be11bdfa1c47da0f7924a792c72a25c251fc0a6739614e`, summary receipt `ev_d3690e25dab5e2463300797dfba8bc35361783e3b74a7065b7e91f6dd0903bda`. Three files parsed, zero parse failures, 37 inventoried files unselected. Application graph is partial; semantic graph is partial/truncated at the requested 8,000 nodes/5,000 unknowns per file and alias expansion bound512. It does not prove exhaustive data flow or runtime reachability. B/U/E and the common desktop files were inspected directly as text, not covered by this new REA selection. Complete retained session evidence is exported to ignored `evidence/synapse-polling-flags.local/rea-evidence.json`; its export's `unknowns:0` is not a completeness verdict (the parent reports 6,145 semantic unknowns). No active binary target was opened.

**Resolved:** no hidden registration/default merge is needed to obtain these flags in the retained model build. Both are absent/falsy after normal model startup. This narrows the previous uncertainty substantially, but does not justify expanding Gillete's polling allowlist or declaring wired high-speed firmware unsupported.

**Actual remaining input/path:** to decide Qe for a real E8 session, the smallest evidence is a same-build, already-recorded snapshot of logical `rzDevice.productId`, the matching `duallink-devices` record/master and timing relative to its storage refresh. To establish that a running host replaces these source-configured flags, first obtain an existing post-startup `injector.featuresList.highSpeedPollingRate` snapshot or identify a specific writer/replacement in the matching host/preload/script set; then pin that writer's bytes, delivery order and native payload. There is no demonstrated native boolean API or public feature-JSON URL to query speculatively. Dashboard device catalogs referenced by dual-link code describe pairing candidates, not a recovered flag-merge path, so no download was needed to answer the focused question.

Any newly acquired configuration or script must match the M/I/V build and dependency identities above, or be treated as a separate version. Actual E7/E8 command acceptance and physical output rates still require separately authorized, labeled traffic and later physical tests described in the prior report. This investigation authorizes none of those actions.

## Parent review and cached Linux enumeration

The parent rechecked M's injector/startup and B's Je/Qe ranges against the pinned
original-byte hashes. Je looks up the actual logical `rzDevice.productId`, and
Qe returns a Boolean; the source table above is consistent with those bodies.

Separately, a read of cached Linux sysfs metadata on 2026-11-11 found both
connected B4/E8 receivers reporting raw `speed="12"`, `bInterval="01"` and
`interval="1ms"` for their interrupt-IN endpoints, with `wMaxPacketSize="0040"`.
B4 exposes three such endpoints and E8 four. Private evidence is retained in
`evidence/synapse-polling-flags.local/linux-enumeration-20261111-01.json`.
No hidraw/input node was opened, feature query submitted, mouse woken or setting
changed. This describes the current cached USB enumeration, not measured motion
cadence, a firmware maximum or Synapse's logical/dual-link session state. It
does not admit higher polling rates or establish support on another receiver.

A Windows session snapshot would attribute Synapse's branch choice. It is not
an unconditional prerequisite for a Linux implementation if direct, separately
authorized Linux tests establish the relevant command's effect, actual cadence
and restoration on the exact transport. Those hardware results remain pending.
