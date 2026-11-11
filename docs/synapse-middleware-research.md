# Official Synapse middleware research

Research date: 2026-11-05. This pass inspects downloaded first-party files as
inert text. It does not run Synapse, access either mouse, change a setting, or
establish physical firmware acceptance. Hardware testing remains deferred.

## Source identity and reproducibility

The Windows App Engine's packaged `electron/main.js` selects
`https://apps.razer.com` as its production application host. The dashboard's
published manifest helper constructs `/synapse/products/{pid}/mw/sw.html`.
Following that route yielded middleware whose manifests explicitly identify
both target models. These are desktop Synapse resources, distinct from the
public Synapse Web product at `synapse.razer.com`.

| Model | Middleware manifest commit | Main script SHA-256 |
| --- | --- | --- |
| V2 HyperSpeed, decimal PID 180 / `00b4` | `db06e6eb85b1ee8b20e8cba272e1d0cffaa9b657` | `ba4e8c1dbfdb45dab0701207b7de674a945270cfc903e10dab7fb4f2f4f54415` |
| V3 Pro, decimal PID 231 / wired `00e7`, receiver `00e8` | `66a7dd5b6934e928e3869c2938409843498473a4` | `e351aaca9bac75e6fe8797d399e1c13c28168bf154237b8be770290da139ba13` |

The main scripts name their lazy chunks. The relevant shared chunks are
V2 `6120.3d50bdcbd9f80022ae9e.js` and V3
`763.ba31528f9f94864c15b6.js`. Static Babel parsing extracted exact Webpack
factory expressions, wrapped only in parentheses and a terminating semicolon.
`selected-factories/ranges.json` records their original **UTF-16 code-unit**
ranges, matching JavaScript string offsets; they are not UTF-8 byte offsets.
All twelve extracted ranges were checked against their original bundles using
JavaScript `String.slice`, without executing any target expression.

The original downloads, extraction ranges, checksums and retained REA evidence
are preserved in ignored `evidence/synapse-official.local/` with private file
permissions. `source-manifest.json` hashes the preserved files. The original
Windows executables and ASAR also remain in
`/tmp/gillete-research/synapse-official/`; their acquisition identities are:

| Artifact | SHA-256 |
| --- | --- |
| Official bootstrapper, version 2.6.0.890 | `e4eabf1a0cf030b773a1a14ed22f4cb337c5f85638863260215b6315d83eb570` |
| App Engine installer 4.0.896 | `a8314ba4ef6124a0a5f6af32654bced378e90b28662cdd198c07fac05ef6bac7` |
| App Engine `app.asar` | `e7a524aca1771251ca4f851441a97cac1c33929891b291ed34deb7adfc1831ec` |

Installer module downloads matched the lengths and MD5 checksums in the
first-party product manifest; those checks are transfer consistency, not an
independent signature-authenticity verdict. No Windows installer was run.

## DPI: direct evidence for the selector-0 candidate

**Observed source, both builds:** protocol factory `7755` defines the scalar
DPI getter and setter with seven data bytes and command pairs `04:85` and
`04:05`. The first argument is copied directly into data byte zero. X, Y and
Z occupy subsequent two-byte big-endian pairs; the scalar wrapper defaults Z
to zero. Both `setDpiLevel` and `setProfileActiveDPISetting` call that same
setter. Their names do not make byte zero a profile-slot identifier.

The DPI task factories are V2 `96571` and V3 `55753`. Each contains a path
that:

1. Reads scalar DPI with selector `0`.
2. Skips the write if both requested axes already match.
3. Otherwise writes the requested X/Y values with selector `0`.
4. Reads selector `0` again and checks both axes, reporting a mismatch as an
   error.

The saved-stage path instead calls `setDPIStages(1, ...)`, or
`setDpiLevel(1, ...)` when its configured alternative is selected. It reads
the stage table back and checks the encoded values. This corroborates the
existing selector-0 experiment with first-party implementation evidence.

**Evidence limit:** this is a real setter path in software published for these
models, but no execution trace proves which branch Synapse takes on a connected
mouse. It does not measure sensor sensitivity, show whether firmware writes
flash, or prove behavior after sleep, power cycling, receiver replug or driver
mode. Keep `temporary_dpi_supported` false until those checks succeed. The
existing journaled `dpi_probe` remains the appropriate next physical step;
automatic per-program DPI must not be enabled from source evidence alone.

Source anchors: V2 factory `7755`, UTF-16 `[767811,963031)` of chunk 6120;
task factory `96571`, `[1728189,1903726)`. V3 factory `7755`,
`[766297,961730)` of chunk 763; task factory `55753`,
`[1733174,1912398)`. Ranges refer to the complete factory expressions, and
the preserved extracted files permit focused searches by method name.

## Onboard profiles: concrete candidate commands

**Observed source, both builds:** protocol factory `7755` includes these
packet builders. Tuple sizes below are the command definitions' declared
data sizes; the generic transport's optional size overrides require separate
inspection before implementing variable-length operations.

| Command | Declared data bytes | Source behavior |
| --- | ---: | --- |
| `05:80` | 1 | Reads number of profiles from response byte zero. |
| `05:81` | 80 | Reads count followed by that many assigned profile IDs. |
| `05:02` | 1 | Creates a profile using the supplied ID in byte zero. |
| `05:03` | 1 | Deletes the supplied profile ID. |
| `05:84` | 1 | Reads the active profile ID. |
| `05:04` | 1 | Sets the active profile ID supplied in byte zero. |
| `05:88` / `05:08` | 80 | Gets/sets name data using profile ID, u16be offset, u16be size and content. |

