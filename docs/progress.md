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
