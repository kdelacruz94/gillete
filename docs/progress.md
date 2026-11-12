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

The user has now answered both outstanding questions: **Later — continue building**
for the V2 hardware session, and the old HyperShift+side1/2/4/10 bindings were
MapleStory gameplay macros that **do not need to be kept**. They will recreate
those macros once the tool is confirmed working. Do not ask again what those
four macros did or require recovering reference 0000 before V2 software validation.
The next isolated V2 validation profile should explicitly disable those four
shifted assignments; original device bytes still belong in the test-restoration
backup. This does not retire the four other opaque V2 turbo functions or authorize
inventing their timing. Physical tests remain deferred; neither mouse was changed.
Earlier notes below about unanswered questions describe older checkpoints.

The user approved and completed the live V3 software test, initially reporting
all steps worked, then noting F23 appeared as Qt key 16777490 instead of F23.
That value is TouchpadOff. It was an actual desktop translation issue, not just
a missing label. The fix is implemented and the user confirmed both F24 and F23
on the physical V3 recheck. Test3 exited 0; normal mode and all 50 saved
descriptors were verified unchanged. No guided test is running. A later async
question to wake the V2 for settings preparation was answered Later, as noted above.

Future software tests now require separate preparation and execution (the old
single-command V3 harness used for test3 has been replaced):

```sh
.venv/bin/python -m gillete.guided_service prepare --product 00b4 --directory evidence/v2-software-test1.local
# Review the printed overrides with the user before starting live control.
.venv/bin/python -u -m gillete.guided_service run --directory evidence/v2-software-test1.local --seconds 180
```

Use a new directory per attempt and product00e8 for the V3 receiver. Preparation
only reads; execution checks the prepared mouse state before starting an isolated
service. The pad's countdown starts after actual activation in that focused window.
On both mice, side12 = F24, HyperShift+side12 = F23, side11 = Ctrl+K then M.
The V2 front index button is the trigger and rear index button toggles repeated1;
V3 uses the ring button and rear button behind the wheel. Leaving the window
cancels repetition; returning requires a fresh press. Known stored actions remain
outside the pad, with explicit unknown/settings masks documented in the preview.
Both original layers, profile inventory/selection and saved DPI/stage/polling
values are compared after mode restoration. No regular profile file is changed.

Inspect output before claiming READY or success. The V3 often sleeps: timeout on initial read means no change;
ask the user to wake it when they resume the deferred physical session. Commands
are bound to the test's configuration identity, mode journals are isolated under
its run/state directory, and evidence failures cannot skip recovery. Do not kill
a service without checking/restoring its mode journal afterward.

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
- validation_plan/validation_pad/guided_service: reviewed, bounded V2/V3 receiver
  software acceptance tests with isolated configuration/state and restoration.

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
  `05020000000000`, still undecoded but retired by the user. The isolated test
  disables those four macros and temporarily masks the other four unknown turbo
  actions; it never guesses their timing. All saved bytes remain preserved.
  Existing input-remapper presets remain untouched under
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
it created no test directory and changed no settings. The user chose Later and
asked to continue building. Do not treat elapsed time as readiness. When the user
resumes hardware testing and wakes the mouse, run:

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
not call the existing permanent-settings transaction. **Correction after tracing
the packet builder:** the driver caller selects VARSTORE for V3 and NOSTORE for
V2 HyperSpeed, but `razer_chroma_misc_set_dpi_xy` in the same pinned fork ignores
that parameter and always sets byte0 to VARSTORE. The caller is therefore not
evidence of a temporary V2 write. The getter does honor the selector. Verify live
readback and independence from saved DPI/stages before enabling profile DPI
transitions; do not substitute pointer scaling or permanent writes silently.

## Explicit standalone alternatives in a named profile

Profiles now have optional per-model `standalone` normal/shifted mappings. Older
profiles load with no alternatives. JSON persistence, duplicate and import/export
retain the choices. `Profile.resolve` remains the Linux software mapping;
`for_onboard` overlays alternatives only for compilation to mouse memory, without
mutating the original layers. An unassigned shifted action follows the standalone
normal action, while an explicit software shifted assignment still needs its own
alternative if unsupported. A stored-assignment alternative preserves raw bytes
from the chosen mouse layer. Different mouse models retain independent choices.

The native **Standalone mappings…** editor saves choices locally, lists the Linux
and standalone actions, and offers edit, keep-stored and follow-profile actions.
Its action editor restricts choices to supported families and validates key/chord
encodings. Save preview now shows all button layers with Linux action, current
mouse assignment and actual proposed bytes decoded for display. It lists remaining
blockers, including a standalone shifted alternative that would be hidden by an
inherited normal HyperShift trigger. Zero-change choices remain locally usable
without a pointless hardware save. The same identity/stale-preview checks,
write journal and restoration path cover compiled alternatives.

All 147 tests pass. New coverage includes model-specific compilation, actual Linux
macro playback with a different standalone key, explicit shifted alternatives,
trigger conflicts, old-profile parsing, import/export roundtrips, invalid imports,
GUI cancellation/local-save failure and simulated onboard save/restore. An offline
check on both original saved captures produces F24 on side12's normal/shifted
layers only, retaining the other 40 V2 / 48 V3 functions and the Linux macro.
No physical writes, live remapping, startup changes or input-remapper changes
were performed. Native firmware macro/turbo support, per-profile sensitivity,
wired operation and full physical acceptance remain unfinished.

## Bounded firmware read diagnostics

`python -m gillete.firmware_probe` is an explicit development diagnostic for
the verified B4/E8 receiver routes. It captures normal mode, identity, assigned
slots, active/stored button descriptors and saved settings before and after
candidate reads. Its separate `FirmwareQueryHID` accepts only bounded class06
getter shapes; the ordinary application's allowlist remains unchanged. There
are no macro allocation/write/delete methods. It never starts a service, grabs
input, switches mode or writes settings. Keep hardware use deferred until the
user is ready; this continuation performed sysfs discovery only, with both
receivers present and no E7 cable transport.

The macro reader queries storage/count, then enumerates at most 128 nonzero IDs.
Actual ID-page declared lengths are 4+2n (n<=32), and memory lengths 7+n (n<=72),
matching the pinned upstream service rather than blindly using the command
definitions' 80-byte maxima. It validates ID/offset/length echoes, stops a query
family on rejection or malformed data, and never dereferences reference 0. Raw
data capture is optional and limited to 4096 bytes per macro/8192 total. A probe
has a 512-query limit, a 40-second deadline checked between requests, and reserved
query budget for the final state comparison. A kernel ioctl can still exceed
the between-request deadline. Reports are new-only, with permissions 0600 and new
parent directories 0700; terminal summaries omit device identity and macro contents.

DPI diagnostics only query storage selectors 1 and 0. Matching or different read
values cannot establish nonpersistent setters. Empty/rejected macro catalogs do
not establish the meaning of old reference 0 or prove firmware macro support
absent. The new tool remains useful for investigating new native macros even
though the user's four old MapleStory macros no longer need recovery.

All 165 tests pass. New checks cover request rejection, dynamic pages/chunks,
zero/duplicate IDs, data bounds, malformed echoes, stale HID frames without a
resent request, preflight sleep/driver-mode failures, external state differences,
query/time limits and private report handling. No candidate getter was sent to
a physical mouse, and no hardware readiness or new capability is claimed.

## V2/V3 software acceptance preparation and lifecycle

The old V3-only harness now has separate `prepare` (read-only) and `run` commands
for both receivers. `validation_plan` builds model-specific profiles without
opening hardware. It explicitly disables the four retired V2 MapleStory macros,
temporarily disables other undecoded functions without interpreting their bytes,
and masks stored DPI/native device-setting actions to prevent accidental writes.
These masks apply inside and outside the pad. All other known original actions
retain passthrough, including pointer drag ownership and known shifted actions
whose normal assignment is masked. The ordinary stored-action decoder and
unknown-action activation guard are unchanged.

The preview records raw originals and effective inside/outside actions for every
changed control/layer. Both mice test side12 F24/F23, side11 Ctrl+K then M and
toggle1 at a 200ms interval. V2 uses front index as held HyperShift and rear index
for toggle1; V3 uses ring/rear-wheel buttons. Outside the pad, those test buttons
return to their known stored actions (the V2 rear index is currently LeftCtrl).
No regular profiles or startup preferences are changed.

Execution checks the original identity, bindings, assigned/active slot, inventory
and saved settings before activation. The test directory is claimed once. All
service commands include its unique config path; daemon mode journals use its
private XDG state directory. PID/title identify the pad, wildcard characters are
escaped, and READY requires the test profile active in that exact focused window.
The pad starts its duration only on a matching readiness receipt, with a separate
90-second preparation limit. Closed windows/signals stop startup; owned children
have bounded termination, and a cancelled window-query child is reaped. Cleanup
stops the owned service before journal recovery, checks saved settings/profile
selection as well as all descriptors, and performs recovery before writing logs.
Disconnected/unverifiable state is reported as failure with recovery data kept.

All 186 tests pass, including both complete test profiles through the engine,
HyperShift, shortcut timing, turbo cancellation/fresh press, preserved pointer
drags, stale preview rejection, config identity, readiness, window-close/startup
failure, disk failure during evidence saving, and unsuccessful restoration.
Qt countdown checks run offscreen; controller tests use simulated hardware and
service children, with a real harmless child used to check cancellation/reaping.
Offline builds against the original private captures preserve 42 V2 / 50 V3 raw
descriptors and list 12 effective overrides each. The private
`evidence/naga_*-software-preview.local.json` files are offline previews, not
prepared live tests; fresh read-only preparation is still required.

Arch/wheel/source artifacts were rebuilt and staged package/GUI/CLI checks pass.
No physical read/write, input grab, real remapping, startup change, system package
installation or input-remapper change occurred. The user chose to defer hardware
testing; that remains in effect. Firmware actions, wired operation, settings and
reconnect persistence, per-profile sensitivity, broader service acceptance and
final migration remain unfinished.

## Shared-profile editing and V3-only visibility

The profile editor now keeps assigned V3-only controls visible when viewing the
V2, as required by the specification. Shared assignments, V3 overrides and
standalone-only choices all qualify. These rows identify the physical V3 control;
double-click or the navigation button switches the selected model without
changing any mapping. The V2 selector shows no substitute button, and the edit
path rejects attempts to assign a physically absent control to a V2 override.

Mapping cells and selector details now identify shared values, mouse-specific
overrides, inherited Normal actions and stored actions from the last active-slot
read. Unread and undecoded mouse memory remain distinct. Passthrough HyperShift
uses the saved shifted assignment, while an inherited normal HyperShift trigger
stays active on both layers; the display uses the engine's resolver for both.

Shared editing previously initialized the dialog from the effective mouse
override. It now starts from the shared value, names the editing scope, and
explains when a mouse override takes precedence. Device edits start from the
effective inherited value when an override is absent. Removing an assignment
affects only the selected scope/layer, removes empty override containers, and
does not save when there is nothing explicit to remove. Local save failures
restore the complete last-saved profile and displayed values. A shared shifted
mapping can be edited for the other mouse even when the selected mouse has an
explicit normal HyperShift override; the actual trigger remains unchanged.

All 196 tests pass. New coverage includes scope-specific dialog initialization,
persistence/reload, per-mouse and per-layer removal, failure rollback, stored
trigger precedence, unknown-versus-unread state and V3-only navigation without
cross-mouse writes. The native layout was rendered offscreen using an isolated
temporary configuration, with no service activation or HID access. Hardware,
firmware, per-profile sensitivity and migration acceptance remain deferred or
unfinished as described above.

## Buffered-input cancellation and prompt release during USB cleanup

A hardware-free reproduction demonstrated an actual cancellation bug: a side1
press queued under one window was processed after focus moved, emitting the new
window's KEY_B mapping. Cancelling the engine's existing jobs alone did not cover
unprocessed reports. Reports and queued button commands now carry the engine's
generation. Immediately before advancing it, the session captures pending hidraw
reports under the old generation, using bounded nonblocking reads. A buffer that
cannot be drained or a full software queue stops the session with a visible error.
This covers both reports in Python's queue and reports already waiting in hidraw.

The router consumes old held states and releases without starting new actions.
An old held control remains disarmed until release, so duplicate reports cannot
restart macros or HyperShift. Old wheel pulses cannot execute mapped actions;
ordinary pointer movement and releases of existing native drags are preserved.
The generation is checked after mode verification and inside the coordinator
lock. DPI/native commands are checked again after waiting for the hardware lock;
stale profile-switch commands are also discarded. Already-admitted USB operations
still finish under their lock, including on cancellation, before resources close.

Session cleanup previously awaited USB workers before cancelling engine jobs.
It now blocks further input and cancels generated keys/macros first, so a slow
USB operation cannot keep a turbo running after disconnect/Disable. The remaining
workers finish before output/transport teardown and journaled mode restoration.
Startup also checks a requested stop after asynchronous setup steps and never
claims READY after an input-boundary failure.

All 220 tests pass. New tests use real local packet sockets as bounded report
buffers and simulated output/HID adapters; no real device input or key injection
occurs. Coverage includes focus changes with and without a pin, profile changes,
emergency cancellation, monitor loss, mode-query waits, held HyperShift across
interfaces, pointer releases/movement, stale wheel actions, queued DPI/native/pin
commands, queue overflow and disconnect. A full session test keeps a simulated
USB operation in flight while triggering disconnect, verifies immediate macro
cancellation/release, then checks resource closure and normal-mode restoration.
A simulated logind stream verifies suspend cancellation and no macro restart on
resume; cancelled keyboard setup is checked before any mouse ownership.

These results do not verify physical receiver reconnects, radio delivery timing,
or real system suspend/resume. At this checkpoint, hotplug retry classification
still used error-message fragments; the next section records its replacement. Hardware tests
remain deferred by the user; neither mouse, input-remapper nor startup preferences
were changed. Full firmware/wired/settings/persistence/sensitivity/migration
acceptance remains unfinished.

## Explicit reconnect outcomes and recovery failures

An offline reproduction showed that `ENODEV` / "No such device" incorrectly
disabled automatic reconnect, while a mapping error in a profile named "Timeout"
incorrectly kept retrying. Retry decisions now use exception types and firmware
status codes, independent of display wording. Device OS errors are classified
only around HID/evdev operations; missing executables, journal failures,
permissions and competing input ownership retain their own meaning. Missing
interfaces during enumeration can retry, but ambiguous identities and unverified
transport routes cannot activate. A known return to normal mode can reconnect;
an unexpected mode requires attention.