These definitions strengthen the research route for slot creation and
selection, but their presence in a shared protocol module is not proof that
every operation works on every model. The V3 main module advertises onboard
profile-navigation mappings and its startup enables the onboard engine.
The V2 main module advertises a hardware profile switch but omits that
navigation mapping group. Do not infer extra usable V2 slots from shared
builders, or treat a rejected V3 slot as created.

The onboard engine in factory `51294` manages profiles, names and dependent
settings together. A transactional Gillete implementation must preserve all
assigned slot content and relevant metadata before any create/select/delete
experiment, then verify active and stored banks independently. The current
single-slot readback is insufficient to enable multi-slot switching.

### Profile metadata lifecycle follow-up — 2026-11-10

Focused inspection of the retained V3 factory `51294` resolves the metadata
writer's dependency order. `setProfileNameStructure` normally calls
`createNewProfile(id)` **before** writing any metadata. Its final boolean
parameter skips that call; `_writeKeyMappingHash` explicitly passes true.
Therefore copying the default name-writer path for a rename or recovery would
also submit a profile-create command. That behavior must be separated in a
future transactional implementation; source alone does not prove recreation
is harmless or idempotent on these mice.

The structure is 250 bytes: mixed-endian GUID16, UTF-8 name100, a 128-byte
owner/padding area and mapping hash6. The non-rzDevice30 path writes chunks
of at most 64 bytes with a five-byte header (profile ID, offset:u16be,
total size:u16be), overriding declared command size to `5+n`. Reads request
the same chunk sizes with their size field zero. Its reader extracts only 64
owner bytes despite the 128-byte write area, so round-tripping decoded fields
would not preserve every original metadata byte. Keep complete raw metadata
for any future restoration. This differs from macro metadata's item count
and reserved/timestamp/hash layout; the structures are not interchangeable.

`addProfileNameStructure` skips ID1, while the generic `setProfileName`
wrapper does not enforce that skip. Neither wrapper establishes that Naga
slot1 supports name metadata. The shared `getProfileIDList` parser calls its
leading byte a total and slices that many IDs; this user's Naga instead
physically reports capacity5 with one assigned ID and a separate count1.
Continue using the observed Naga inventory contract, rather than copying the
shared parser's capacity/count assumption.

No create/delete/select/name/hash command was submitted for this follow-up.
All slot lifecycle operations remain unverified. A later experiment must
preserve even readable unassigned-bank content, in addition to assigned slots,
and must not reconstruct opaque metadata from these partial decoded fields.

## Macro capability: model-specific warning in the source

The V2 main module's `DeviceInfo.OBMSpecs.supportedFeature` explicitly sets
`macros` false while its supported mapping groups include `macroGroup`.
Startup merges those feature values into the onboard configuration. This
distinguishes accepting a macro mapping in the application from declaring
onboard macro-storage support. It is stronger evidence against assuming the
four old zero references contain recoverable onboard sequences.

The V3 model declaration does not specify a `macros` field in that object.
The shared configuration contains a macro-enabled default, but the complete
effective configuration and upload path still need tracing. Neither omission
nor the shared macro command builders establish V3 native macro acceptance.
The [macro/turbo follow-up](synapse-macro-turbo-research.md) establishes the
rate conversion and traces the incoming macro option into the engine subclass.
Runtime V3 options and actual storage/playback acceptance remain unobserved.

The user has retired the old V2 MapleStory macros. Preserve their original raw
binding records for restoration; do not spend validation time recovering their
sequences or reinterpret reference zero globally as disabled.

## REA coverage and remaining work

Preserved App Engine artifact inspection parent:
`ev_a5cf1288f271e8957f75ef9090bf460e00146072bed28bde15c953d861e9e95b`.
Its extraction evidence is
`ev_9bc85b7250e69f989d8b8c0a8bc5427bd0fd45a28be12e256c7e7d09292077ae`.
Extraction covered container entries. Twelve unpacked native addons had hashes
that contradicted the ASAR header. They were retained as observed-untrusted
with `record-and-continue`; signing after ASAR creation is a possible
explanation, not a verified cause. None was loaded or executed. This pass's
DPI/profile conclusions come from JavaScript source, not those addons.

Core installer managed-member evidence
`ev_d0a1c711b2dadb2ee924f1b953f130f9446cde248163271d238b8ae7f2b2827a`
established the package-discovery URL construction; it did not load a CLR or
observe network calls. The later focused middleware analysis was interrupted
before a persistent export. Its handle is gone and REA reports no active
analysis. Do not cite that interrupted run as complete coverage. The direct
factory-range validation and retained source bytes above remain reproducible.

Next independent research: finish native macro event serialization and the
upload/rollback graph, then check the precise size-override behavior used by
profile names and stage tables. Next physical research, when the user resumes it:
run the prepared reversible selector-0 DPI experiment, verify the V3 wired
read-only route, and design a separately reviewed profile-slot experiment.
No new hardware capability is enabled by this document.

[V2 manifest](https://apps.razer.com/synapse/products/180/mw/manifest.json),
[V2 entry script](https://apps.razer.com/synapse/products/180/mw/main.16b5a8f74ad8b0a866c5.js),
[V2 shared protocol chunk](https://apps.razer.com/synapse/products/180/mw/6120.3d50bdcbd9f80022ae9e.js).

[V3 manifest](https://apps.razer.com/synapse/products/231/mw/manifest.json),
[V3 entry script](https://apps.razer.com/synapse/products/231/mw/main.b99e76de0de2ff5029fc.js),
[V3 shared protocol chunk](https://apps.razer.com/synapse/products/231/mw/763.ba31528f9f94864c15b6.js).

[Official download page](https://www.razer.com/synapse-4),
[production dashboard](https://apps.razer.com/synapse/dashboard/),
[published desktop manifest helper](https://apps.razer.com/synapse/assets/js/manifest.js).
