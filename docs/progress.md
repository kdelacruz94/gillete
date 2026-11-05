# Current implementation state

The interview is complete and implementation is authorized. Follow
`specification.md`; do not repeat the design interview or ask for its approval.
The user wants a finished native CachyOS/Hyprland app for both Naga mice, with
real onboard bindings, every control, HyperShift, macros/turbo, program profiles,
DPI/polling controls and migration only after verification. RGB, Bluetooth and
other side plates are deferred. Pointer-motion macros are optional.

## User-specific constraints and current state

- The V2 has custom assignments saved by Synapse on Windows. Original means the
  actual captured assignments, never factory defaults. Several firmware actions
  are not yet decoded for software execution. Preserve their raw bytes.
- During the first V2 driver-mode capture, the user manually stopped/suspended
  input-remapper's V2 mappings and requested a restart. The second capture passed.
  Gillete did not stop, resume, remove or migrate input-remapper. Leave the user's
  suspended state alone unless instructed otherwise.
- Both physical mice are restored to normal mode. No guided capture or Gillete
  service is running. The first live V3 test passed normal F24, Ctrl+K then M,
  toggle-1 and focus-loss cancellation. Shifted F23 exposed a desktop keymap
  problem; the correction now passes both an isolated real Wayland test and
  the user's physical V3 recheck.
- The user is willing to set up a Windows VM if protocol work requires it; none
  has been provisioned. REA has now inspected upstream recorded captures; no
  native binary target has been opened. See `remaining-protocol-research.md`.

## Latest user interaction

The user approved and completed the live V3 software test, initially reporting
all steps worked, then noting F23 appeared as Qt key 16777490 instead of F23.
That value is TouchpadOff. It was an actual desktop translation issue, not just
a missing label. The fix is implemented and the user confirmed both F24 and F23
on the physical V3 recheck. Test3 exited 0; normal mode and all 50 saved
descriptors were verified unchanged. No guided test is running. A later async
question to wake the V2 for settings preparation is currently pending (see below).

The completed retest command was:

```sh
.venv/bin/python -u -m gillete.guided_service --directory evidence/v3-software-test3.local --seconds 180
```

Use a new directory for any future test. The command opens a foreground input
pad, creates an isolated config, starts a private daemon, enables only the V3,
and prints READY after actual activation. Tell the user to use the test window:
side 12 = F24; ring + side 12 = F23; side 11 = Ctrl+K then M; rear button behind
wheel toggles repeated 1. Start repeat again and leave the window to test focus
cancellation. Closing the pad ends the test and restores normal mode. No existing
local profile file is changed. The helper verifies all 50 stored descriptors.

Inspect output before claiming READY or success. The V3 often sleeps: timeout on initial read means no change;
ask the user to wake it and retry the already-authorized test. The helper's
shutdown/timeout paths deserve another check before a live run. Do not kill a
service without checking/restoring its mode journal afterward.

## Installed development build

- `.venv` uses **/usr/bin/python 3.14**, system site packages (PySide6 6.12 and
  evdev), editable Gillete install. Default uv initially selected 3.12; that
  fresh unusable venv was replaced with this explicitly selected interpreter.
- `~/.local/bin/gillete` links to this checkout's `.venv/bin/gillete`.
- `~/.local/share/applications/org.gillete.Gillete.desktop` installed.
- `/etc/udev/rules.d/70-gillete.rules` installed after `udevadm verify` passed.
  It adds uaccess only for HID VID 1532, PIDs 00b4/00e7/00e8. Reloaded rules and
  triggered only the connected supported hidraw nodes. Normal-user read/write
  access was verified for both mice. No input or OpenRazer daemon was restarted.
- `dist/` contains a built Arch package, wheel and source archive. Staged Arch
  launcher/GUI/CLI and a separate wheel install passed. The package is not
  installed system-wide and full hardware acceptance remains incomplete.
  No systemd service was installed/enabled.
- No remote or PR exists. Source is checkpointed locally in git on main.
  Private evidence is ignored (`*.local.json`, `*.local.lock`, `*.local/`).

## Implemented modules

- model/profiles: validated actions, shared mappings + per-model overrides,
  normal/shifted layers, revision-checked atomic persistence, focus rules, pins.