Session cleanup preserves an explicit retry outcome. Availability failures during
mode restoration retain the mode journal for recovery before the next inspection
and input ownership. Identity, journal, output-release and other cleanup failures
veto automatic activation. Worker errors arriving while shutdown waits for an
admitted USB operation are now recorded instead of discarded. Native-setting
rollback also wraps a failed identity query as an unresolved recovery failure,
so a disconnect there cannot conceal an uncertain write behind a retryable error.
An outer recovery error stays fatal even when its cause is device unavailability.

The supervisor retains the five-second delay and requires available focus/suspend
monitoring and exactly one transport. Unexpected cancellation or an exception
escaping session cleanup stops automatic activation. Software control now shows
the retry countdown and waiting state alongside the reason. The HID exchange
continues to send each request only once and poll for its reply; retry permission
does not authorize repeating an uncertain setter. A new session starts without
the previous session's macros or held output keys.

All 263 tests pass. New coverage includes OS/status classification, device-open
and feature-ioctl failures, missing versus ambiguous interfaces, busy/stale reply
deadlines without resending, evdev ownership/permissions, raw-input EOF, supervisor
backoff and gating, known versus unexpected modes, and the native retry display.
A simulated mouse exercises disconnect with a retained active mode journal,
recovery before the next inspection, and fresh ownership without restarting
actions. Fault injection covers identity changes, journal disk failures, output
cleanup, rollback identity loss and late transaction failures. Tests use simulated
hardware and local packet sockets; physical receiver removal, wake/reconnect and
system suspend acceptance remain unverified. No hardware request, real remapping,
input-remapper change or startup preference change occurred in this continuation.

## Reversible DPI-selector experiment preparation

Per-program hardware sensitivity still depends on verifying a nonpersistent DPI
setter. Rechecked the pinned fork's packet builder: its scalar DPI setter always
emits selector1 despite accepting a storage argument. No claim of selector0
support follows from that source. The new separate `gillete.dpi_probe` provides
`prepare`, `run` and `recover` for an explicit candidate `04:05` selector0
experiment; the service, normal transport allowlist and profile schema are
unchanged. No physical preparation or write was performed in this continuation.

Preparation captures firmware, serial, normal mode, assigned/active slots,
inventory, all known controls in bank0 and every assigned slot, stored
DPI/stages/polling and selector0 DPI. It validates each response and previews a
small target distinct from both getters, preserving opaque scalar bytes. Raw
original bindings, including retired or undecoded macros, remain private and
unchanged. The execution directory is claimed once, and the complete recovery
journal is flushed before a setter. Fresh inspection rejects stale settings,
bindings, identity or profile selection before mutation.

Execution checks selector0 and saved-settings readback immediately, holds the
value for 0–10 seconds, then compares the complete captured state. It sends the
candidate once; rejection, ignored writes, timeout and cancellation all enter
cleanup. Restoration repairs changed saved values in dependency order, including
the independent scalar after a stage-table write, then restores selector0.
If that restoration changes saved readback, one additional saved repair is
allowed only after the earlier repair was verified. There is no blind SET retry
or unbounded write loop. Final verification compares both DPI getters, saved
settings, identity/profile/inventory and all captured binding functions. Reply
metadata is retained in evidence but is not mistaken for a changed assignment.

Identity, firmware, mode or profile changes prevent recovery writes. An uncertain
restoration ACK retains the journal; explicit recovery first reads current state
and skips values already restored. Partial restoration is never reported as
success. Signals request cancellation between operations; recovery bypasses the
experiment's query/time budget. A saved read-only preparation is not accepted as
an attempted-write recovery journal. Journal and report files are mode0600 in
new private directories; terminal output omits hardware identity and bindings.

All 306 tests pass, including 43 new tests using independent/aliased simulated
storage, multiple V3 slots, opaque descriptors, stale previews, device/firmware
identity changes, ignored/rejected writes, lost SET/restore ACKs, disconnect/wake,
coupled stage/scalar restoration, unresolvable getter aliasing, cancellation,
budget exhaustion, journal disk failure and one-shot CLI execution. No real HID,
evdev, uinput or compositor operation was performed by those tests.

Even a successful physical roundtrip would establish only observed getter
independence and restoration. Coupled selector0/1 readback does not itself prove
a nonvolatile write; separate readback does not prove sensor changes or absence
of hidden permanent writes. Sensor behavior, power-cycle and receiver-replug
independence and driver-mode operation remain required. `temporary_dpi_supported`
stays false in every report. Per-profile sensitivity, native firmware actions,
wired transport and the remaining physical acceptance/migration work remain
unfinished, with hardware testing still deferred by the user.

## Wired descriptor and read-only route validation path

Rechecked the actual public descriptor dump and wired firmware response already
pinned by the protocol research. Report sizes agree for pointer and boot keyboard,
but wired interface01 omits receiver notification IDs8/9, mouse report10 and
keyboard LED output. The wired firmware reply is a four-byte payload; the
receiver's existing two-byte query would reject that response. These facts
support separate wired inspection, not physical button correlations. No wired
decoder relaxation, transport enablement or production capability was inferred.

`gillete.wired_probe` defaults to descriptor-only sysfs inspection. It identifies
the exact E7 USB ancestor and all four `bInterfaceNumber` values, retaining raw
descriptor bytes, hashes, report-size summaries, HID/USB driver associations,
resolved HID instances and USB enumeration numbers. Listing order cannot swap
the keyboard roles. The receiver may remain attached but is recorded separately
and never selected by a shared serial. Incomplete, oversized, ambiguous or moved
interfaces abort inspection.

