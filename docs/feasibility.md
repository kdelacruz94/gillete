# Gillete feasibility and evidence ledger

Status: interview complete and implementation authorized. Native editor/service,
onboard binding transactions and driver-mode routing are implemented. Both mice
passed initial onboard power-cycle/HyperShift and control-capture tests; the V3
passed core live software acceptance. Full-product acceptance remains incomplete.
See `progress.md` for the latest implementation and active hardware-test state.

## Requested outcome

- Native Linux application for CachyOS, for Naga V2 HyperSpeed and Naga V3 Pro.
- Every-button remapping, persistent mappings on the mouse, multiple profiles
  for games/programs, and HyperShift. RGB is not a priority.
- The user completed the grilling interview and accepted the scope recorded
  in `specification.md`.

## Local observations

Initial read-only shell inspection found CachyOS with Hyprland/Wayland and USB receiver
`1532:00b4`, named Razer Naga V2 HyperSpeed. No V3 was listed in that snapshot.
The V2 presents three hidraw interfaces bound to `razermouse`; their permissions
were root-only. Its HID_UNIQ was all zeros, so it is not a usable unique identity.
Do not assume VID/PID alone identifies the mouse for backup restoration.

Installed components include OpenRazer 3.12.4, input-remapper, PySide6, evdev,
hidapi, and Wireshark CLI. OpenRazer and the input-remapper tray were running.
Any future driver-mode or event-grab work must account for existing owners.
REA 6.8.0 was connected with no target open; Ghidra, Hopper, and Kuna were
reported available. No binary analysis or USB protocol commands were performed.

Existing work worth consulting, without assuming it remains the desired design:

- `/home/kdelacruz/Projects/terminal-config/cachyos/naga/`: input-remapper
  profiles and Hyprland focus watchers.
- `/home/kdelacruz/Projects/AI-Brain/Fleet/reports/naga-cap-scout.md`: earlier
  investigation, including WoW/MapleStory context and unverified physical inputs.

## V2: protocol evidence

Reference: OpenNaga tree/commit `a19e837a6f64cd9b394e62d50c899eb79861bac2`.
The live GitHub tree and pinned raw files were inspected. Search-engine cached
raw content was older and normal-layer-only; use the pinned revision below.