- macros/engine/recorder: timed sequential chords, repeats/turbo, cancellation,
  shared output ownership, press-time release pairing, fresh-press disarming.
  Unchanged stored primary-button drags survive focus changes; disconnect,
  suspend and emergency stop release them. Pointer recording is optional.
- gui/gui_recording: native profile CRUD/import/export, macro editor/recorder,
  rule editor, overrides, tray, scroll/DPI/native V3 action editors. Recorder
  uses kernel monotonic timestamps and sorts interfaces. Real recording still
  needs acceptance. Failed local saves roll back the displayed configuration.
- applications/gui_launch: installed desktop-app picker via GIO/GioUnix, saved
  desktop IDs resolved at launch, and an executable browser retaining explicit
  argv. Missing apps and failed commands report an action error without tearing
  down mouse control. Action editing shows only fields relevant to its kind.
  Dependencies now include python-gobject and GLib2.84+ (present on this host).
- gui_controls/gui_applications: all 21/25 controls selectable in both layers,
  and a running-window picker for program rules. Picked application IDs/titles
  are escaped as literal glob patterns. Title matching is optional.
- The tray now has per-mouse profile pins/Automatic, enable/disable and emergency
  stop. Closing the editor hides it if a tray is available; Quit editor exits.
  Live pin requests go through the service's validation and durable save.
  Offline pins read the latest file first, preserving unrelated external edits.
- protocol/hid/devices: strict 90-byte feature framing (91 including report ID),
  sysfs discovery, exact receiver config interfaces, metadata/binding reads.
  Profile count/list/active queries have a narrowly scoped zero-size-response
  exception. List accepts compact declared length or zero-size padded results.
- onboard/compile_onboard: journaled binding writes, readback, uncertain-write
  rollback, serial/mode checks, original response-flag preservation. Unsupported
  software actions block saves. Keep-stored preserves existing shifted actions,
  including unknown Synapse bytes; explicit normal mappings inherit normally.
- hardware/gui_hardware: asynchronous inspect/preview/save/recovery, assigned
  slot checks, stale-preview rejection, readable current binding descriptions.
  Slot backup exports both layers including opaque functions and reply flags.
  Reported battery and firmware are displayed after Read mouse when available.
- settings/gui_settings: native DPI/stage/polling edit and before/after review,
  independent X/Y or linked axes, stage count/selection, hardware limits, stale
  preview checks and coupled-setting recovery. New `device-settings` journals
  restore stages before scalar DPI, then polling. No physical setting writes
  have been performed yet; acceptance is pending.
- driver_mode/driver_capture: durable reversible temporary mode ownership and
  raw mouse-only capture with no input grabs. CLI `recover` handles bindings,
  mode and supported setting journals.
- reports/runtime/stored_actions: all receiver control reports decoded, combined
  interface states, wheel pulses, uinput adapter, exact known stored functions.
  Unknown firmware functions block software activation rather than substituting
  defaults. Native V3 wheel/profile controls have explicit action types.
- device_controls: serialized, journaled DPI-stage/native wheel actions; not yet
  physically accepted. Multiple hardware-bank cycling in the live service is
  explicitly unavailable. DPI buttons now use storage1 and one-based selected
  ordinal, preserve identifiers, and set the scalar DPI through the coupled
  transaction. Physical active/scalar acceptance is still required. Native wheel getter/setter use 02:B0/30
  from the pinned OpenRazer fork; local reads so far timed out while asleep.
- device_session/service/emergency: explicit per-mouse enable, all-interface
  evdev grabs, raw HID routing, user uinput output, focus selection, persistent
  pins, argv-only launch, device ownership/identity checks, mode restore,
  reconnect attempts, idle-gap and active-hold wireless liveness checks,
  logind PrepareForSleep monitor, private same-UID Unix socket.
  Service starts with both mice disabled by default; explicit Startup choices
  apply at the next start after focus/suspend/shortcut preflight. Ctrl+Alt+Pause is added only when
  enabling; an existing different binding blocks activation. Removing the
  shortcut only removes this app's unchanged binding.