The bounded size parser handles short HID items, cumulative report fields,
global Push/Pop, collections and numbered-report prefixes following
[USB HID 1.11](https://www.usb.org/sites/default/files/hid1_11.pdf), sections6.2.2
and8. It reports lengths, not usage semantics or button meanings. Unknown/long
constructs and inconsistent descriptors require review. An unnumbered 90-byte
feature body remains distinct from the leading-zero 91-byte hidraw envelope.
The public [issue2885 descriptor dump](https://github.com/openrazer/openrazer/issues/2885)
and the first firmware reply from pinned
[OpenSnek wired reads](https://github.com/gh123man/OpenSnek/blob/b4e0f666d21b52efc0a64a0e128a1278aa1b3ad2/captures/usb/2026-10-18-naga-v3-pro-wired/reads.txt)
are checked-in functional byte fixtures without hardware identity or user input.

Explicit `--query-routes` first requires the known report-size layout, then
submits only allowlisted getter shapes: firmware04bytes, mode02bytes and
polling01byte on candidate interface00. Interface03 is attempted once only if
that bootstrap fails. A normal-mode, inventory or state-verification failure on
an answering route is reported without a further sweep. Strict framing rejects
status0 request echoes and the incorrect two-byte firmware payload. Transactions
remain1f; no setters, transaction sweeps, input reads/grabs or service changes
are allowed by this diagnostic.

On a working route, normal mode, serial, assigned/active slots, inventory,
bank0/active-slot binding functions, firmware and saved settings are captured
before/after. The route is reported verified only when those reads match.
Bounded work allows256 queries/120seconds per route between operations; kernel
I/O may exceed the deadline. Descriptor/driver/enumeration identity is checked
before opening, after opening and after querying. A changed/reused HID node
invalidates the result and prevents trying another route. Reports are new-only,
mode0600, under newly created mode0700 parents; summaries omit device identity
and binding contents. No actual descriptor collection or HID request was made
against the user's hardware during this continuation.

All 353 tests pass, including 47 wired/descriptor cases. Tests cover both public descriptor sets, exact firmware framing,
malformed descriptors, global-stack/padding arithmetic, sysfs interface order
and identity races, receiver/cable separation, route fallback, request echoes,
normal-mode gating, inventory rejection, state drift, unplugged verification,
strict getter shapes and private one-shot reports. Production E7 configuration,
mode switching, remapping and writes remain gated. Physical wired reads,
driver-mode button capture and persistence tests remain required; this is not
evidence that the user's wired transport works yet.

Arch, wheel and source artifacts were rebuilt. Staged package checks cover the
native GUI/CLI plus the new diagnostic entrypoint. The source archive now ships
the public JSON fixture; all 47 wired tests also pass from the extracted source
using its own imports. No host package installation or service activation occurred.

## Native device diagnostics and service transport identity

The former device-list text view only checked whether each node was readable.
It could call a configuration interface accessible even though Gillete opens it
read/write for feature queries. The native Devices & diagnostics panel now
separates configuration-route access, raw/evdev enumeration and read access,
uinput write access, duplicate transports, desktop monitoring and service state.
Per-node read/write checks and the nearest bound HID driver are also displayed.
No HID/input node is opened to collect this information, and no ownership probe,
service startup, mode switch or settings request is performed.

Service status now includes its session's product/USB path/transport, excluding
hardware serial and window contents. Diagnostics matches that route instead of
assuming a model-level active flag owns every connected transport. An older
daemon without this field is labeled as active for the model with unknown exact
transport. Current ownership, retry state and reported errors are kept distinct
from permissions: readable nodes can still be grabbed by another remapper.
Connection and permission data changes only on refresh; service updates reuse
the existing poll. Disconnect or failed refresh clears stale device results,
and selection persists through discovery-order changes.

The Feature validation page records the actual limits of development evidence:
receiver control captures, partial side12/HyperShift power-cycle tests, V3 live
examples versus the pending V2 software test, implemented recorder/launch and
settings work, and unverified native firmware actions, extra V3 slots, temporary
DPI and wired operation. It explicitly describes historical development tests,
not validation of the currently connected unit. The data does not enable any
backend capability or change configuration/write guards.

All 368 tests pass. New checks cover read-only configuration permissions,
missing/duplicate raw or evdev nodes, unknown access, active receiver versus
attached cable, older daemon compatibility, retry/errors, nearest sysfs driver,
refresh/disconnect behavior and selection retention. Native Qt rendering was
inspected offscreen with simulated discovery and service state. Hidden-tab row
heights now recompute at the actual viewport width so the validation text is
readable without excessive blank space. Hardware acceptance, settings and
receiver reconnect/persistence tests remain deferred; no real input ownership,
remapping, hardware query or startup preference was changed.

## Portable profile bundles and optional program rules

Offline editor checks reproduced two profile-management defects: duplicating a
profile left self-switch buttons pointing at the original, and single-profile
exports omitted program rules and profiles referenced by button actions. Copies
now rebase self-references across shared and per-mouse Normal/HyperShift layers,
retain other local profile links and standalone choices, and copy their saved
program rules in a disabled state. Long or repeated names receive bounded,
distinct names. The source configuration remains unchanged until the new copy
is saved successfully.

Version2 exports contain the selected profile, the transitive set of linked
profiles (including cycles), and saved program rules for that set. They exclude
default selections, pins, startup preferences and hardware recovery data.
Exports use private atomic replacement, preserving an older backup if writing
or replacement fails. Import validates the complete graph before review,
allocates collision-free identities across local and incoming profiles, and
rewires all imported self/cross references together. A missing dependency in a
new bundle cannot silently bind to an unrelated local profile with the same ID.

Native import review lists profile names, linked copies and source rule states.
Rules are retained disabled by default; explicit activation preserves each
source rule's enabled/disabled state. Existing equal-priority rules retain
precedence. The Program profiles table now supports enabling/disabling a rule
without deleting it, with changes applied by Save rules. Older configurations
default existing rules to enabled. Legacy version1 exports still import; any
external link must exist locally and is shown in review, otherwise import asks
for a new bundle containing its dependencies.

The editor preserves unsaved rule rows during successful copy/import and
rolls back the proposed local configuration on save failure. Cancelling review
writes nothing, and a concurrent edit detected by the store's revision guard
is not overwritten. Imported profiles do not replace defaults, pins or startup
choices. Existing service preflight still applies to new profiles; this work
does not loosen unknown stored-action or HyperShift reachability checks.

All 403 tests pass. New checks cover cyclic exports, self/cross links in both
layers and model overrides, macro/standalone preservation, ID and name collisions,
optional rule activation, legacy links, strict schema/size/count limits, private
atomic exports, disabled-rule persistence, native review/cancellation, unsaved
editor rows and failed or conflicting saves. The import-review layout was also
rendered and inspected offscreen with synthetic profiles. No live hardware,
input, service or startup state was changed; physical tests remain deferred.

## Validate profiles reachable by each mouse, allowing inactive drafts

An offline reproduction showed that saving an unused profile with unfinished
HyperShift assignments rejected the running service configuration, even when
that profile's only program rule was disabled. Preflight previously checked the
entire library against each connected mouse. This also forced V3-only program
profiles to be fully usable on an unrelated V2 session.

Software preflight now computes the selectable profiles independently for each
mouse. In Automatic mode its roots are the model's default and every enabled
rule that can match that model, including future windows. In pinned mode the
root is the manual selection. Both modes follow all effective profile-switch
buttons transitively, through shared and per-model Normal/HyperShift layers.
The traversal uses the same resolution as playback, so model-absent controls,
overridden actions and shifted assignments masked by explicit or inherited
HyperShift triggers cannot introduce false destinations. Cycles are bounded by
the profile set rather than recursion.

All reachable profiles still require resolved stored actions and usable
HyperShift configuration before taking input ownership, accepting a reload or
changing a live pin. Choosing Automatic revalidates its roots before changing
the saved pin. Invalid reachable reloads retain the prior engine configuration
and request session shutdown through the existing error path. An unrelated,
structurally valid draft can remain incomplete without interrupting software
control. Disabled rules do not exclude a profile that is reached by a button.
Whole-library schema and reference validation remain in force.

All 421 tests pass. The 18 added cases cover per-model rules and overrides,
both layers, inherited-trigger masking, a 1000-profile cycle, unknown stored
actions in linked profiles, inactive import during a running turbo, disabling
and re-enabling an active rule, invalid manual pins, Automatic revalidation,
actual queued profile-button selection and release-before-reuse, and both
receivers' preflight before simulated output setup. Real engines, profile
storage and daemon reload/command paths are exercised with synthetic device
state and recorded outputs. No mouse node, uinput device, compositor setting
or user configuration was touched. Physical acceptance remains deferred.

## Native read-only binding persistence verification

Receiver unplug/replug remains an explicit acceptance gap. The existing
one-button test kept device handles open and only supported a reported mouse
power cycle. Added a separate native workflow tied to a completed binding-save
journal, so future saved configurations can be checked through both restart
steps without another setter or an open handle spanning the unplug.

The baseline checks the journal's product, hardware serial, successful-save
status, changed entries and current values. Backups, restored transactions,
settings journals, malformed/duplicate locations and unchanged-only saves are
not accepted as proof of a new binding save. Every known control on both layers
is read in every assigned slot and bank0. The active mirror must agree with the
selected stored slot. Hardware serial, firmware, assigned/active slots, inventory
and USB/HID route are checked around the read. A getter-only transport has no
binding setter, allows at most400 requests and a120-second budget between
operations; an in-flight kernel call can outlast that deadline.

After READY, the user reports a mouse power cycle with the receiver left
connected. A second read must match the baseline, including opaque response
metadata. The dialog then observes disappearance of the selected receiver,
waits for its configuration interface to reappear at the same USB port, and
checks a third read with a changed USB bus/device enumeration. Rediscovery
allows new hidraw numbers; serial/firmware checks prevent accepting another
mouse. The two receiver PIDs are supported by this diagnostic; the unverified
wired route remains unavailable.

The original recovery journal is hashed and checked before/after each phase,
never edited. A separate new private directory holds a mode0600 receipt with
baseline/readback evidence, phase outcomes, reported power cycling and observed
receiver disconnection. Physical output is explicitly unverified. This is
binding readback evidence, not a claim about macro timing, settings persistence,
all possible assignments or completed model support. Cancelling or timing out
waits for the current read before closing and records an incomplete outcome;
completed read evidence may remain in that receipt. An explicit retry is offered
for transient read failures after preparation. No setter is retried or issued.

All 454 tests pass, including 27 backend and6 native-dialog cases. Checks cover
both receiver models, an untouched V3 slot changing, wrong identity/firmware,
active-mirror and metadata changes, source-journal mutation during reads,
same-port/new-enumeration requirements, incomplete interface discovery, query
budgets and getter-only enforcement, private receipts and cancellation during
the final read. Dialog tests use real Qt worker threads with simulated reads,
exercise retry and close/timeout behavior, and verify that the main window
cannot quit while this modal operation is active. Native READY layout was
rendered offscreen. No physical HID/input access or user settings changed;
actual receiver-replug acceptance is still deferred.

## Device-action prerequisites before software ownership

Offline reproduction found that a V2 native-wheel assignment and a V3
multiple-slot cycle assignment passed service preflight, then raised an error
on their first button press. Known-action decoding alone did not establish
that the corresponding adapter could execute with this model and snapshot.

A shared device-action support check now drives the editor and session
preflight. Native wheel-mode/onboard-slot actions require V3; one assigned
onboard slot is explicitly a no-op, while multiple-slot cycling remains
unimplemented and rejects software activation. The message suggests a local
profile switch or another explicit software mapping. DPI-stage actions require
valid scalar and stage-table reads while preserving legitimate differences
between those two values. Native wheel-mode cycling requires its recognized
two-byte readback. Hardware inspection now adds this optional getter only for
V3; failures remain metadata errors and do not block unrelated actions.

Preflight checks each effective Normal/HyperShift action in the already
computed selectable profile set. Model-specific overrides, inherited triggers
and inactive drafts retain their behavior. Startup rejects an unusable device
action before output/input ownership, and live pins/reloads use the same
checks. Runtime still reads the actual current values again before a setter;
it does not trust the editor's old snapshot. The native adapter also rejects
both V3-only action types on V2 consistently instead of silently treating V2
onboard cycling as a no-op.

Mapping cells, visual control details and the action editor distinguish missing
reads, known unavailability, and implemented prerequisites. Local drafts remain
saveable; software-adapter limits do not alter standalone firmware encoding.
Recognized readback is explicitly not physical setter acceptance. No new
hardware capability, onboard slot selection or per-program DPI was enabled.

All 480 tests pass, including 24 added backend cases and two native-editor
cases. Coverage includes rejected getters, malformed DPI/wheel values,
per-model limits, single/multiple slots, both layers, inherited-trigger masking,
startup before ownership, inactive drafts versus pins/rules, runtime rechecking
and preservation of local drafts. The existing slow-USB cleanup tests now
provide valid simulated DPI readback and still verify immediate generated-key
release while the admitted operation finishes. No live mouse query, setter,
input ownership or user configuration change was performed.

## Official Synapse middleware investigation

Downloaded the official Windows bootstrapper and App Engine package without
running them, then followed the production application host to model-specific
V2 and V3 middleware. The first-party manifests identify both target mice.
Preserved their exact source bytes, acquisition hashes, twelve extracted
Webpack factory ranges and earlier REA artifact evidence in ignored
`evidence/synapse-official.local/`. Factory ranges were verified using JavaScript
UTF-16 slicing; Python character offsets are not interchangeable.

Both middleware builds contain a selector-0 scalar DPI read/write/readback
task, plus a selector-1 saved-stage path. This strengthens the prepared
reversible experiment but does not verify sensor behavior or volatility.
The shared protocol factories also define one-byte profile create, delete and
active-selection commands. The V2 model explicitly disables onboard macro
storage while allowing macro mappings. V3's effective macro configuration
still needs tracing. See `synapse-middleware-research.md` for exact identities,
command definitions, limitations and next validation steps. No hardware
capability was enabled, and no device was accessed.

The macro/turbo follow-up directly establishes first-party turbo interval
encoding (`floor(1000 / rate)`) and rate decoding (`round(1000 / interval)`)
for both target builds. Existing `008e` parameters therefore represent
Synapse's 7 presses/s setting; actual firmware timing remains unmeasured.
Also confirmed the numeric macro playback families, big-endian references,
and the engine subclass's assignment of the incoming macro capability flag.
Preserved the additional subclass chunks and focused REA evidence. See
`synapse-macro-turbo-research.md`. Native event serialization, full upload
dependencies and physical V3 macro-storage acceptance remain outstanding.

## Macro event format and upload dependency follow-up

Recovered unfinished `macro_inspection.py` and its catalog integration after
the T3 restarts. First-party module `41022` supplies opcode numbers; factory
`51294` supplies the record shapes and upload sequence. The read-only decoder
now reports key usages, complete five-button masks, wheel notches, all four
delay widths and raw cursor coordinates. It retains every parsed record's raw
bytes and stops at unknown/incomplete/unsupported data with the entire
remainder preserved. It reports held inputs without Synapse's invented final
releases, and flags the four-byte delay's signed-JavaScript ambiguity. It
never emits executable actions, changes a binding or claims playback support.

The candidate catalog accepts only enumerated nonzero IDs, now through 32767
as established by Synapse's first-party random-ID generator. Count/request/
byte bounds remain in place. Its optional raw-data capture adds the inert
interpretation without additional device queries. Ordinary transport's
class-06 restrictions remain unchanged.

The source upload trace identifies allocation, 250-byte metadata and event
data as separate dependencies. Its storage-reclamation fallback can format
and reconstruct profiles/macros. Gillete does not implement or invoke that
fallback. Native uploads remain unimplemented; a verified read-only catalog
and recovery design must precede a fresh-ID experiment. Details are in
`synapse-macro-turbo-research.md`.

All 502 tests pass, including source-derived combo/delay/mouse/wheel/cursor
examples, partial-stream preservation, no synthetic releases, high macro IDs,
limits and unchanged diagnostic request counts. Package checks pass with the
new decoder included and its read-only tests exercised from the extracted
source archive. No host install, HID query/write, service activation, input
capture or user-config change occurred. Next physical step: V3 receiver awake,
read-only macro catalog and DPI-selector check; preview any temporary write
only after those reads succeed. V2's old MapleStory macros remain retired.

## V3 receiver read-only firmware check — 2026-11-05

After the user reported the V3 awake, the opt-in receiver diagnostic completed
224 getter requests. Macro storage/count queries succeeded: zero catalog
entries, 307200 bytes reported maximum and free, zero reclaimable bytes.
No macro data or names were read because the catalog was empty. This verifies
these two getters on this V3 receiver, not allocation, upload or playback.
Both DPI selectors returned 6400 × 6400 with their requested selector echoed.
Normal mode, device identity, inventory, active/assigned slots, binding records
and saved settings matched before and after. One slot (1) is assigned/active.
Private complete report: `evidence/v3-firmware-read-20261105-01.local.json`.

A subsequent read-only DPI experiment preparation succeeded. It proposes
selector-zero 6400 × 6400 → 6500 × 6500, followed by restoration, with saved
scalar DPI 6400, stages 400/800/1600/3200/6400 (fifth selected) and polling
1000 Hz. Exact originals and candidate bytes are in ignored
`evidence/v3-dpi-selector-20261105-01.local/prepared.json`. No setter has run.
The temporary write still awaits explicit approval. Its recovery can restore
saved DPI/stages/polling if the candidate unexpectedly affects those values.
Matching readback alone will not establish sensor behavior or volatility.

## V3 selector-zero reversible write — 2026-11-05

The user approved the prepared three-second 6400 → 6500 DPI experiment.
It completed with `readback-roundtrip-restored`,
`selector_readback_independent=true`, and `original_state_restored=true`.
Immediate selector-zero readback was 6500 × 6500; saved scalar DPI remained
6400, stage data and polling matched the originals, and the later full
protected-state comparison passed. Restoration read selector zero as
6400 × 6400 and verified the original settings and bindings. No experiment
or recovery error was recorded. Private complete journal:
`evidence/v3-dpi-selector-20261105-01.local/run/journal.json`.

This establishes the bounded selector-zero setter/readback round trip on
the user's V3 receiver in normal mode. It does not establish actual sensor
sensitivity, flash-write behavior, sleep/power-cycle/replug persistence or
driver-mode compatibility. `temporary_dpi_supported` remains false; automatic
per-program DPI is still disabled. A subsequent experiment needs a measurable
sensor change and explicit persistence/driver-mode acceptance, with its own
reviewed changes and restoration plan.

## User-paced V3 sensitivity/power-cycle experiment

Added `dpi_sensor_probe` using the existing complete snapshots, identity/mode/
profile guards and restoration path. The selector-zero candidate is written
once, checked independently of saved settings, and held for at most three
minutes while the user observes movement and power-cycles the mouse. No USB
queries occur during that waiting phase. The explicit user report is retained
separately from post-cycle readback. Timeout, cancellation, invalid reports and
errors attempt restoration; interruptions retain recoverable journals, including
the waiting phase. No input grab, recording, profile setter or binding setter
is used. Automatic temporary-DPI support remains disabled.

The user authorized the next sensitivity/power-cycle validation, woke the V3,
and the prepared 6400 → 3200 test reached READY. The user reported both
speeds too fast to distinguish, and specified a usual DPI of **1200**. The run
was cancelled and original settings/bindings restored successfully, with no
power-cycle or sensitivity success claimed. Journal:
`evidence/v3-dpi-sensor-20261105-01.local/run/journal.json`.

Added an explicit lower-DPI preparation option so the revised test can use
1200 without changing the user's saved profile. It is validated against the
original values, included in the recovery document and cannot be overridden
at run time. A fresh read-only 6400 → 1200 preparation is in
`evidence/v3-dpi-sensor-1200-20261105-01.local/prepared.json`.
The original 6400 is still the restoration target; 1200 is the user's recorded
preference, not authorization to overwrite saved stages permanently.

All 520 tests pass, including user-report versus actual readback, retained
candidate/reset outcomes, timeouts, cancellation, malformed reports, saved
settings drift, aliased storage, lost ACK, interrupted waiting recovery,
exact requested values and invalid/unchanged/increasing targets. Source and
wheel package validation also cover the new module and DPI tests.

## V3 1200-DPI sensor/power-cycle observation — 2026-11-05

The revised user-paced run reached 1200 × 1200 with saved scalar DPI still
6400, unchanged stage bytes and polling. The user reported that 1200 felt like
their usual speed and felt the same after switching the mouse off and on.
Post-report readback confirmed selector zero still at 1200 × 1200, with the
protected state unchanged. The receiver was not unplugged; power cycling is
user-reported, not an independently observed USB removal.

The run finished `sensor-observation-restored`: restoration of selector zero
to 6400 × 6400 and all original settings/bindings verified, without experiment
or recovery errors. Private complete journal:
`evidence/v3-dpi-sensor-1200-20261105-01.local/run/journal.json`.

This supplies human sensor-effect evidence and shows the candidate surviving
the reported mouse power cycle. It does not prove flash/NVM behavior or
receiver-side versus mouse-side retention. Do not classify selector zero as
volatile from its name or independent getter. Automatic per-program DPI stays
disabled pending receiver-replug/true power-loss investigation and driver-mode
validation. User preference remains 1200; test cleanup restored the exact
pre-test 6400 rather than permanently modifying saved stages.

## Receiver-replug DPI experiment preparation

Added `dpi_replug_probe` for the next user-authorized V3 retention check.
Read-only preparation captures the exact receiver port/enumeration identity
and all original mouse settings/bindings. The run journals before its one
candidate setter, verifies immediate independent readback, closes the old
transport, and announces READY. Sysfs polling then requires actual receiver
absence and a changed bus/device address after same-port reconnect. Incomplete
interfaces do not count as removal. A fresh transport checks the original
mouse identity and protected state before recording the candidate/original/
other DPI outcome, then restoration uses another fresh transport. The candidate
setter is never replayed on reconnect.

Timeout/cancellation/errors attempt restoration; an absent receiver or failed
cleanup retains a journal without claiming restoration. The existing recovery
command accepts both the waiting and completed replug statuses. The experiment
never changes driver mode, grabs input, or enables automatic DPI support.

All 529 tests and package checks pass. Added cases cover candidate retention
versus reset, descriptor closure/reopening, incomplete enumeration, unchanged
USB address, wrong port, radio read failure, aliased storage, cancellation,
timeout, unplugged cleanup and later explicit recovery. A read-only preparation
for 6400 → 1200 is saved in
`evidence/v3-dpi-replug-1200-20261105-01.local/prepared.json`. Live replug outcome
is still pending; only announce READY after the run verifies its candidate.

## V3 receiver test timeout — recovery pending

The 1200-DPI receiver-replug run timed out without observing receiver USB
removal. Cleanup could not verify restoration because the mouse returned
`Device timeout`; journal status is `recovery-required`. Sysfs still shows the
V3 receiver and configuration interfaces. A subsequent explicit recovery
attempt also returned `Device timeout`. No receiver-retention outcome is
established, and the candidate 1200 setting may remain active.

Retained journal:
`evidence/v3-dpi-replug-1200-20261105-01.local/run/journal.json`.
Next action is to wake the V3 with its receiver connected, then retry the
already-authorized journal recovery and verify originals. Do not start another
hardware experiment or claim restoration until recovery succeeds.

## V3 pending recovery completed — 2026-11-10

After the user woke the V3, explicit recovery of the retained receiver-test
journal completed as `original-state-restored`. `original_state_restored=true`
and the full normalized captured state matches the original snapshot,
including selector-zero 6400 × 6400, saved settings and binding functions.
No recovery error remains. The old `Receiver-replug observation timed out`
message is the retained experiment error; it does not indicate a new recovery
failure. No hardware experiment is currently running, and no successful
receiver-retention outcome is inferred from this recovery.

## V3 replug detected; reconnect read timed out — 2026-11-10

The fresh receiver test observed actual USB removal and a changed enumeration
address on the original port. The first post-reconnect capture returned
`Device timeout`, and immediate cleanup also timed out. The user then confirmed
replugging. Explicit journal recovery succeeded: `original-state-restored`,
6400 × 6400, matching saved settings and complete normalized original state,
with no remaining recovery error. The experiment's old timeout is retained as
historical evidence. No post-replug DPI value was obtained, so this run does
not establish whether 1200 survived receiver removal.

Private journal:
`evidence/v3-dpi-replug-1200-20261110-01.local/run/journal.json`.

The failing regression reproduced USB enumeration followed by transient
readiness failures, yielding `recovery-required` despite later responsiveness.
Replace the fixed one-second assumption with fresh-transport read-only
readiness checks before both the retention snapshot and restoration. These
retry only typed device-unavailable, busy/timeout status (1/4), and missing
USB-device errors. Each attempt revalidates the original mouse identity and
captures state. Attempts share a per-phase 2048-read budget, max 16 attempts
and a 45-second retry deadline checked between attempts. Malformed
responses, identity/state mismatches, command rejection and permission errors
are not retry reasons. The caller's setter is outside the retry handler;
uncertain writes never cause the candidate or restoration SET to be resent.

Added regression coverage for actual getter busy/timeout, temporary transport
unavailability, structural rejection, permanent unavailability, and an
uncertain setter escaping the read-only retry loop. Full suite: 538 passed;
package source checks: 217 passed. An initial parallel check run hit the existing
GUI-instance acknowledgement timing failure; that test passed independently
and subsequent full suites passed. No GUI behavior was changed in this fix.
Physical acceptance of the new readiness loop still needs the next live trial.
No hardware experiment is currently running; original V3 state is verified.

## V3 replug node-access race — 2026-11-10

The next physical run again detected actual receiver removal and changed
USB enumeration, but opening the new configuration node failed with EACCES.
The bounded cleanup readiness loop then handled one device-timeout response
and completed restoration successfully. Verified `test-failed-restored`,
`original_state_restored=true`, selector-zero 6400 × 6400 and full normalized
original-state equality. There is no post-replug DPI readout, so retention
remains unresolved. No hardware experiment is running.

Private complete journal:
`evidence/v3-dpi-replug-1200-20261110-02.local/run/journal.json`.

The new node was readable/writable when inspected after cleanup. This is
consistent with udev/seat permissions becoming ready after interface discovery;
the exact permission-manager event was not captured. A red/green regression
showed that route discovery returned a completed replug even while current
node access was unavailable. `observe_route` now requires read/write access
to the exact configuration node returned by the validated route before
reporting readiness. It polls within the existing bounded wait and does not
change ACLs/rules or treat missing access as receiver removal. EACCES thrown
by an actual open is still a hard failure, not a broad retry permission.

All 540 tests and 219 packaged-source checks pass. Physical acceptance of
both readiness gates together awaits a fresh user-paced replug trial.

## V3 receiver-replug retention accepted — 2026-11-10

The next user-paced run completed as `receiver-replug-restored`. It observed
receiver USB removal and changed bus/device enumeration after reconnect to
the original port. Two post-replug getter attempts returned status 4; the
bounded readiness loop opened fresh transports and then captured the original
mouse successfully without resending the candidate setter.

Selector-zero DPI was 1200 × 1200 immediately after the candidate write and
remained 1200 × 1200 after the observed receiver replug. Saved scalar DPI,
stages and polling were unchanged throughout. Cleanup verified selector zero
back at 6400 × 6400 and full normalized original-state equality (including
all original binding functions), with no experiment or recovery error.
Private complete journal:
`evidence/v3-dpi-replug-1200-20261110-03.local/run/journal.json`.
The user separately confirmed replugging. No experiment is currently running.

This physically accepts the access/readiness fixes and establishes retention
of the candidate across receiver removal on this V3. Together with the earlier
human sensitivity/power-cycle observation, it shows that receiver replug does
not reset this setting. It still does not prove flash/NVM use versus mouse-side
powered memory, or full battery power-loss behavior. Do not infer safe
high-frequency automatic writes or enable temporary-DPI support from this.
Driver-mode behavior and safe per-program integration remain unverified.

## Driver-mode DPI experiment preparation

Added `dpi_driver_probe` for the user's authorized next V3 test. It reuses
complete original snapshots and validated explicit lower-DPI targets. The
normal-mode preflight journals DPI recovery before taking a separate ModeLease;
only then does it enter driver mode, validate identity/firmware/profile state,
apply selector-zero 1200, and verify independent saved-settings readback.
The user-paced phase asks for movement only, with a three-minute deadline.
It never starts remapping, records input or grabs devices; users should use
the other mouse for clicks while this driver-mode-only test owns the V3.

Cleanup restores normal mode through the mode journal before calling existing
normal-mode DPI/settings restoration and complete original-state verification.
Uncertain mode writes, DPI ACK loss, saved-settings drift, cancellation,
timeout and malformed observations retain recovery evidence. A changed mouse
identity blocks cleanup writes until the original mouse returns. Recovery must
use this module's `recover --directory` command to restore mode before settings.
No automatic DPI capability is enabled by success or by a user observation.

The read-only preparation initially timed out, without a mode or DPI write.
After the user woke the V3, fresh preparation succeeded for temporary driver
mode and 1200 DPI, with planned restoration of the original normal mode,
6400 DPI, saved settings and bindings afterward. Preparation file:
`evidence/v3-dpi-driver-1200-20261110-01.local/prepared.json`.
Live acceptance remains pending until READY, the user's observation and
verified restoration are recorded separately.

Driver-test validation: all 553 tests and 232 packaged-source checks pass,
including mode/DPI ACK loss, identity changes, mode-before-settings recovery,
user feedback, deadlines and protected-setting drift.

## V3 driver-mode DPI accepted — 2026-11-10

The user authorized the temporary driver-mode DPI test and reported the V3
awake. Fresh read-only preparation succeeded, then the run entered driver
mode and changed selector zero from 6400 × 6400 to 1200 × 1200. Both immediate
and final driver-mode readback were 1200; saved scalar DPI, stages and polling
matched originals. The user reported that movement felt normal at their usual
1200 DPI. No input grabbing, software remapping or generated keys were used.

The run completed `driver-dpi-restored`. Its separate mode journal verified
`normal-mode-restored`; the DPI journal verified `normal_mode_restored=true`,
`original_state_restored=true`, selector-zero 6400 and full normalized original
state equality. No experiment or recovery error was recorded. Private complete
journals are in `evidence/v3-dpi-driver-1200-20261110-01.local/run/`.
No hardware experiment is currently running.

This physically establishes the selector-zero DPI write/readback and human
sensor effect in the V3 receiver's driver mode, with independent saved
settings and successful mode-first restoration. It does not validate the V2,
wired V3, NVM implementation, automatic focus-switch lifecycle, or concurrent
software-remapping/DPI integration. Production capability flags remain
unchanged pending integration work and its acceptance checks.

## Native macro implementation — 2026-11-10

Implemented the pure `native_macro` compiler and bounded `macro_memory`
packet/getter helpers from the preserved first-party Synapse bundles. The
allocation command carries actual event length; the separate admission
estimate includes 256-byte metadata overhead and rounds to 256-byte blocks.
Metadata UUIDs use mixed-endian Windows bytes, event counts little-endian.
Repeated macros expose their trailing-delay difference from software playback.

The isolated `native_macro_probe` now prepares, uploads, verifies, temporarily
binds and cleans up an exact F24-down/80-ms/F24-up experiment. It requires an
empty catalog, already-free space and V3 receiver normal mode. Snapshots cover
all reported controls in all six banks, including unknown controls. Normal
side 12 is changed only after full independent metadata/event readback and
protected-state verification. The observer reads F24 without grabbing input or
injecting keys, requires a post-READY press/release and records actual duration.

Cleanup restores original normal/HyperShift functions and reply flags before
deleting the fully verified unreferenced test object. Lost ACKs never cause
blind upload retries. Incomplete/unverifiable allocations are retained with
recovery evidence. External binding/settings/catalog changes block deletion.
Identity changes block cleanup writes until the original mouse returns.
See `native-macro-validation.md` for exact bounds and recovery commands.

Offline validation: all 589 tests pass, including interruption/ACK loss,
partial uploads, wrong metadata echoes, unknown-control references, external
changes, journal failure, cancellation, observer timing/event loss and
restoration of original reply flags. All 268 packaged-source checks pass;
Arch/wheel installation into isolated staging and native GUI smoke checks pass.
The host installation, input-remapper and service configuration are unchanged.

Read-only preparation subsequently succeeded on the awake V3, capturing all
33 reported controls in all six banks (396 records), assigned/active bank 1,
and an empty macro catalog with 307200 bytes free. The exact six-byte F24
experiment is privately prepared in
`evidence/v3-native-macro-20261110-01.local/prepared.json`. No macro allocation,
upload, binding or deletion has been submitted. Native playback/persistence
and production integration remain unverified. The next physical stage needs
explicit approval for this newly prepared macro-storage experiment.

## V3 native macro execution accepted — 2026-11-10

The user approved the exact F24-down/80-ms/F24-up macro upload, temporary
normal side-12 binding and cleanup. The first launch stopped before hardware
changes because installed evdev has no `set_clockid` method. The observer now
uses Linux EVIOCSCLOCKID on its own descriptor, verified both by a regression
test and by opening the real V3 keyboard interface. A subsequent read-only
preflight found DPI had changed from 6400/stage 5 to 3200/stage 4 since the
preparation. It stopped without a macro SET. Fresh preparation preserved the
current 3200 setting rather than restoring the stale snapshot.

The refreshed run uploaded a fresh native macro, independently verified all
metadata/event bytes, bound normal side 12 and announced READY. The user
confirmed pressing/releasing it. The observer recorded F24 down/up with an
83.001-ms hold, without input grabbing or key injection. This physically
accepts the bounded allocation, metadata/data upload, counted-once binding
and basic delay/execution path on this V3 receiver.

Cleanup completed `native-macro-restored`, `native_playback_verified=true`,
`original_state_restored=true`, with no experiment or recovery error. All
original bindings and protected settings matched, including current 3200 DPI.
The catalog is empty again: maximum 307200 bytes, 306688 immediately free and
512 reclaimable. No formatting/compaction was attempted. Private full journal:
`evidence/v3-native-macro-20261110-02.local/run/journal.json`.

All 590 tests and 269 packaged-source checks pass after the observer fix.
Native macro power-cycle retention, HyperShift/repetition and production
multi-profile dependency handling remain unverified. No test is running.

## Native macro retention test prepared — 2026-11-10

Added a separate `--power-cycle` preparation purpose using the same exact
F24-down/80-ms/F24-up stream and temporary normal side-12 binding. The run
requires actual post-READY F24 down/up plus an explicit human off/on report
within the same 180-second deadline. It independently rechecks the catalog,
all metadata/event bytes and stored/active binding before claiming observed
retention. It never claims instrumented battery removal or flash/NVM proof.
Cleanup and recovery retain the original experiment's ownership/dependency
checks. Ordinary execution now also verifies the object/binding after playback.

All 596 tests and 275 packaged-source checks pass, including missing/ambiguous
cycle reports, shared deadlines and a missing macro after a reported cycle.
The staged Arch/wheel and native GUI checks pass. Read-only preparation
succeeded in `evidence/v3-native-macro-power-20261110-01.local/prepared.json`,
with the current 3200 DPI, empty catalog, 306688 free and 512 reclaimable bytes.
No follow-up upload or binding change has been submitted. The next step needs
the user to power-cycle and tap the mouse after READY; no test is running.

## Power-cycle run active and recovery hardening — 2026-11-10

The user selected Ready for the prepared retention test. Before launching,
an offline disk-full test exposed that creating binding-recovery data for
the first time during cleanup could prevent restoring a live candidate.
The complete canonical binding-recovery journal is now durable before the
first allocation. Cleanup verifies/reuses it; Programmer's best-effort status
writes cannot prevent restoration if the disk fills later. Deletion still
requires a durable intent and retains an unbound object if that fails.
The regression fails on the previous code and passes after this change.
All 597 tests and 276 packaged-source checks pass.

The approved `v3-native-macro-power-20261110-01.local` run has now uploaded
and verified its exact macro, temporarily bound side 12 and announced READY.
It is awaiting the user's off/on + side-12 sequence and explicit report. When
the user confirms completing the cycle, write exactly `{"power_cycled": true}`
with `durable_json` to its `run/power-cycle-report.json`; do not invent that
confirmation. Its process automatically restores on completion or timeout.
Check `run/journal.json` before any new mouse operation. Input-remapper and
production services remain unchanged.

## V3 native macro off/on retention accepted — 2026-11-10

The user completed the requested mouse off/two-second wait/on/side-12 sequence
and explicitly confirmed it. That report was recorded separately from actual
keyboard events. The V3 emitted F24 down/up with an 81.001-ms hold for the
requested 80-ms delay. Post-execution getters verified the catalog, complete
250-byte metadata, six event bytes and both stored/active macro bindings.
The run recorded `power_cycle_retention_observed=true` and
`post_execution_readback_verified=true`.

Cleanup completed `native-macro-restored`, `native_playback_verified=true`,
`original_state_restored=true`, with no experiment/recovery error. Original
functions, reply flags and protected settings matched, preserving 3200 DPI.
The macro catalog is empty again: maximum 307200, free 306176, reclaimable1024
bytes. No format/compaction was used. Full private journal:
`evidence/v3-native-macro-power-20261110-01.local/run/journal.json`.
No experiment is currently running.

This accepts native counted-once execution and retention across the user's
reported mouse switch cycle on the V3 receiver. It does not establish battery
removal/flash implementation, native HyperShift macros, multiple-object/profile
management, repeat/toggle cancellation, V2 native storage or wired transport.
Continue independent production integration; request physical cooperation only
for the next concrete acceptance case.

## Host reboot recovery and profile planning — 2026-11-10

The user reported a frozen CachyOS display and forced reboot. The completed
native macro journal was durably saved at 20:59:51 EST, before the previous
boot's final log entry at 21:02:20. Both native macro primary journals record
successful restoration and deletion. No Gillete/test process survived, and
the production user service is inactive. Targeted previous-boot kernel checks
found no logged GPU/Xid/lockup/OOM/watchdog fault; coredumpctl found no dump in
the relevant interval. Repeated razermouse battery-query timeouts are logged,
but they do not establish the cause of the display freeze. No service/driver
change was made on that evidence.

Fresh read-only V3 verification succeeded after reboot: normal mode, all button
functions matching the last restored snapshot, and an empty macro catalog.
Saved scalar/stage and selector-zero DPI are now 1600 rather than 3200. The
check made no writes and preserves that current state; the origin of the DPI
change is not established. Private report:
`evidence/post-reboot-20261110-01.local.json`. No recovery setter was needed.

Recovered the interrupted `compile_profile` encoder seam and empty planner
file. Completed `native_macro_plan`: pure profile dependency previews deduplicate
event streams, retain each binding's own playback count, choose fresh IDs
outside catalog/dangling references, estimate all allocation blocks and enforce
free-space/slot limits. It preserves normal/HyperShift/standalone resolution,
unknown passthrough bytes and UTF-8 names. Unsupported actions, remaining
hardware acceptance and repeated-playback timing differences are explicit.
No production macro-write capability has been enabled; the preview has no
apply API. The next integration step is an asset-aware production transaction.

Validation after recovery: all 614 tests and 293 packaged-source checks pass.
Fresh Arch/wheel staging, isolated GUI smoke and CLI validation pass without
host installation or remapping. The unfinished source is recovered and the
working tree is checkpointed before proceeding with the production transaction.

## Asset-aware native profile transactions — 2026-11-10

Added the experimental `native_profile_transaction` library. It prepares full
state/catalog/profile artifacts, recompiles them during validation, rejects stale
previews and persists complete originals before the first allocation. Multiple
new assets upload and verify before binding writes. A successful transaction
retains the saved profile and explicit undo data, checking active/stored bindings,
native object bytes and unrelated protected state afterward.

Rollback/undo restore original affected groups and reply flags before cleanup.
They preserve existing macro objects and include sequence-family references
when avoiding IDs/deleting new assets. Partial unverifiable objects retain
recovery evidence; fully verified siblings can be removed independently.
External binding/catalog changes block unsafe overwrites/deletions. Repeated
undo uses fresh reads rather than resubmitting completed deletes. Disk-full
failure after bindings still restores originals using the prewritten journal.

The library has no GUI/CLI hardware caller yet. No mouse query/write or service
change was made in this implementation turn. The current snapshot contract is
the already verified E8 receiver with only bank1 assigned; other slot arrangements,
multiple native assets, shifted macro execution and full production integration
remain pending. Next: build the concrete multi-asset acceptance runner, then
connect verified transaction/recovery behavior to the native Mouse memory UI.

Validation: all 626 tests and 305 packaged-source checks pass. Staged Arch,
wheel, CLI and isolated GUI checks pass without host installation. Tests cover
multi-asset save/undo, sequence references and pre-existing objects, stale and
forged plans, partial uploads/ACK loss, cancellation, external edits, repeated
undo and disk-full restoration. Hardware acceptance remains separate.

## Two-asset / HyperShift acceptance prepared — 2026-11-10

Added the opt-in `native_profile_probe` runner. It admits only the fixed test
profile: normal sides11/12 share F24-down/80-ms/F24-up; shifted sides11/12
share the F23 equivalent. It requires the existing ring-finger HyperShift
trigger, preserves it and every unrelated assignment, and rejects any plan
changing more than exactly those four mappings. The initial catalog must be
empty. It uses the asset-aware save/undo backend rather than a separate writer.

The observer reads this V3's F24/F23/F24/F23 transitions in order, checks actual
press/release pairs and records durations without grabbing/injecting. It also
requires the user's explicit confirmation of the requested physical button
sequence. The shared 180-second deadline starts at READY. Any failure, timeout
or cancellation attempts durable undo; ambiguous objects remain journaled.
Recovery uses `native_profile_probe recover --directory` and the authoritative
`run/profile.json` parent; physical observations live in `run/experiment.json`.

All 634 tests and 313 packaged-source checks pass, including wrong order,
missing confirmation, failed allocation, real-event sequencing and full undo.
Read-only preparation succeeded in
`evidence/v3-native-profile-20261110-01.local/prepared.json`: two fresh objects,
1024 bytes estimated allocation, empty catalog, current 1600 DPI. No allocation
or binding write has occurred. The four changed locations are bank1 controls
0x4a/0x4b, layers0/1; existing ring-finger mappings are unchanged.

Next requires the user's approval for these two native uploads and four saved
binding changes. After READY, ask for side12; ring+side12; side11; ring+side11,
releasing all buttons between combinations. Only after the user confirms the
full sequence write exactly `{"sequence_completed": true}` to
`run/sequence-report.json`. No test is running; input-remapper remains untouched.

## V3 shared native macros and HyperShift observed — 2026-11-10

The user approved the uploads/four mappings and confirmed performing side12,
ring+side12, side11, ring+side11. Actual events were F24/F23/F24/F23 with holds
81.989/82.964/81.998/80.997 ms. Saved state and both objects verified after
playback. This accepts the exact shared-reference/native HyperShift case,
separate from cleanup reliability.

Automatic undo restored the original bindings but encountered an invalid
report length/checksum during final verification. The first fresh-connection
recovery failed with the same error. Its catalog showed both objects were
already deleted and the binding-recovery journal was restored. A second
fresh-connection recovery, instrumented to name any failed command, succeeded
without reporting one. The authoritative `run/profile.json` now records
`restored-readback-verified`, `original_state_restored=true`, an empty catalog
and full normalized original-state equality, preserving 1600 DPI. The separate
experiment retains the initial recovery error and now records
`recovered-after-verification-error` with the verified recovery reference.

Full private evidence: `evidence/v3-native-profile-20261110-01.local/run/`.
No test is running. Openrazer-daemon and polychromatic-tray-applet were observed
running; no kernel error appeared in the checked interval. This does not prove
they caused the malformed reply. No service/driver change was made. Production
macro writes remain gated while communication/recovery robustness is investigated.

## Native desktop read-only review — 2026-11-10

Added Review native macro profile to Mouse memory for the eligible V3 receiver
and active slot1. Preparation rediscovers the selected route, refuses an active
Gillete service and compares inspected identity, firmware, controls, bindings
and saved settings with a fresh complete read-only snapshot/catalog.

The native dialog shows Linux actions, current/proposed bindings, shared asset
count, storage admission and pending requirements. It has only Close, with no
save action or implicit upload. Ordinary Save to Mouse remains unchanged.
Tests cover immutability, stale inspection, service/route gates and the actual
offscreen dialog. All 641 tests and 320 packaged-source checks pass; staged
Arch/wheel/GUI/CLI checks pass. Next: investigate bounded malformed-report
handling before connecting native macro writes to the production UI.

## Bounded malformed-reply handling — 2026-11-10

A deterministic ioctl regression reproduced the transport's immediate abort
when one checksum-invalid reply precedes a valid matching reply. The test went
red for both a query and a setter envelope before the change. The transport
now rejects the malformed sample and may collect another GET_REPORT without
resubmitting the command. Three malformed samples or the existing 0.8-second
response deadline terminate the exchange. Invalid CRC/reserved fields are
never decoded; valid rejection statuses, wrong payload sizes and short ioctl
transfers still fail immediately. Persistent stale/busy replies remain bounded.
Corruption followed by timeout retains ProtocolError rather than being
misclassified as ordinary device unavailability.

Transport counters and last-exchange diagnostics contain only command class/op,
GET counts, malformed counts and completion state, never payload/identity data.
Native profile prepare/save/failure/undo receipts copy cumulative counters to
durable evidence. Unknown failure causes are not attributed to OpenRazer or
other clients from this change.

A fresh read-only V3 snapshot/catalog completed 522 exchanges with 522 GETs,
zero malformed samples and exact equality to the last restored state. Then a
separate read-only test modified one returned mode-query sample's CRC only in
the Python process: the real receiver supplied a valid second GET reply to
the same single submitted query. It recorded malformed1/GET2/completed=true
and independently verified normal mode afterward. This is local fault injection,
not captured hardware-originated corruption or proof of the original cause.
No settings, bindings, native objects, services or drivers were changed.
Private evidence: `evidence/bounded-reply-health-20261110-01.local.json` and
`evidence/bounded-reply-injection-20261110-01.local.json`.

Validation: all 648 tests and 327 packaged-source checks pass, including
persistent corruption, wrong-command/busy replies, unchanged rejection and
short-transfer handling, single-submission setter envelopes and durable health
counter snapshots. Staged Arch/wheel, CLI and isolated GUI checks pass.
No experiment is running. Next: integrate supported native save/undo with
explicit capability gates, retaining unknown-cause diagnostics and recovery.

## Explicit native desktop save and undo — 2026-11-10

Connected the native review to explicit Save to Mouse via the asset-aware
backend, with a new production gate: E8 receiver, observed firmware0101,
active/sole assigned bank1, single-key once-only keyboard macros. Unsupported
multi-key/repeat/turbo/mouse/movement modes remain in Linux profiles and block
native save until their acceptance. These remain full-goal requirements.

Save revalidates immutable prepared artifacts/capabilities and current hardware
state before writing. It waits for the read worker to finish; a panel-owned
timer holds pending writes and is cancelled if the panel is destroyed. Undo
through the existing recovery chooser recognizes native profile receipts and
restores mappings plus safely removes new assets. Save gates cannot disable
recovery, which retains identity/firmware checks. Existing objects stay for
undo, and the preview explains fresh allocations/free space; reuse/pruning
remains pending.

Added journal admission/size guards: preparation accounts for saved/restored
snapshots before any SET, and an oversized update cannot replace readable
originals. Assignment-only slot backup now refuses nonzero native macro
references because it lacks their data. Native families display references
instead of generic device-defined labels. Full receipts and exported Linux
profiles remain the recovery sources.

All new hardware writes in this turn were simulated fixtures. No mouse-setting
write, input grab, service activation, driver change or preset migration occurred.
Next: native multi-key/chord acceptance and managed object reuse, followed by
broader device/service/startup acceptance and migration verification.

Validation: all 663 tests and 347 packaged-source checks pass, including the
firmware/mode gates, actual Qt confirmation, deferred save ordering/cancellation,
asset-aware desktop save/undo, native backup rejection and oversized journal
protection. Fresh staged Arch/wheel, CLI and isolated GUI checks pass. No live
native save was performed during this turn. This is staged UI integration,
not completion of the full macro/device/migration acceptance requirements.

## Native macro reuse and dependency integrity — 2026-11-10

Added `native_macro_library`: bounded metadata scanning and inert event
fingerprints identify byte-identical managed objects. Profile planning can reuse
their IDs; only new uploads count against space/slots. No existing object is
rewritten/deleted. Unchanged saves produce no setting commands, including on
full storage; modifying one stream uploads only that replacement. GUI previews
now show new/reused counts and correct storage costs.

New version2 native receipts require `library_before` fingerprints for reused
objects and macro dependencies of affected original bindings. Apply verifies
them before writes. Undo checks catalog/dependency integrity before restoring
old references, preventing dangling references if original data was deleted or
edited externally. Reused/old objects are never included in cleanup ownership.
Metadata, size and SHA-256 are checked around save/recovery, with bounded query,
time and object-size budgets. Unknown event bytes are never executed.

Artifact validation rejects missing dependency records and version downgrade
claims for reused assets. True old version1 native receipts remain readable and
recoverable with their prior evidence limits. The shared journal reader accepts
version2 only for the native transaction kind. Save failures expose their
recovery path if a durable parent exists. Old managed objects still retained for
undo require explicit pruning later; unrelated catalog data is preserved.

All changes in this step were verified offline with simulated devices; no mouse
query/write, service change or migration occurred. Physical repeated-save reuse
acceptance and native multi-key/repetition validation remain pending.

Validation: all 674 tests and 358 packaged-source checks pass, including no-op
save/undo, one-stream replacement, full-storage reuse, external data/metadata
edits, deleted dependencies, incomplete/version-downgraded snapshots and true
version1 recovery. Staged Arch/wheel, CLI and isolated GUI checks pass. No
hardware operation was performed during this turn. Next: prepare a combined
native key-sequence/repeated-save acceptance case and continue remaining modes.

## Combined native chord/count/reuse acceptance prepared — 2026-11-10

Added `native_sequence_probe` and a dedicated `native_sequence_pad`. The exact
three-object profile changes only both layers of sides11/12 and preserves the
existing ring trigger. Normal side12 emits Ctrl+K, releases Ctrl, then M with
explicit 20/40/20/80/40-ms delays; shifted side12 emits F24 three times with
40-ms holds/150-ms trailing gaps. Both side11 layers share once-only F24 held40ms.

After initial save, the runner prepares/saves that same profile again. All
three objects must be reused and the per-transport Razer setting-command
counter must not increase. Then the dedicated foreground Qt window and selected
V3 evdev observer independently validate logical Ctrl+K/plain M and the exact
F24 count/order. Extra keys, repeats, wrong modifier state, dropped events and
late events invalidate the result. The runner records measured holds/periods.

READY requires the window to be focused and its readiness handshake complete.
The user then reports off/on and side12; ring+side12; side11; ring+side11, waiting
one second between combinations. Input must stay in the dedicated window.
Only after explicit confirmation write exactly
`{"power_cycled": true, "sequence_completed": true}` to `run/user-report.json`.
The runner validates post-cycle state/objects and unwinds the repeat receipt
before the initial receipt. Receipts live in `run/repeat/profile.json` and
`run/initial/profile.json`; `recover` is repeatable after complete cleanup.

Optional private corruption capture retains at most16 malformed frames during
this test and cannot block valid reply collection if capture fails. The
transport's setting-command counter distinguishes actual Razer setting
operations from USB SET_REPORT queries; unchanged-save acceptance uses it.
The pad observes only allowed test keys and consumes local editing shortcuts;
it never opens hardware, injects keys, grabs input or changes keyboard options.

Read-only preparation succeeded at
`evidence/v3-native-combined-20261110-01.local/prepared.json`: three fresh
objects/1536-byte estimate, empty catalog, firmware0101, 1600 DPI and zero
setting commands. No native allocation or binding write occurred, and no
window/test is running. New approval is required for these three objects,
four mappings, actual Ctrl+K/M window input and a reported power cycle.

A read-only Hyprland check found empty global/Naga keyboard options. Physical
F13–F23 desktop interpretation still needs its own acceptance; previous native
F23 tests observed raw keys, while the existing service correction targets its
virtual keyboard. This combined case uses F24, leaving that separate requirement
visible rather than assuming physical XKB behavior. No keyboard setting changed.

The production native save gate now explicitly blocks F13–F23 until their
physical-keyboard desktop interpretation is accepted, rather than extending
the earlier raw-key result to Qt/application behavior. F24 and ordinary key
families remain eligible under existing gates. Linux service correction and
existing stored mappings are unchanged. This is a remaining compatibility
requirement, not a reason to omit the requested function-key support.

Validation: all 688 tests and 372 packaged-source checks pass, including raw
edge order/count, desktop modifier state, extra/late events, missing human
confirmation, failed apply, nested/idempotent recovery, setting-command counters,
readiness-gated pad capture and failed diagnostic storage. Staged Arch/wheel,
CLI and isolated GUI checks pass. No test/window is running and no native
setting was written during preparation.

Additional production follow-up from code inspection: undo currently compares
the entire original protected snapshot. An unrelated legitimate DPI edit can
therefore cause recovery-required after restoring affected bindings. Investigate
scoped undo that preserves unrelated current state while retaining affected-group,
catalog and original macro dependency guards. No such behavior change was made
in this preparation step. Managed-object pruning and physical function-key
compatibility remain outstanding too.

## Scoped desktop native undo — 2026-11-10

Implemented the production follow-up identified above. Desktop restore now
requests explicit scoped undo: current unrelated settings/mappings/catalog
entries are preserved while affected original groups and reply flags are
restored. Snapshot projection checks that inverse writes did not alter that
unrelated current state. Original macro dependencies are checked before inverse
writes; missing/changed dependencies and externally edited affected mappings
still block restoration. Geometry/route/profile changes are not treated as
ordinary unrelated edits.

Owned macro objects still referenced elsewhere, including sequence references
on unknown controls/unassigned banks, remain in memory with receipt reasons.
Byte-mismatched objects are retained without attribution; communication errors
remain failures, not false cleanup success. Receipts/UI distinguish affected
mappings restored from complete original captured-state restoration. Repeated
scoped undo is safe and does not resend completed deletes. Save admission now
rejects active/stored differences in affected groups before writing.

The default strict rollback/undo path is unchanged for acceptance runners,
including the combined test currently awaiting user approval. New code was
verified only with simulated devices/offscreen GUI tests; no hardware query,
setting write, keyboard change, service activation or migration occurred.

Validation: all 704 tests and 388 packaged-source checks pass, including later
DPI/settings edits, shared/modified objects, missing original dependencies,
independent active-bank edits, communication failures and repeatable undo.
Staged Arch/wheel, CLI and isolated GUI checks pass. The earlier four-tap
shared/HyperShift result is already captured and restored; a repeated human
confirmation does not authorize or establish the newer combined chord/count
experiment, which has not run.

## Diagnostic evidence refreshed — 2026-11-10

Updated the desktop's historical feature-validation rows to reflect the actual
development-unit results: V3 firmware1.1 once-only native keyboard macros,
shared objects/HyperShift/off-on retention, and scalar1200-DPI observations in
normal/driver mode with off-on/replug retention. Native chord/repetition/F13–F23
acceptance, saved DPI-stage/polling writes and automatic sensitivity integration
remain explicitly pending. V2 onboard macro storage is separately unavailable
according to its Synapse model; opaque saved references are not proof of
standalone playback. These rows still do not certify the currently connected
unit, and diagnostics performs no new mouse/input operations.

Validation: all64 diagnostic/GUI checks pass. No capability gate, device setting,
service, keyboard configuration or remapper was changed by this text update.

## Native Keep stored bridge and keymap research — 2026-11-10

Fixed an integration gap: native macros saved by Gillete previously became
unresolved firmware references in software mode. V3 receiver/firmware0101
inspection now reads the bounded catalog and complete supported counted-once,
single-key event bodies twice, then rechecks their referring bindings. Actual
bytes and delays resolve through the existing cancellable Linux macro runner.
No reference alone is treated as executable. Unsupported/changed/missing objects,
other routes/firmware, zero references, repeated/multi-key/mouse streams remain
unresolved. Optional read errors are visible without publishing partial bodies.

Service startup rechecks required native bodies on its newly opened transport
before input ownership; explicit host overrides do not depend on unused objects.
Private snapshot serialization preserves supported bytes with size/ID validation
and remains compatible with older snapshots. Software acceptance comparisons
include captured bodies. No setter, upload, delete, grab or live service action
was performed; physical cross-mode acceptance remains pending.

The completed first-party Hyprland/XKB research is in
`native-keyboard-compatibility-research.md` (commit1fafddf). It establishes that
physical device-name suffixes are not USB identity, no public address selector or
exact field-unset/query exists, runtime rules outlive disconnects, and restoring
effective options does not restore inheritance. The standard option also leaves
modified F23/F24 aliases at higher levels. README claims now distinguish the
accepted base-symbol correction from those unfinished combinations. No physical
keyboard rule or global option was changed, and the virtual-only guard remains.

Validation: all754 tests and438 packaged-source checks pass, including complete
readback, changed dependencies, zero/missing references, getter-only admission,
snapshot compatibility, software preflight and cancellation. Staged Arch/wheel,
CLI and isolated GUI checks pass. The combined hardware test remains prepared,
not run, while awaiting the user's readiness response.

## Complete virtual function-key maps — 2026-11-10

The user deferred the combined V3 experiment and requested continued building.
No mouse experiment was started. Implemented an offline libxkbcommon compiler
and connected it to the uniquely owned virtual output, replacing the incomplete
standard-option correction. It explicitly replaces F13–F24 symbols/types/actions
in every compiled layout, preserves repeat policy, and verifies all256 core
modifier masks per key/layout with no consumed modifiers or altered key state.
Tests reproduce and fix the prior Shift+Super+F23/Control+Super+F24 aliases.
Ignored RMLVO errors/layout loss and non-evdev Fn keycodes are rejected.

Each output has a fresh UUID. A private compiled-file marker in Hyprland's
actual active layout establishes loading before physical input ownership;
RMLVO strings alone cannot do that. The watcher covers identity, rules,
marker and file/source fingerprints. Closing precedes private-file retirement;
cleanup does not guess old inherited settings or issue inverse setters. The
runtime rule remains scoped to a name that is never reused. The physical-name
guard is retained and tightened to the new owned format. Custom absolute
keyboard files are preserved; unsupported/relative inputs block activation.

Implementation, sources, lifecycle limits and remaining live acceptance are in
`virtual-function-keymap.md`. Tests use the real library plus a simulated
compositor; no live keymap rule, physical setting, service or remapper changed.

Validation: all790 tests and480 packaged-source checks pass. The real-library
matrix includes modifiers, multiple layouts, custom maps and keycode mismatch;
the simulated compositor covers actual-file marker loading, rejected/fallback
loads, ownership/configuration changes, file replacement and cleanup without
inverse setters. Non-regular files are rejected without blocking. Staged
Arch/wheel, CLI and isolated GUI checks pass. Live virtual-output delivery and
the previously prepared native mouse experiment remain deferred.

## Selected-mouse native memory preflight — 2026-11-10

While tracing managed-storage work, found a production usability gap: native
review/save/undo rejected any existing daemon socket, even after the selected
mouse was disabled. Replaced that existence check with a bounded, read-only
status request. The selected model must report requested=false, active=false,
no remaining transport/session and no pending startup preference. An idle
daemon or another enabled model no longer blocks direct memory work.

Old/malformed status, permission errors and timeouts do not prove release.
Absent/refused listeners are not started, removed or otherwise repaired; the
subsequent exclusive HID lock and normal-mode/identity guards remain required.
No configuration identity is sent in the status-only request, so another
configuration's live ownership is still checked. No control command is issued.

Tests cover every ownership phase, incomplete/old status, a real private Unix
socket, other-model activity, and review/save/restore refusal before opening
hardware followed by success after selected-model release. No hardware or
live service action was performed. Managed native-library review/reclamation
remains the next implementation task; physical tests stay deferred.

Validation: all816 tests and506 packaged-source checks pass. Staged Arch/wheel,
CLI and isolated GUI checks pass. The status-only private socket test and all
three desktop native entry points preserve the other model's requested state.

Managed reclamation must review complete current bank/control/layer references,
match metadata and full event bytes to validated local save artifacts, retain
foreign/changed objects, and identify affected undo receipts before deletion.
Any loss of old undo dependencies needs explicit acknowledgement in the final
review; no history is silently discarded. Admission and every deletion need
fresh identity/reference checks and durable intent. Uncertain delete results
are resolved by new catalog reads, never a blind repeated setter.

## Managed native storage review and explicit deletion — 2026-11-10

Implemented `native_history`, `native_cleanup` and `gui_native_library`, connected
to Mouse memory after an eligible V3 firmware1.1 read. Review compares catalog
objects against fully validated local upload artifacts, retains foreign/changed
objects, and scans every bank/control/layer before allowing an unused object.
It lists affected original catalog/mapping dependencies and requires explicit
undo acknowledgement, reset when selection changes. History files and Linux
profiles remain untouched; private cleanup receipts retain selected full bytes.

Apply reconstructs the preview, then repeats reference/protected-state, catalog,
history, ownership and identity checks before each durably journaled deletion.
The progress window can stop between checks, including after durable intent but
before the setter. Lost replies are observed through fresh catalog reads without
repeated SETs. An interrupted batch needs a fresh review, not blind resume.
No mode, binding, sensitivity, upload, format or defragmentation change is sent.
Actual free/reclaimable counters are reported separately; safe compaction remains
an outstanding protocol task. See `native-storage.md` for limits and acceptance.

All implementation verification is offline with simulated devices/Qt widgets.
No hardware operation or live service/migration change was performed, and the
user's physical-test deferral remains in effect.

Validation: all860 tests and550 packaged-source checks pass. Coverage includes
all four macro-reference families, unknown controls/unassigned banks, exact byte
ownership, changed/foreign objects, old undo dependencies, altered history/state,
selection forgery, lost replies, cancellation during durable intent and between
objects, disk-write failures, bounds, dialog acknowledgement/cancellation,
reader-before-writer sequencing and idle-model desktop entry points. Staged
Arch/wheel, CLI and isolated GUI checks pass. No real object was deleted.

## Authoritative manual profile selection — 2026-11-10

The editor previously treated a missing cached service status as proof that the
service was offline. Selecting a pin could then write preferences locally while
an unreachable live service still owned the mouse. Selection now always asks
the live service to validate and apply the profile first. Only an absent/refused
listener permits an offline preference save, held under the daemon's lifetime
lock through a revision-checked write. Startup, shutdown, timeout, permission,
configuration and malformed-acknowledgement failures do not permit fallback.

Literal profile IDs are separate from Automatic in the new selection command;
a profile whose ID is `automatic` can now be pinned. The existing CLI selector
remains compatible. Offline selection never starts a service or enables a mouse.
Per-mouse preferences and unrelated concurrent profile edits remain preserved.

Validation: all875 tests and566 packaged-source checks pass, including a real private Unix socket with the
daemon command handler, lifetime-lock contention, lost/invalid acknowledgements,
live preflight rejection and GUI worker routing with no cached status. No live
service, hardware, compositor or input-remapper settings changed. Staged
Arch/wheel, CLI and isolated GUI checks also pass; no host package was installed.

## Native lifecycle/polling trace and read-only observation tooling — 2026-11-10

Reviewed the completed source report `remaining-native-protocols.md`. It pins
first-party bundles/factory ranges and separates packet construction from actual
firmware behavior. Slot creation can delete/initialize an existing target and
omit default binding writes; new-slot contents and lossless rollback remain
unresolved. The traced `defragStorage` resets/deletes profiles, formats storage
and rebuilds only selected decoded fields. Polling/scroll/debounce, active ID and
opaque bytes are not fully restored. Format/rebuild remains excluded.

V3 source defines separate ordinary, per-profile and high-speed polling families.
High-speed dispatch depends on injected flags and connection state, still
unresolved. Implemented `polling_reads` and an explicit E8-only
`firmware_probe --sections polling` observation path. It queries assigned IDs,
distinguishes encodings, retains unknown values without the source decoder's
8000-Hz fallback, validates echoes and rechecks completed values. A clean device
rejection ends that family; uncertain failures stop remaining polling queries.
No failed query is retried. Baseline firmware, mode, identity, assigned/active
inventory, active mirror/slot bindings and ordinary settings are compared.

The existing request/time limits reserve verification work. Reports distinguish
nominal code recognition from measured cadence, conditional route selection,
setter support and retention; all those capability claims remain false. Ordinary
application read/settings allowlists and polling choices stay unchanged.
Desktop diagnostics expose high-speed and compaction limits. V2 and wired
candidate polling are rejected before discovery/report creation.

No mouse, service, keymap, remapper or system package was changed. Tests use fake
devices/sockets and offscreen widgets; physical tests remain deferred. The
previously prepared combined V3 test is still pending the owner's readiness.

Validation: all905 tests and596 packaged-source checks pass. Coverage includes
all256 reply codes in both families, exact request framing, selector/transport
rejection, no production allowlist expansion, clean rejection versus uncertain
failures, candidate and baseline drift, failed rechecks, assigned-only selectors,
private new-only reports and summaries without hardware identity. Staged
Arch/wheel, CLI and isolated GUI checks pass. The two new test-fixture mistakes
(a category-ambiguous fake firmware response and expecting a file exception
through argparse's error boundary) were corrected before the passing run.

## Focus events cancel before window queries — 2026-11-11

Code inspection found a gap in the requested focus-loss behavior: the watcher
awaited `hyprctl activewindow` before canceling macros. Reproduced it with a
blocked query and a running toggle turbo; the original test failed with its
macro job and held key still active. The production watcher now consumes the
event stream independently of its single window-query worker. Active-window
events establish a pending boundary and cancel before querying; an Event
coalesces refresh requests, with revision checks before and after engine updates
to reject superseded results. No per-event task/query queue grows unbounded.

Mapped input, hardware button commands and new service activation wait for
settled focus. Existing sessions retain ownership during a refresh, continue
pointer movement and releases, and suppress pending/old presses until release
and a fresh press. Publishing current focus fences reports buffered during the
query, including when the final profile is manually pinned or focus returned to
the same window. Title-only refreshes preserve unchanged profiles and running
macros. A profile-changing title update gates input while outputs are released;
if superseded mid-update, it stays gated until the current result is applied.

Query failure/disconnection stops both monitor workers and marks focus
unavailable; query cancellation kills/reaps its owned subprocess. Startup choices
remain pending during refresh, and software control/diagnostics show the wait.
Malformed active-window field types fail rather than becoming string identities.

Event framing comes from the first-party [Hyprland IPC documentation](https://wiki.hypr.land/ipc/):
activewindow/activewindowv2 are focus notifications; windowtitle/windowtitlev2
refresh title matching. Event contents are not interpreted as commands. Tests
use in-memory streams, packet sockets, simulated outputs and stub subprocesses;
no live desktop, service, input capture, mouse setting or remapper was changed.
The owner's physical-test deferral remains in effect.

A separate read-only smoke check connected this watcher to the current Hyprland
event socket and parsed a real active-window query successfully: available=true,
pending=false, a focused window present and zero engines attached. It generated
no input, accessed no mouse node and retained no window title/class in its
summary. This establishes initial desktop IPC compatibility only; physical
macro delivery/cancellation and the deferred acceptance tests remain pending.
An additional reset-on-close test found and fixes a reconnect error path: an
OSError from closing the old compositor socket no longer terminates monitoring.

Validation: all928 tests and645 packaged-source checks pass. The regression
first failed on the old watcher. New coverage includes 100-event coalescing,
in-flight/lock-wait/mid-release invalidation, pinned turbo cancellation before a
blocked query, unchanged title refreshes, malformed query fields, subprocess
cleanup, disconnect/reset recovery, pending input/commands, drag releases and
fresh-press recovery. Staged Arch/wheel, CLI and isolated GUI checks pass; no
host package or service startup preference was installed or enabled.

## Complete control/layer software acceptance prepared — 2026-11-11

The existing live software examples cover a few bindings, not every required
control. Implemented `control_validation`, `control_trace` and `control_pad`,
integrated as `guided_service prepare --suite controls`. The reviewed recipe
requires42 V2 or50 V3 taps: every electronic12-button control in both layers.
A second holdable trigger allows testing the first HyperShift trigger itself;
the second trigger was already tested normally/shifted in phase1. Each marker
is a unique F13–F24/Shift/Ctrl/Alt combination, displayed in preparation.

The optional daemon flag `--trace-controls` supplies at most512 routed mouse
edges per selected session, with an independent epoch, layer, generation and
source. It records no raw report, keyboard-device input, pointer coordinate or
action argument. Ordinary launches construct no trace. The pad opens no input
or service socket: it receives controller snapshots and foreground Qt events.
Typing a marker without mouse edges cannot count. Duplicate held reports and
suppressed/disarmed inputs cannot fabricate fresh taps; wheel pulses produce
paired evidence through the real router path.

The pad guides one tap at a time, waits for release/quiet and automatically
changes its title to select the alternate profile after phase1. R retries while
retaining failures; Escape ends the test. Exact rules apply only to its class/
titles, with the reviewed fallback outside. Session/route changes, focus loss,
wrong layers/controls/modifiers, extra keys and missing evidence fail rather
than filling a tally. Quiet verification uses service observation time, not
delayed reply arrival. Receipts are re-evaluated against the full recipe, live
trace epoch, nonce and run interval. Evidence size/write failures retain the
last partial file and never publish a verified completion.

The controller still claims an isolated configuration/state directory, reaps
only its own children and verifies normal mode plus unchanged captured stored
state before reporting success. Known firmware/wheel metadata is now included
in that check while battery changes remain harmless. Macro preview labels also
describe the actual sequence instead of assuming every macro is Ctrl+K then M.
Older example plans remain supported. Detailed scope, limitations and recovery
are in `software-control-acceptance.md`; diagnostics call the new suite prepared,
not physically passed. Native/onboard and wired admission gates stay unchanged.

No hardware preparation/run, live service, generated input, keyboard setting,
input-remapper or system package change occurred. Tests use synthetic frames,
recorded outputs, in-memory service mocks and offscreen Qt. The owner's physical
test deferral and the earlier prepared combined native experiment remain intact.

Validation: all993 tests and707 packaged-source checks pass. Simulated runs drive
all42/50 pairs through real Engine/Router logic, then feed actual Qt key-event
objects into the offscreen pad. Coverage includes pulse wheels, cross-interface
shift ordering, trigger rotation, missing/extra/wrong evidence, stale/dropped/
rewound data, epoch/time/route mismatch, partial close/retry, disk/size failures,
controller cleanup and unchanged legacy example behavior. Staged Arch/wheel,
CLI and isolated GUI checks pass. No host package was installed.

## Synapse polling feature parameters resolved — 2026-11-11

Completed the bounded retained-build trace in
`synapse-polling-feature-flags.md`. Model231 registers a frozen empty object for
`highSpeedPollingRate.yes`; the named wired/wireless flags are absent/undefined,
not explicit false declarations. The first-party injector does not merge hidden
default parameters into that object. The independent E8 dual-link/master branch
can still select high-speed polling without either property. Its real logical
PID/cache/master state was not observed. The result narrows source uncertainty
without admitting another polling rate or rejecting firmware capabilities.

Reviewed the pinned injector/startup and consumer ranges against original-byte
hashes. REA static coverage remains bounded and partial; exported zero-unknown
counts are not treated as completeness. No shipped code or Windows runtime was
executed. The delegated investigation changed only its research document and
ignored private evidence. The parent separately recorded cached Linux sysfs USB
enumeration: both attached receivers expose 1ms interrupt-IN endpoint intervals.
No hidraw/input node, feature query, mouse wake or setter was used. This cache is
not a measured motion cadence, firmware maximum or Synapse session route.

Updated the earlier protocol report and README to distinguish those findings.
A matching Windows session would attribute Synapse routing; separately authorized
Linux command-effect, cadence and restoration acceptance can independently prove
support on an exact transport. Physical tests and production gates stay deferred.

## Reviewed mouse-read to Linux-profile copying — 2026-11-11

Added **Create Linux profile from this read…** to the mouse-memory panel. It
copies the last inspected assigned slot into a new inactive local profile, using
explicit per-mouse overrides for both layers. Shared mappings, the other mouse,
defaults, pins, rules and startup selections are preserved. Inactive assigned
slots can be copied without pretending they are active. No fresh hardware query,
service command or mouse write occurs during review/creation.

The draft freezes its source and validates receiver/model, slot inventory and
complete assignment records. Recognized stored actions become editable host
actions, including already-supported native single-key once-only bodies; portable
profiles contain no unit identity or native macro IDs. Unknown functions retain
Keep stored until the user explicitly disables that row locally. Recognized rows
can also be disabled, allowing unavailable native device actions to be replaced
later. Originals on the mouse remain intact. This is not a complete firmware
backup and does not import DPI, polling or opaque native data.

The review shows actual HyperShift triggers and known device prerequisites. A
normal held trigger remains effective on both layers; its shifted choice cannot
contradict the retained normal trigger. Removing that normal trigger makes the
shifted choice editable. Creating an unfinished profile is allowed, while existing
activation checks continue to block unresolved actions when the profile becomes
selectable. Creation opens the new profile in this mouse's overrides for editing.
Conflicting external edits and failed saves abort without overwriting the existing
configuration or activating the new profile.

Validation: all1012 tests and726 packaged-source checks pass. New coverage includes
both models/layers, missing/mismatched reads, effective inherited triggers,
explicit row choices, native-body conversion, inactive slots, immutable review,
cancellation, disk failure and concurrent edits. Staged Arch/wheel, CLI and
isolated offscreen GUI checks pass. No host package, live service, generated
input, remapper migration or hardware experiment occurred. The owner's physical
test deferral remains in effect; the earlier combined V3 native experiment and
complete receiver-control suites remain prepared, not passed.

## Configurable emergency-stop shortcut — 2026-11-11

The specification requires a configurable emergency shortcut, but the service
previously fixed it at Ctrl+Alt+Pause. Added a validated local preference and
Startup controls for Pause/F1–F12 plus optional Ctrl/Alt/Shift/Super. Legacy
version1 configurations retain the default. Preferences normalize into a bounded
chord rather than accepting arbitrary compositor syntax. Profile import and
duplication preserve the local choice.

The daemon takes its active choice at startup. Saving a preference or reloading
profiles leaves that choice installed until the service is stopped/restarted;
enabling the second mouse reuses the active choice. Status/Software control show
the active, configured and saved choices, including restart-required state.
The Startup save reads current configuration and changes only this preference.
No compositor/service command, remapping or startup activation occurs on save.

Conflict inspection covers the selected named key, known XKB keycodes, submaps
and reported ignore-modifier bindings. The existing installed receipt contains
the exact observed binding; cleanup does not unbind if another matching row was
added. Removal is read back, and failures retain the receipt. Switching after an
interruption first recovers an unchanged owned old chord; a user replacement
is preserved. Old receipts without a chord field retain their default meaning.

New installations journal intent before the compositor mutation, including before
the older keyword fallback. If a reply is lost after creation, shutdown or a later
start can identify the pending owned row and verify its removal or adoption.
Prepared Lua recovery uses the recorded generated description; legacy recovery
uses the exact executable command. Neither claims ownership of arbitrary rows.
An unwritable intent journal prevents the mutation. These are bounded registry
checks, not an atomic lock against other desktop configuration writers.

The implementation uses first-party [Hyprland bind/unbind syntax](https://wiki.hypr.land/configuring/core/binds/)
and preserves the documented case-sensitive chord on removal. Tests substitute
an inert compositor registry and temporary stores: no live binding was read,
added or removed, and no hardware, service, remapper or host package was changed.
Live shortcut/desktop acceptance remains pending with the other deferred tests.

Validation: all1061 tests and775 packaged-source checks pass. Coverage includes
old configuration/receipt migration, custom Lua and legacy chords, named/code/
submap conflicts, lost replies, failed journals/removal, shared and replaced
bindings, local-only GUI saves, active/pending display and service reload/restart
semantics. Staged Arch/wheel, CLI and isolated GUI checks pass. No host package
was installed and no live shortcut or physical test was run.

## Compact native control editor — 2026-11-11

An offscreen layout audit found the main window's minimum size was893×778:
the visual control selector forced a taller window than a768-pixel desktop,
even before decorations. Wrapped that selector in a resizable scroll area.
The mapping table keeps its own viewport, and the selector reveals a control
when selected from the table or focused with the keyboard. Profile controls
and the normal/HyperShift editor remain reachable without hiding controls.

Repeated the audit with a1024×640 offscreen window: minimum size is893×580,
all six tabs retain the requested height, and all21 V2 plus25 V3 control positions
can be selected and fully revealed. Keyboard Tab/focus navigation also reveals
its target. Action/macro/settings dialogs were inspected for minimum-size issues;
their existing minimum heights fit this check. This is Qt layout evidence for
the tested font/platform, not live Wayland rendering or physical input acceptance.
The audit uses temporary profiles, disabled service polling and stubbed device
discovery; it reads no mouse or desktop input and sends no service commands.

The same audit with a valid256-character pinned profile found a second constraint:
the minimum width grew to2511 pixels. The profile picker now uses a bounded
contents hint, and the pin/status labels wrap as plain text within available
width. Spaced and unbroken256-character names, literal markup and the longer
profile-copy status now fit the1024×640 window; full pin text has sufficient
wrapped height. No profile data or selection behavior is changed.

Validation:73 relevant GUI/mapping/HyperShift checks and775 packaged-source checks
pass. Staged Arch/wheel, CLI and isolated GUI checks pass. The two layout audits
also exercised actual offscreen Qt geometry and keyboard focus. No tests were
added just to mirror this layout change. Full physical acceptance and migration
remain deferred, and no host package or live remapper was changed.

## Combined V3 native test: desktop sequence observed, raw validation failed — 2026-11-11

The owner approved the prepared combined experiment and confirmed switching the
V3 off/on and completing all four combinations. The existing prepared directory
`evidence/v3-native-combined-20261110-01.local` now contains its single completed
run. Do not restart that run or reuse the human confirmation for another test.

The test window recorded the expected16 edges: Ctrl down, K down/up, Ctrl up,
plain M down/up and five F24 pairs. K had Ctrl, M had no modifiers, and no
unexpected desktop key was recorded. The repeated save reused all three objects
with zero Razer setting commands. However the selected mouse's raw observer
raised `Unexpected native chord/count key sequence`. It did not retain the
offending event. Therefore the experiment is `test-failed-restored`, not a pass;
raw order/timing, post-cycle asset verification and wider native admission are
not established by the visually correct desktop sequence.

Both nested transactions report `restored-readback-verified` and
`original_state_restored=true`. The initial transaction's final catalog is empty;
the three test macros were removed. Final storage reports3584 recyclable bytes,
not free/compacted memory. No format/rebuild was attempted. The test process
finished with exit1, and its window was closed by cleanup. Input-remapper was
not changed. Source gates remain unchanged.

Diagnosis is limited by missing raw failure evidence. A deterministic offline
replay reproduced this evidence gap: an out-of-order F24 edge raises the same
validator error, but the observer exposed no trace. This does not reproduce or
identify the underlying hardware failure. Added a bounded128-event tail with
source indexes, timestamps, type/code/value, expected-edge index and failure.
The next run saves it privately as `raw-input.json` after cleanup; it contains
only the selected mouse's key/drop events, no event-device paths, unit identity
or pointer motion. Capping is explicit and keeps the offending tail event.
No filesystem write occurs inside the input loop. Trace-save failure cannot
prevent the runner's existing hardware cleanup. Acceptance rules are unchanged.

The regression first failed with a missing trace API, then passed through the
real rejecting observer and transaction cleanup path with simulated sources.
The original raw-order cause remains unresolved: a fresh awake-mouse preparation
and another explicitly coordinated physical run are needed to collect it.

Fresh read-only preparation completed at
`evidence/v3-native-combined-20261111-02.local/prepared.json`: the exact same
three-object/four-mapping experiment,1536 estimated bytes, empty initial catalog
and zero preparation setting commands. It has no run directory and has not been
activated. This proposal includes the new failure trace for a future approved
repeat; the prior confirmation is not transferred.

Validation: all1063 tests and777 packaged-source checks pass, including bounded
failure evidence and retained offending events after verified simulated rollback.
Staged Arch/wheel, CLI and isolated GUI checks pass. Only the first approved
physical run and subsequent read-only preparation accessed the mouse; no second
write experiment, production capability expansion or migration occurred.

## Combined V3 diagnostic acceptance and DPI-preserving recovery — 2026-11-11

The owner approved repeating the same combined test with raw diagnostics.
Attempt02 stopped before creating its initial transaction: current DPI/stage
had changed from1600/stage3 to800/stage2. No macro/mapping write was admitted.
The wrapper's historical `recovery-required` status reflects the preparation
mismatch, not an instruction to overwrite the current settings. The read-only
state review retained the differing fields and submitted zero setting commands.

The same authorized test was refreshed to that current state as attempt03.
Three macros uploaded, but DPI changed again to400/stage1 before test bindings
were applied. Strict cleanup refused deletion while unrelated state differed.
The owner confirmed pressing an index/DPI button to wake the mouse, then selected
their preferred setting and explicitly requested it be kept. Scoped undo first
stopped on another state change, then verified affected mappings and unrelated
current state, removed all three verified unreferenced objects and left an empty
catalog at the selected1600 DPI. Its receipt is `affected-bindings-restored`;
`run/recovery-outcome.json` records the resolution without rewriting the earlier
failed experiment. No DPI setter or format/rebuild was used in recovery.

Fresh attempt04 matched that recovered1600-DPI snapshot and retained the exact
approved assets/mappings. Preparation submitted zero setting commands. The owner
was instructed to wake by movement only and confirmed off/on plus all four taps
after actual READY. The completed run is
`evidence/v3-native-combined-20261111-04.local/run/experiment.json`.

This time raw and Qt records both contain exactly16 expected edges, including
Ctrl+K, plain M and the five F24 pairs. The raw tail has `expected_edge=16`, no
failure and no cap. The repeated save reused three objects and submitted zero
setting commands. Post-cycle protected state and all macro bytes verified.
Measured K/M holds were42.002ms; the counted F24 holds were40.999/41.999/42.001ms
and onset periods193.001/195.001ms for requested40ms holds plus150ms gaps.
These are measured timings, not a claim of exact scheduling or instrumented
battery-removal/NVM behavior.

The runner exited0 with `native-combined-restored`. Both nested transactions
report original-state restoration, and a separate receipt audit rechecked both
event sequences, reuse telemetry, empty final catalog and1600×1600 saved DPI.
Final recyclable storage is6656 bytes; this is not automatically free space.
No test/window remains running. Input-remapper and startup settings were not
changed. The cause of the first raw-order rejection remains unknown; this
successful instrumented run did not weaken the validator or retrospectively
turn the first failure into a pass.

## Native keyboard save admission follows the combined result — 2026-11-11

Explicit native saving on the accepted E8/firmware0101/sole assigned slot1 route
now admits balanced keyboard sequences played once and counted single-key
macros. The accepted combined profile first failed the old gate, then passed
after the policy change. The source-backed count byte permits1–255; the physical
case exercised three F24 iterations, not every parameter value. Values above255
still fail before transport writes. Counted multi-key, held/toggle/turbo, mouse,
movement/keyless macros, native F13–F23 desktop interpretation and other routes
remain gated. Existing compiler size/encoding and transaction guards still apply.

The pure preview and explicit-save check share this action policy. Removed stale
generic pending messages for shared objects, HyperShift and asset-aware recovery
that now have implementation/physical evidence. Firmware/route checks remain in
the actual save gate. Counted previews explicitly state the trailing final gap
and that native playback runs to completion; focus cancellation requires Linux
service playback. Native saves preserve the explicit Linux profile actions.
Keep-stored decoding is still limited to separately verified single-key once
bodies, so other stored bodies need explicit Linux mappings for service use.

Validation: all1069 tests and783 packaged-source checks pass. New checks admit
the exact accepted combined profile, exercise encoded counts1/2/3/255, reject256
before writes, and retain the remaining family/route gates. Staged Arch/wheel,
CLI and isolated GUI checks pass; no host package or startup preference changed.

Prepared the next receiver software check read-only at
`evidence/v3-controls-20261111-01.local/prepared.json`:50 taps cover all25 controls
on both layers, rotating the held HyperShift trigger so it is tested too. The
proposal retains all50 original descriptors and current1600 DPI. It has no run
and requires separate approval for temporary driver mode, input ownership and
virtual-keyboard output; the native macro approval does not cover that scope.

## V3 complete receiver control/layer software acceptance — 2026-11-11

The owner approved the prepared50-tap V3 software test, including temporary
driver mode, selected-mouse input ownership and virtual output. The controller
finished with exit0 and `CONTROL COVERAGE VERIFIED`. Its50 passing receipts
cover all25 electronic controls normally and under HyperShift, rotating the
trigger to test ring-finger normally/shifted as well. Coverage is in
`evidence/v3-controls-20261111-01.local/run/coverage.json`.

Independently replayed the receipts against the exact prepared recipe, readiness
nonce and captured service epoch; every source edge and Qt key pair validates.
Four failed attempts remain recorded: normal left-click had an unexpected Meta
event; shifted sides8/9 crossed the arming/cancellation boundary; shifted
top-rear received F23. Their subsequent attempts passed. They are not erased or
counted as passes, and no cause beyond the recorded errors is asserted.

Restoration reports normal mode, unchanged stored state and all50 original
descriptors, with zero errors. The owned mode journal is normal-mode-restored;
service shutdown has no notes. The verified saved baseline was1600×1600 DPI.
The owned daemon/window exited, leaving no running remapping test. No permanent
mapping, setting, macro, input-remapper configuration or startup change occurred.

This is also live Qt evidence for the new compiled virtual keymap's F13–F24 base,
Shift, Alt and Shift+Alt combinations, plus Ctrl/Ctrl+Alt on F13. All256 modifier
masks remain offline evidence; physical onboard keymaps and other applications,
layouts, reloads, suspend/replug and full macro/profile lifecycle remain separate.
Diagnostics and acceptance/keymap documentation now distinguish the passed V3
suite from the pending V2 and wired suites. Saved/onboard every-button persistence
is not inferred from software input coverage.

The first V2 read-only preparation timed out before mode read succeeded, with
no setting changes. After the owner explicitly woke it by moving, preparation
completed at `evidence/v2-controls-20261111-01.local/prepared.json`. It retains
all42 original descriptors and the actual current DPI, and proposes42 guided
taps with rotated index-button triggers. No V2 live run, input grab or mode
change has started; that separate scope still requires approval. V2's existing
Synapse assignments remain its originals, not factory defaults.

Validation:78 relevant diagnostics/GUI checks and783 packaged-source checks pass;
the final diagnostic wording check also passes. Arch/wheel, CLI and isolated GUI
checks pass. V2 preparation preserved its current1800×1800 DPI and has no run
directory. No host package was installed and no remapper migration occurred.

## V2 complete receiver control/layer software acceptance — 2026-11-11

The owner approved the42-tap V2 software test. Its first activation was blocked
by an exclusive event-device grab. Cleanup verified normal mode, unchanged saved
state and42 original descriptors, with no mode journal or shutdown notes. No
successful input-ownership claim or coverage was inferred from that attempt.

Read-only process/descriptor inspection and the installed input-remapper API
identified its V2 injector as RUNNING with global suspension false. No process
was killed. The owner then explicitly authorized temporarily stopping only the
V2 preset and restoring the exact same preset afterward. A fresh read-only
proposal was prepared at `evidence/v2-controls-20261111-02.local`.

The private handoff journal recorded the original preset and file fingerprints
before the stop. It stopped only the V2 group through the existing daemon's
device-specific API, launched the reviewed isolated test and arranged to restore
that preset only after verified normal-mode/stored-state cleanup. It did not
change preset/autostart files or suspend other groups. The final wrapper and
controller both exited0.

The live test completed42/42 control/layer pairs, including normal and shifted
front/rear index triggers through trigger rotation. Its source/Qt receipts
independently replay against the exact recipe, readiness nonce and service epoch.
Seven failed attempts are retained: initial left-click lost focus; shifted
rear-index and sides1/3/4/10 crossed the arming/cancellation boundary; another
shifted side1 attempt had a desktop order/count mismatch. Their later attempts
passed. No failure was erased or used as a pass, and no cause beyond the recorded
error is asserted.

Restoration verifies normal mode, unchanged stored state/all42 descriptors and
the1800×1800-DPI baseline with no errors or shutdown notes. The owned mode lease
is normal-mode-restored. The handoff receipt is original-preset-restored; a fresh
read of the existing daemon independently confirms the same original V2 preset
RUNNING and matching preset/config/xmodmap file hashes. The owned Gillete test
daemon/window exited. This is temporary coexistence, not migration.

Both receiver suites now pass92 total normal/HyperShift control pairs. Diagnostics
and documentation reflect that bounded result. V2 macro/turbo/focus examples,
wired operation, saved/onboard coverage and broader lifecycle acceptance remain
separate. Cached discovery still shows only B4/E8, so the next wired investigation
needs the owner to connect the V3 USB cable; no wired probe has been run here.

Validation:78 relevant diagnostics/GUI checks and783 packaged-source checks pass.
Staged Arch/wheel, CLI and isolated GUI checks pass. Original input-remapper
operation was independently verified restored; no migration/autostart change or
host package installation occurred.

## V3 wired read-only route verified; mode capture prepared — 2026-11-11

The owner connected the V3 cable and authorized only descriptors and prepared
getters. `gillete.wired_probe --query-routes` completed with exit0 and private
report `evidence/v3-wired-read-20261111-01.local.json`. Discovery selected E7 by
USB ancestor/PID, with B4 still connected and E8 absent. All four interfaces
used hid-generic/usbhid; their79/159/61/22-byte descriptors matched the public
wired layouts. Interface00 completed all225 queries, with no setting opcode.
Interface03 was not tried after that success and remains unverified.

Before/after snapshots match: normal mode0000, firmware01010000, assigned/active
slot1,33 inventory IDs,100 records for the25 known controls across both layers
and active/stored views, and unchanged DPI/stages/polling. DPI stayed1600×1600;
ordinary polling readback was01. The eight extra inventory IDs, unassigned
banks, macro bodies and a raw flash image were not compared. This verifies the
getter route only, not a setter, polling cadence, persistence or wired inputs.

`gillete.wired_capture` now prepares an isolated180-second/4096-report driver-mode
proposal from that successful inspection. Preparation checks current sysfs
metadata without sending HID requests. A real proposal exists at
`evidence/v3-wired-capture-20261111-01.local`, with no run directory. No wired
mode change, capture, input grab, virtual keyboard or saved-state write has run.
New owner approval is required because the existing cable authorization is
explicitly read-only.

Run rechecks the complete snapshot before admitting a durable mode lease. The
separate transport guard permits only the proven getter shapes and journaled
driver/normal mode changes. Binding, macro, DPI, polling and profile setters
remain rejected; normal application E7 configuration/activation stays gated.
Capture reads only the selected mouse, suppresses pointer-only duplicates and
can stop on user confirmation, timeout, record limit or interruption. Retained
raw mouse frames can contain motion fields. The V2 and its remapper stay
available without a handoff.

Cleanup restores normal mode and compares the same known saved state. Recovery
can reopen fresh nodes after replug only with matching raw descriptors, firmware
and serial; a completed lease cannot change a later owner's driver mode. Other
state differences are reported and preserved, including externally changed DPI.
Tests exercise uncertain mode acknowledgments, stale snapshots, absent/invalid
journals, unrelated setters/getter shapes, record-limit cleanup, normal completion,
idempotent recovery, re-enumeration and wrong identity without recovery writes.
Diagnostics and research docs now show the passed live reads and the prepared,
unrun wired input experiment separately. No migration or host installation.

Validation: all1099 automated tests pass, including30 new wired capture cases.
The initial full run caught an obsolete GUI expectation for the previous wired
status label; it now checks the live getter evidence without enabling activation.
All813 packaged-source checks, staged Arch/wheel paths, isolated GUI and CLI
checks pass. Nothing was installed on the host. The retained live proposal was
revalidated against current USB metadata without opening HID or creating a run.

## V3 wired controls captured; isolated software acceptance implemented — 2026-11-11

The owner approved the three-minute wired mode/input capture and confirmed the
requested sequence. `evidence/v3-wired-capture-20261111-01.local/run` completed
with exit0. All 78 retained reports replay through the strict wired decoder:
all 25 controls have complete press/release or wheel pairs; ring+side12 and
left+side1 holds cross interfaces correctly, and no controls remain held.
Extra clicks/scrolls remain in the trace. Interface00 tilt bits20/40 and wheel
signs, interface01 vendor buttons and interface02 side usages agree with the
receiver decoder on the observed hid-generic binding. Receiver-only report IDs
are explicitly rejected by the new wired decoder.

The mode journal is normal-mode-restored. Before/after verification confirms
the same known active/stored descriptors, inventory, slot, firmware and saved
settings, including 1600×1600 DPI. Health records 331 exchanges/replies, zero
malformed reports and exactly two setting commands: enter and restore mode.
No binding, macro, DPI, polling or profile setter was admitted; no input grab
or virtual output was used. The V2 and input-remapper were untouched.

The full private trace and a 58-report excerpt independently replay to the same
control/combination coverage. The bundled excerpt contains original input bytes
with rebased times, public descriptors and provenance; private hardware identity,
device paths and saved assignments are excluded. This is physical wired input
evidence, not software HyperShift/key delivery or standalone write acceptance.

`gillete.wired_acceptance` implements the next isolated 50-tap software test.
The existing receiver controller/session/daemon accept an explicit adapter;
their defaults and normal E7 configuration gate remain unchanged. The wired
adapter requires successful capture/restoration proof, only the cable transport,
matching serial/firmware and the tested assigned slot. It reads only proven
getters, uses the strict wired decoder and an isolated mode-only transport.
That transport requires exactly one active owned journal for each mode setter
and rejects all saved-state setters even in driver mode. The daemon is bound
to its run's configuration and journal directory and cannot enable the V2.

After separate approval, the same guided window/source/Qt matcher can exercise
all 50 normal/HyperShift pairs, including trigger rotation. It takes mouse
input ownership and generates virtual markers, so the earlier capture approval
does not authorize running it. Cleanup verifies the 50 known stored descriptors,
slot, settings and firmware. Explicit recovery supports new enumeration with
matching raw descriptors, serial and firmware, restores owned mode alone and
reports/preserves unrelated changes. Ordinary wired activation, onboard writes
and lifecycle acceptance remain gated.

Read-only preparation completed at `evidence/v3-wired-controls-20261111-01.local`
with no run directory. Its fresh snapshot reports 3200 DPI/stage4, after the
capture cleanup verified 1600 DPI/stage3. The stage values, stored bindings,
firmware, serial and polling are otherwise unchanged. No cause is inferred;
no DPI setter was used. The owner was asked whether to keep 3200 or return to
1600 with the mouse buttons. Keep this actual snapshot intact; a changed DPI
requires a fresh proposal rather than replacing current settings. No wired
software test or normal application control has started.

Validation: all 1,126 automated tests pass, including 27 new wired acceptance
cases. Tests replay the physical trace through the real router/engine, verify
factory/adapter selection and reject stale settings before any subprocess.
They also cover missing controls/releases/combinations, invalid layouts and
identity/proof, unowned/ambiguous journals, forbidden setters, recovery after
replug, mismatched live firmware/serial, wrong config/state roots and preserving
external DPI changes. All existing receiver controller/session checks pass.
All 878 packaged-source checks, staged Arch/wheel paths, isolated GUI and CLI
checks pass. No host installation, migration or startup change occurred.

The owner returned the V3 to 1600 DPI and requested another read. Fresh getter-only
preparation at `evidence/v3-wired-controls-20261111-02.local` confirms 1600×1600,
stage3, normal mode and all 50 known stored descriptors. Its 50-tap proposal has
no run directory. The earlier 3200-DPI proposal remains intact as observed
history; use only the refreshed proposal for the next approved software test.
No DPI setter was used, and no live wired software control has started. Source
code is unchanged from the passing 1,126-test/878-packaged-check validation.