[Binding codec](https://github.com/Zer0codestuff/OpenNaga/blob/a19e837a6f64cd9b394e62d50c899eb79861bac2/Sources/NagaController/Hardware/RazerOnboardBindings.swift):

- Transaction `0x1f`, command class `0x02`; enumerate `0x84`, read `0x8c`,
  write `0x0c`. Binding payload length is 10 bytes.
- Bank 0 is the active view, bank 1 the stored bank. These are not proof of
  two independent user-selectable onboard profiles.
- Request byte 2 selects normal/HyperShift. Reply byte 2 must not be treated
  as a trustworthy layer echo. Preserve unknown function bytes when backing up.
- Inventory expects 21 controls. This is model-specific evidence, not a V3 schema.

[Assignment plan](https://github.com/Zer0codestuff/OpenNaga/blob/a19e837a6f64cd9b394e62d50c899eb79861bac2/Sources/NagaController/Hardware/OnboardProfilePlan.swift):

- Its editor maps 19 controls; side IDs are `0x40..0x4b`. The inventory also
  includes IDs 9 and 10, which the editor leaves unchanged. Every-control
  coverage therefore needs further work, including wheel directions.
- Hold-to-HyperShift function block is `0c 01 01 00 00 00 00`.
- The reference rejects left-click as the onboard HyperShift trigger. This
  restriction requires distinguishing firmware evidence from application policy.
- Keyboard/mouse/media assignments are encoded onboard. The reference rejects
  macros, application launch, shell commands, and software profile switching
  for onboard save; this alone does not prove firmware can never support macros.

[Physical verification](https://github.com/Zer0codestuff/OpenNaga/blob/a19e837a6f64cd9b394e62d50c899eb79861bac2/Documentation/verification-2026-10-21.md):

The maintainer reports shifted wheel click/tilt with the app closed, shifted
wheel click after power cycling, and successful restoration of 84 descriptors
(two banks, two layers, 21 controls). Bluetooth HyperShift was not verified.
These are upstream physical results, not tests of this user's firmware.

[Save/restore implementation](https://github.com/Zer0codestuff/OpenNaga/blob/a19e837a6f64cd9b394e62d50c899eb79861bac2/Sources/NagaController/Hardware/OnboardProfileStore.swift):

It requires normal device mode, journals the original assignments, reads back
stored writes and the active mirror, and retains recovery data after incomplete
restoration. Its normal save order writes HyperShift before normal assignments
because of a reply-status side effect. Rollback ordering, durable journaling,
and receiver identity must be independently reviewed before adopting its design.
Do not treat an acknowledgment timeout as proof a write failed to reach hardware.

## V3: evidence and unresolved protocol

[Official product](https://www.razer.com/gaming-mice/razer-naga-v3-pro) identifies
the V3 Pro, interchangeable plates, five onboard profiles, and a remappable
underside profile control. Firmware command compatibility with V2 is unproven.

Reference: Naga Control tree/commit `824fac8a3951471af15a80586ac4c65d07c6bf00`.
[README](https://github.com/Rainexn0b/naga-control/blob/824fac8a3951471af15a80586ac4c65d07c6bf00/README.md)
explicitly lacks onboard binding upload. Its software remapping is not a
substitute for the requested onboard support. It uses a custom OpenRazer
backend, evdev/uinput, and Qt. Wired PID is `00e7`, receiver PID `00e8`.

[Integration findings](https://github.com/Rainexn0b/naga-control/blob/824fac8a3951471af15a80586ac4c65d07c6bf00/docs/integration-findings.md)
record special controls translated by its proposed driver into F13–F18,
with matching 12-button-plate input signatures on wired and receiver transport.
Alternate 6/2-button plates were captured over the receiver; wired equivalents
remain unverified. Both transports attached simultaneously collide in that
OpenRazer integration because of shared serial identity. These limitations
belong to the reference stack, not necessarily the hardware or our future app.

No V3 binding-bank commands, onboard HyperShift, or physical persistence tests
have been established for this project. REA/Synapse investigation should target
these gaps if published source and controlled read-only queries cannot resolve them.

## Accepted interview decisions — round 1

1. Onboard support plus a Linux background service. Clearly distinguish
   onboard mappings from software-only actions; never silently substitute them.
2. Keyboard keys/chords, mouse buttons, scroll, disabled buttons, profile
   switching, normal and HyperShift layers. Macros, turbo/repeat, and program
   launches are required, not deferred extras. Aim for the Synapse feature set
   with Linux compatibility, excluding RGB as already requested.
3. Program-specific profiles switch on focus, return to a default elsewhere,
   and support manual override.
4. The user is willing to set up a Windows VM if investigation needs Synapse.
   An existing VM has not been established. Final operation is Linux-only.
5. Native desktop app, tray menu, profile import/export, DPI stages, and
   polling-rate controls, targeting Hyprland/Wayland first.

## Accepted interview decisions — round 2

6. Prioritize both 2.4 GHz receivers and V3 USB wired operation. Bluetooth is
   deferred, not part of initial acceptance.
7. Only the 12-button side plate is required. All other electronic controls
   remain in scope: extra top controls, ring finger, underside profile button,
   wheel click, tilt, and scroll directions, as present on each model.
8. Hold-to-HyperShift on an assigned mouse button plus optional software toggle.
   Unassigned shifted controls retain their normal actions. Keyboard activation
   was offered as an optional extension; the user did not request it.
9. Macro recording and manual editing, adjustable delays, once/count/while-held/
   toggle playback. Cancel macros/turbo on leaving the program, changing profile,
   suspend, or disconnect; require a fresh press to restart. Include a configurable
   emergency-stop shortcut.
10. Explicit Save to Mouse for standalone mappings. Automatic focus switching
    must not repeatedly rewrite permanent memory. Temporary device assignments
    require model-specific verification; software-only execution is labeled.
11. Shared named profiles with per-mouse overrides and independent defaults/manual
    selection. The V3 ring-finger control has no V2 HyperSpeed equivalent; a shared
    HyperShift layer can use a different activation button on each device.
12. Retire input-remapper's handling of these mice only once a working product
    is proven ready. Preserve existing configurations for rollback. The user
    explicitly authorized investigating input-remapper and similar upstream
    projects for reusable code and ideas.

Round 3 confirmed persistent manual pins and authorized implementation. Optional
pointer-motion recording is deprioritized; the user's concrete shortcut/turbo
examples are in the [approved specification](specification.md). No device-setting
writes, exclusive grabs, or production-service migration have occurred.

## Direct receiver observations during implementation

The user connected the V3 receiver. Both receivers are now present; V3 is bound
to `hid-generic`, while V2 remains bound to `razermouse`.

- Read-only feature reports succeeded on V2 interface 0 and V3 interface 3.
  The V3 interface-0 attempt echoed a status-zero request instead of executing
  it; do not interpret that as unsupported firmware functionality.
- Direct usbfs control access returned EBUSY while the kernel owned the interface.
  No driver was detached; hidraw feature reports provide the working route.
- Both receivers reported firmware bytes `01 01` and normal-mode bytes `00 00`.
- V2 returned 21 inventory IDs. V3 returned 33; its enumeration requires a
  34-byte payload to include the count and full list, rather than V2's 22 bytes.
- Read 84 V2 descriptors (banks 0/1, two layers, 21 IDs) and 396 V3 descriptors
  (banks 0..5, two layers, 33 IDs). Receiving bank-tagged data does not by itself
  prove independent stored banks or safe writing semantics.
- Original snapshots are private, mode-0600 local JSON files under `evidence/`;
  they include identity information and are excluded from version control.
  These are raw read snapshots, not yet a tested transactional restore mechanism.
- V3 special-control IDs and HyperShift function bytes require further physical
  correlation. V2 physical naming must distinguish DPI IDs 0x0b/0x0c from tilt
  IDs 0x34/0x35; do not infer a label from inventory order.

The initial 20 automated tests cover the requested sequences, turbo/cancellation,
shared modifier ownership, HyperShift release pairing, local profiles/pins,
recording model, and V2 report framing. A native offscreen smoke check exercises
example import, persisted pinning, and macro step creation. None establishes
physical injection, onboard persistence, or final application readiness.

### V3 physical programming and power-cycle results

After explicit user authorization, the journaled writer temporarily assigned
F24 to stored bank 1, control `0x4b` (printed side button 12), normal layer.
The second guided attempt observed F24 press/release from the physical V3 input
device. The first attempt timed out because the user missed the test window;
it restored successfully and was not counted as physical verification.

A separately authorized combined test assigned F24 normally and F23 in the
HyperShift layer of the same button. The existing ring-finger trigger was not
modified. The user explicitly confirmed switching the mouse off and back on.
The physical input stream then reported complete F24 and F23 press/release
pairs for normal and shifted use, without a Gillete remapping service running.
Both original stored assignments and their active mirrors were restored and
read back successfully afterward.

This establishes persistence and hardware HyperShift for that tested control,
bank and key assignments on this receiver/firmware. It does not establish all
controls, all profile slots, wired operation, receiver unplug/replug persistence,
or complete app readiness. Transaction journals and explicit physical results
are retained privately under `evidence/`.

### V2 physical programming and power-cycle results

The user also authorized a combined V2 side-12 test. Its existing front
index-finger/DPI-up binding already performs firmware HyperShift and was not
changed. Stored normal and shifted side-12 assignments were temporarily set to
F24 and F23. After the user's explicitly confirmed power cycle, the mouse's raw
HID keyboard reports contained both complete press/release pairs. Reading raw
reports allowed this test without stopping input-remapper's existing V2 ownership.
Both original functions were restored and verified in stored and active views.

This verifies the tested V2 firmware outputs and persistence, not any behavior
input-remapper might subsequently apply to them. The application input service
still needs its own end-to-end acceptance. As with V3, receiver unplug/replug,
other physical controls, and full-product verification remain pending.

### Driver mode and live Linux software acceptance

Subsequent bounded captures identified all 25 in-scope V3 controls and all 21 V2
controls with down/up evidence. Both mice returned to normal mode with their
actual saved descriptors unchanged. The V2 retained its existing Synapse
customizations; the user suspended input-remapper manually before the second
capture, and Gillete has not resumed or removed it.

The first V3 software acceptance test exercised native input grabbing, uinput,
HyperShift, Ctrl+K then M, toggle-1 and program focus cancellation. The user
confirmed the sequence, then reported a specific F23 discrepancy. The original
saved V3 descriptors were restored and all 50 matched.

An isolated real Wayland test reproduced F23 becoming XF86TouchpadOff, even
without the mouse or engine: the default XKB inet symbols cause this. The
standard `fkeys:basic_13-24` option corrects the virtual keyboard's symbols.
Hyprland also needs `resolve_binds_by_sym=true` on this output so compositor
shortcuts use those corrected symbols. This behavior is documented in
[Hyprland's device configuration](https://wiki.hypr.land/configuring/core/devices/).
All F13–F24 pairs then reached the Qt test window correctly. A subsequent
physical V3 recheck also delivered F24 and HyperShift F23 down/up, confirmed by
the user and captured native scan codes/keysyms. Normal mode and all 50 original
saved descriptors were verified afterward. The remaining acceptance cases
below are still required.

## Completion evidence still required

The settings editor now supports separate current DPI and 1–5 stored stages,
selected-stage ordinals, linked/independent axes and 125/500/1000Hz receiver
polling. Limits are 30000 DPI for V2 and 50000 for V3, consistent with the
[V2 specification](https://mysupport.razer.com/app/answers/detail/a_id/6392/) and
[V3 specification](https://mysupport.razer.com/app/answers/detail/a_id/21025/).
The leading DPI payload byte selects storage1, independently of the active
profile ID. Original stage identifiers/reserved fields are preserved. A V2
physical read demonstrated current DPI1800 while selected stage1 was1200;
the editor and rollback retain this distinction. Coupled settings tests cover
uncertain SET acknowledgements and restoring the table before scalar DPI.
Physical setting writes/persistence testing remains pending a wake-up response.

- Completed app and packaging acceptance for the approved scope (interview,
  runnable development install and both control inventories are complete).
- Mapping and release behavior for every requested control in both layers.
- Persistent writes read back successfully, then physically exercised after
  mouse power cycle and receiver unplug/replug with the app/service stopped.
- V3 onboard slot enumeration, selection, preservation, and both layers.
- Multiple host profiles and correct game/program activation on Hyprland.
- Explicit separation of software actions from confirmed onboard assignments.
- Recovery from interrupted writes, held inputs, disconnect, and sleep/resume.
- CachyOS installation, permissions, service lifecycle, and removal instructions.

No requirement above is complete merely because a source project documents it
or a future mocked test passes. Hardware tests need these actual devices.