- keyboard_map: per-output Hyprland `fkeys:basic_13-24` plus
  `resolve_binds_by_sym=true`, applied before grabbing physical input. Preserves
  other options and restores its own option change. A one-second monitor stops
  the session if a config reload/edit removes the correction; re-enable to
  recheck. Symbol-based binding policy is restricted to the ephemeral output.
  Does not edit Hyprland files or configure physical keyboards/mice.
- gui_service: service start/stop, per-mouse enable/disable, emergency stop, live
  status/tray tooltip. GUI can close while daemon continues. Hardware panel needs
  software control disabled because the service owns the HID transport lock.
- startup/gui_startup/gui_instance: opt-in Hyprland/UWSM XDG desktop startup,
  separate per-mouse startup choices, and one editor per profile file. A second
  launch reopens the existing hidden window; a crashed editor's socket is
  reclaimed only after acquiring its process lock. Startup saving never enables
  a current session. A conflicting autostart entry is preserved. Existing
  profile configurations load with an empty startup selection.
- Service requests from the GUI carry the exact profile path; a different
  configuration cannot accidentally control the current daemon. Enable/disable
  commands are serialized, shutdown waits for shortcut ownership verification,
  and supervisors stop before session cleanup. Focus-monitor loss rejects new
  translated input and restores normal mode until monitoring returns.
- validation_pad/guided_service: prepared bounded V3 software acceptance test.

## Verification completed

Latest completed suite: **113 tests passed**, including settings failure/recovery,
startup/service recovery, real editor processes, native settings/control/application
dialogs and tray profile changes. The native editor and validation pad
both passed offscreen open/close smoke checks. Explicit Qt top-level deletion
before QApplication shutdown avoids a Python 3.14/PySide6 6.12 teardown crash.
Tests also explicitly destroy Qt widgets before their QApplication.

Real kernel uinput test passed as the normal user: its own temporary virtual
input node was exclusively grabbed before emitting F24 down/up and REL_X.
All three events were read back; no physical mouse was grabbed or mode-changed.
Read-only daemon startup reported focus and suspend monitoring ready, both mice
disabled, and exited cleanly on shutdown. This is not live remapping acceptance.

### Physical tests, all restored

- V3 side 12 normal F24: physical evdev down/up, restore verified.
- V3 normal F24 / shifted F23, existing ring HS trigger unchanged: user confirmed
  power cycle; both down/up pairs detected. All 396 original descriptors across
  readable banks subsequently matched byte-for-byte.
- V2 same combined power-cycle test, existing front-index HS trigger unchanged:
  raw HID F24/F23 down/up detected despite input-remapper ownership. All functions
  restored. Reply flag initially differed; same-value shifted write restored it.
  Programmer now preserves flags automatically (including rollback disk failures).
- V3 driver-mode capture: all **25** controls identified with press/release.
  Native vendor report 4 codes: DPI up/down 20/21, ring 59, top front 54,
  top rear d2, underside profile 50. Side keys on iface02: 1e..27,2d,2e.
  Pointer iface00: buttons 01/02/04, tilt bits 20/40, wheel signed byte3.
  Normal mode and all 50 bank-1 descriptors verified unchanged.
- V2 restarted driver-mode capture: all **21** controls identified with
  press/release. OpenRazer turns DPI vendor reports into numbered keyboard
  usages 68/69 on iface01. Other report layouts match the decoder.
  Normal mode restored; all **84** original active/stored descriptors matched
  the first Synapse-configured snapshot exactly. First V2 capture was interrupted
  at the user's restart request and separately verified restored before retry.
- V3 live software test1: emergency shortcut setup rejected the obsolete
  Hyprland keyword API before physical input ownership. Fixed with Lua
  `hl.bind`/`hl.unbind`, verified readback and crash-recovery receipt. Original
  50 descriptors unchanged.
- V3 live software test2: user confirmed F24, chord, toggle and focus cancellation.
  Service samples show turbo active at 95.9s, default profile and zero jobs at
  97.4s, return to validation with zero jobs at 98.9s. F23 was TouchpadOff.
  Controller ended cleanly via SIGINT; normal mode and all 50 original saved
  descriptors were verified unchanged. No service remains running.
- V3 live software test3: after the correction, user confirmed both F24 and F23.
  The pad recorded F24 scan202/keysym65493/Qt16777287 and F23
  scan201/keysym65492/Qt16777286, each with complete down/up pairs. Closing the
  pad ended the service and restored normal mode; all 50 originals matched.
  Evidence: `evidence/v3-software-test3.local/{input,service,restoration}.json`.

### F23 diagnosis and fix

`.venv/bin/python tools/diagnose_fkeys.py --raw --uncorrected` reproduced
KEY_F23 (193), XKB scan 201, keysym 269025201, Qt TouchpadOff (16777490).
Removing the engine and mouse did not change it. A clean `xkbcli compile-keymap
--layout us` confirmed the default inet symbols assign this alias. Applying the
standard `fkeys:basic_13-24` option only to the virtual keyboard produced F23
keysym 65492, Qt F23 (16777286), with complete down/up pairs.

Expanded F13–F24 testing found Hyprland's global shortcut keymap still consumed
F20 as XF86AudioMicMute. The first expanded test triggered that shortcut once;
the microphone was observed muted afterward and left alone (prior state was not
recorded). The user was informed. `resolve_binds_by_sym=true` on only the virtual
output corrected this second issue. The full engine → uinput → Hyprland → Qt
test then passed all F13–F24 pairs. Test command:
`.venv/bin/python tools/diagnose_fkeys.py --all-function-keys`.

The diagnostic opens a short-lived focused window and never opens physical
mouse interfaces. Unit tests cover preserving options/layout, Lua/legacy APIs,
rejected configuration, user edits, device replacement and restoration. The
validation pad now records actual Qt code, scan code and keysym and names
unexpected keys accurately; it never relabels TouchpadOff as F23.

Remaining limits: the standard XKB option retains secondary special levels for
Super+Shift+F23 / Super+Ctrl+F24; these unusual chords need separate validation.
Physical onboard F-key output still depends on the destination OS keymap.

Private evidence is in `evidence/`: initial 00b4/00e8 snapshots, side12 and
combined-test journals/results, `v3-driver-{test,capture}1.local.json`,
`v3-driver-results.local.json`, V2 driver attempts 1/2 and driver results.
Files produced by sudo were chowned back to the checkout owner, staying 0600.

## Hardware facts and sources

- V2 receiver 1532:00b4 config iface00; V3 receiver 1532:00e8 config iface03.
  Last observed raw nodes V2 2/3/4, V3 9/10/11/12; always rediscover.
- V3 wired 00e7 is recognized but config-interface support remains gated pending
  local validation. Upstream fork routes wired control differently; do not infer
  receiver interface03 works wired.
- Unique hardware serial via 00:82 works on both, including V2's all-zero USB
  descriptor serial. Do not print serials publicly.
- Bank0 is active mirror, not a proven volatile-write target. V2 assigned list
  reports only bank1; active-profile getter rejects, so single-slot active=1.
  V3 slot inspection now succeeds in the live test startup. Readable banks are not
  necessarily assigned/selectable profiles. No create/delete probes performed.
- Pinned OpenSnek b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2 source cached under
  `/tmp/gillete-research/OpenSnek/`; source archive also cached. Its Naga captures
  establish body IDs 0b/0c/0e/34/35/39/6a/80 plus side40..4b. Separate wired
  capture exists. USB_PROFILE_CRUD_SPEC explains profile inventory semantics.
- Pinned OpenRazer fork 26b0eeb5ed70d638fa3528851adcd5e58369a7f5:
  `/tmp/gillete-research/naga-control/openrazer-26b0eeb.c` and chroma-26b0eeb.c.
  It confirms vendor 59/d2 and newer wheel mode 02:B0 read / 02:30 write with
  payload 01,mode (0..2), unlike the unsupported 02:94 old protocol.
- OpenSnek ButtonBindingSupport identifies 0d04 keyboard turbo and 0e03 mouse
  turbo, but its rate conversion is not locally measured. Keep existing raw
  V2 turbo functions intact; do not guess their software timing. Class05 now has
  an upstream macro-toggle interpretation, but reference0000 content/behavior
  remain unresolved. OpenNaga and Naga Control/source-license notes are in
  `feasibility.md` and `reuse-investigation.md`.
- Exact V2 undecoded controls from the preserved bank1 snapshot: normal tilt
  left/right are keyboard-turbo PgUp/PgDn (`0d04004b008e00` /
  `0d04004e008e00`); shifted left click is `0e0301008e0000`; shifted side7 is
  `0d04001c008e00` (Y turbo). Shifted sides1,2,4,10 contain
  `05020000000000`, still unknown. All remain preserved; no software substitute
  has been chosen. Existing input-remapper presets remain untouched under
  `~/.config/input-remapper-2/presets/Razer Razer Naga V2 HyperSpeed/`.

## Still required before completion/migration

1. Broader service acceptance beyond the completed V3 core test; all callbacks,
   virtual-input exclusion, focus transitions, launch, sleep, disconnect/reconnect.
2. Preserve/interpret or explicitly map remaining V2 Synapse firmware actions;
   live V2 acceptance without silently losing them.
3. Physical DPI/stage/polling acceptance (editing/recovery are implemented); slot
   selection/CRUD evidence; wired transport; receiver unplug/replug persistence.
4. Real recorder acceptance, real-login startup acceptance,
   system package install/remove verification and eventual agreed input-remapper
   migration. Overall goal is not complete.

## Current hardware interaction and delivery work

No subagent was requested or started. Continue the existing app goal; do not
repeat the V3 core acceptance.

The settings editor and transactions are now implemented. A read-only prepare
attempt for `evidence/v2-settings-test1.local` timed out on the initial mode read;
it created no test directory and changed no settings. An async question asks the
user to wake the V2 and reply Awake, or choose Later. Do not treat elapsed time
as readiness. Once awake, run:

```sh
.venv/bin/python -m gillete.settings_check prepare --product 00b4 --directory evidence/v2-settings-test1.local
```

This only reads and prints exact proposed changes. Review those values with the
user before the separate `run --directory ... --seconds 180` command. The bounded
test has a native window where the user confirms a power cycle, verifies the
new settings, then restores all originals and compares every stored binding.
Closing the window/timeout also restores. Retain `settings.json` for recovery if
the mouse is disconnected/off and restoration cannot complete. The test window
passed an offscreen open/close smoke check without hardware access.

Packaging: `tools/build_arch.py` stages an sdist + checksum-pinned PKGBUILD in a
temporary directory and uses isolated Python build dependencies. Nothing is
installed/enabled. An initial build failed because installer has no CLI
`--interpreter`; the recipe now uses its public API with explicit `/usr` paths
and `/usr/bin/python`. The corrected build passed. `tools/check_package.py`
verified the staged `/usr` paths/launcher, native GUI open/close and CLI, plus a
separate wheel installation in a temporary virtual environment. Nothing was
installed system-wide. Artifacts are `dist/gillete-0.1.0-1-any.pkg.tar.zst`,
`dist/gillete-0.1.0-py3-none-any.whl`, and `dist/gillete-0.1.0.tar.gz`.
Native dependencies remain declared in PKGBUILD. No build process remains live.

Critical protocol findings from the pinned OpenRazer `chroma-26b0eeb.c`:

- 04:85/05 (7-byte scalar DPI) and 04:86/06 (38-byte stage table) begin with a
  **storage selector**, not an onboard profile slot. `VARSTORE=1`. This is now
  corrected in `hardware.inspect`, `settings` and `Controls.dpi`.
- Stage-table byte1 is a **1-based selected-stage ordinal**; byte2 is count1..5.
  Five 7-byte records begin at byte3: identifier, X:u16be, Y:u16be, reserved2.
  The pinned upstream setter emits identifiers0..4 but active ordinal1..5.
  The physical V2 read emits identifiers1..5. Preserve identifiers/reserved
  bytes. `Controls.dpi` now uses the ordinal correctly, with regression cases
  for both identifier conventions and an active profile other than1.
- Physical V2 read-only query after the V3 test: scalar
  `01070807080000` (1800×1800), stage table
  `0101050104b004b000000203e803e800000304b004b000000406400640000005070807080000`
  (selected ordinal1, values1200/1000/1200/1600/1800), polling `01` (1000Hz).
  Thus scalar and selected-stage values can differ. Preserve both independently;
  do not overwrite scalar DPI merely because an unchanged stage is displayed.
  V3 was asleep and its normal-mode read returned DeviceStatusError timeout.
- Polling getter00:85 and setter00:05 have one byte:1=1000,2=500,8=125Hz.
  Only these receiver rates are in scope; extra high-polling dongles are not
  currently discovered/supported.
- Razer primary specs confirm V2 maximum30000 DPI and V3 maximum50000 DPI:
  https://mysupport.razer.com/app/answers/detail/a_id/6392/
  https://mysupport.razer.com/app/answers/detail/a_id/21025/
  Pinned driver scalar setter uses minimum100. Do not assume V3 is35000 DPI.

Implemented tests cover stale preview, uncertain ACK after each write, partial
write, rollback failure, disk-full status update, invalid recovery payload,
wrong serial/profile/mode and Qt editing flow. Final readback checks the entire
coupled group. No-op editing preserves the observed V2 scalar/stage mismatch.
Physical testing must still establish setting behavior and persistence.

The registered goal may still display blocked from an earlier unanswered
interview; all those questions have since been answered. The goal tool has no
active/resume mutation. Continue authorized work without creating a duplicate
or marking this incomplete application complete.

## Startup implementation and software verification (November 5)

The local initial source checkpoint is `ac8f71b`. The next implementation adds
the Startup tab and single-instance editor behavior. No desktop startup entry
or startup mouse choice was enabled for the user's real configuration. No
mouse mode or stored setting was changed by these checks.

- Profile tests cover backward-compatible disabled defaults, persisted startup
  choices, invalid selections and preserving unrelated external edits.
- A temporary Desktop Entry was executed by the real GLib/GioUnix launcher to
  verify spaces, quotes, backslashes, percent signs and shell-looking text all
  arrive as literal argv values. This launched only a temporary argument recorder.
- Separate real Qt processes verified reopening a hidden editor and reclaiming
  the socket after a simulated crash. Tests use isolated runtime/config paths.
- Real local service sockets with a simulated device session verified startup
  preflight, configuration identity checks and shutdown cleanup. Separate cases
  cover disabling a pending startup choice, shortcut conflict, focus loss and
  cancellation during shortcut installation.
- A real desktop integration check used an isolated empty profile configuration
  and an offscreen editor with `start_service=True`. Actual Hyprland focus and
  logind suspend monitoring became ready, both mice remained disabled, a second
  GUI launch reused the same daemon socket, and both processes shut down cleanly.
  No physical input interfaces were opened for remapping.

The underlying desktop on this host uses UWSM and has an active
graphical-session.target. Startup follows the
[XDG autostart specification](https://specifications.freedesktop.org/autostart/latest/)
and [Desktop Entry argument rules](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).
Plain Hyprland without an autostart manager is documented with the explicit
`gillete gui --background --start-service` session command. A real login and
enabled-mouse startup test remain part of final acceptance after cutover approval.

The rebuilt Arch package and wheel passed `tools/check_package.py`, including
the new startup/single-instance modules, staged native GUI and separate wheel
installation. The complete automated suite passed 107 tests. Final read-only
inspection confirmed the user's `startup_models` is empty, desktop startup is
off, and no Gillete service or hardware test remains running. The V2 wake-up
question is still pending; do not infer readiness from the software checks.

## Program launching and remaining protocol evidence

The research skill explicitly called for a background research agent. One
delegated investigation completed and wrote `remaining-protocol-research.md`;
there is no ongoing delegated task. It inspected upstream BLE captures with
REA and derived their ATT payloads offline. The captures establish stored turbo
parameters but have no HID playback stream to measure timing. OpenSynapse source
identifies function05 as a toggle-macro reference; the V2's reference0000 remains
unresolved. The GUI now describes these families without treating them as known
software actions. Raw originals and unresolved-activation guards are retained.

The wired research found that both USB descriptor sets advertise a 90-byte
feature report on interface03, while the Linux fork sends wired control queries
with wIndex0. This discrepancy still requires a bounded read-only check on the
actual cable connection. It does not justify adding E7 to the verified transport
map. The document gives exact query candidates and driver/descriptor boundaries.

An additional async question asks what the user's existing V2 HyperShift+side
1/2/4/10 macros should do. This can identify intended sequences that are absent
from the binding records. It does not replace the unanswered wake-up question.
No hardware query, setting change, remapping activation or user-app launch was
performed in this continuation.

Program-launch checks used temporary applications and scripts only. Actual GIO
registry resolution verified user-entry precedence, Hidden/NoDisplay/desktop
filtering, literal arguments and the configured working directory. A private
`dbus-run-session` test verified D-Bus activation instead of Exec fallback.
Engine-to-launch checks covered both layers, one launch per physical press,
missing programs and nonzero exit status. The real user's app registry was read
once (94 visible entries), with no launch. Full suite:113 passing tests.

## Macro timing and capture recovery

The recorder now offers recorded timing or a fixed delay between captured events,
including zero delay. The shortcut-sequence builder exposes key-hold and
between-chord times. Bulk delay replacement changes only explicit wait steps,
preserving event order and adjacent chord members.

Capture setup counts an interface only after clock selection, capability checks,
held-key inspection and notifier creation succeed. Media-key-only and relative
mouse interfaces are eligible. Dropped input, disconnect or failed setup closes
all sources and permits a clean retry in the same dialog; a queued callback from
an old source cannot discard the new recording. F12 remains excluded from the
macro. Stopping during a chord records its final hold duration and releases its
keys in reverse order. Invalid timestamps cannot mutate key ownership, and step
limits include automatic key releases and their delays.

The complete suite passes 125 tests. New cases exercise multi-interface ordering,
shared modifiers, pre-held keys, mouse clicks/wheel, virtual-input exclusion,
fixed/recorded timing, F12 during a hold, capture failure/retry, and editing the
Excel shortcut sequence's timing. These tests use simulated input sources and
offscreen Qt dialogs; real desktop macro recording still needs acceptance.
Three abandoned earlier pytest processes were terminated; the current bounded
suite exited normally. No physical input source was opened, mouse setting was
changed, remapping was activated, or startup preference was enabled in this work.

The V2 wake-up and existing-macro-intent questions remain unanswered. Continue
with their responses before the corresponding physical tests. Wired transport,
physical DPI/polling acceptance, per-profile sensitivity and final migration
remain unfinished; the goal is not complete.

## HyperShift reachability and inherited triggers

The editor now distinguishes a configured normal-layer trigger, an inherited
trigger from the last active-slot read, an unverified inherited possibility and
an unreachable custom shifted layer. Snapshot invalidation clears the inherited
claim; another model's or an inactive slot's snapshot cannot prove the active
trigger. The same analysis protects software activation and configuration reloads
after stored actions have been decoded. V3-only shifted controls are excluded
from V2 reachability checks. A held scroll-direction trigger is unusable in the
software event stream because each wheel event has an immediate release; the
editor explains using a held button or software toggle instead. New onboard
held-scroll trigger assignments are rejected, without rewriting existing ones.

Software resolution now keeps a normal-layer inherited HyperShift trigger usable
while another trigger is held, matching explicitly assigned trigger behavior.
Its opaque shifted descriptor is not executed or rewritten. The editor shows
this effective trigger on both layers and directs edits to Normal. Onboard
compilation preserves both original descriptors for an inherited trigger and
does not treat arbitrary class0c bytes as a known trigger. An explicit new normal
trigger still compiles to both layers.

All 133 tests pass, including engine/router behavior, toggle cancellation,
per-model overrides, service preflight before input/output ownership, editor
snapshot lifecycle and opaque-descriptor preservation. Offline checks against
the original saved hardware captures preserve all 42 V2 and 50 V3 bank1 functions
exactly, identify the actual front-index/ring triggers, and leave the V2's eight
opaque functions unresolved. Both profiles from the successful physical V3
software test also pass the new preflight offline. No new hardware test or
physical write was performed; these checks do not replace live acceptance.

Per-profile sensitivity remains a separate required gap. Focus switching must
not call the existing permanent-settings transaction. The pinned Linux fork's
scalar DPI setter (`openrazer-26b0eeb.c`, switch around lines2620–2633) uses
VARSTORE for V3, while V2 HyperSpeed falls through to NOSTORE. This supplies a
candidate temporary V2 path, not proof for either physical device. Verify live
readback and independence from saved DPI/stages before enabling profile DPI
transitions; do not substitute pointer scaling or permanent writes silently.
