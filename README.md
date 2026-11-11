# Gillete

Native Linux profiles, macros, and onboard programming for the Razer Naga V2
HyperSpeed and Naga V3 Pro. Built for CachyOS/Hyprland.

**Under development; hardware acceptance is ongoing.** The native editor,
onboard preview/save/recovery flow, user service and input router are implemented.
Both receivers passed side-12 onboard persistence/HyperShift tests and complete
physical-control identification (21 V2 / 25 V3 controls). The first V3 live test
passed chords, toggle turbo and focus cancellation; an F23 desktop-keymap issue
was corrected and physically revalidated on the V3. Full service acceptance,
wired operation, device-settings acceptance and migration remain unfinished. Keep your
input-remapper configuration for rollback.

## Run the editor

Requires Python 3.11+, PySide6, python-evdev, python-gobject, libxkbcommon1.11+
and GLib 2.84+
(already present on the target CachyOS machine). From this checkout:

```bash
PYTHONPATH=src python -m gillete.cli gui
```

The development build is also installed on the target machine as `gillete gui`
and the **Gillete** desktop launcher, using a Python 3.14 environment with the
system PySide6/evdev packages. A scoped udev rule grants the active desktop user
access to only the three supported Naga USB product IDs.

The editor opens without grabbing a device or changing mouse settings. Local
profiles save to `$XDG_CONFIG_HOME/gillete/profiles.json` or
`~/.config/gillete/profiles.json`. Use `--config /path/to/profiles.json` before
the subcommand to isolate experiments.

**Devices & diagnostics** separates connection/service checks, per-node
permissions and feature-validation evidence. Select the receiver or cable by
model, transport and USB port. Configuration queries require both read and write
access to their hidraw node; software input requires readable input nodes and a
writable `/dev/uinput`. Readable input does not prove that another remapper has
released its grab. The panel reports Gillete's existing ownership/error state
without testing ownership by taking control of the mouse.

Use **Refresh connection checks** after reconnecting or changing permissions.
Service status updates while the editor is open and identifies its USB route,
so an active receiver is not presented as control of an attached cable. Feature
validation distinguishes implemented behavior, partial live tests and unfinished
work. Those results describe development hardware; they do not certify the
connected unit or its current mappings. Diagnostics opens no mouse/input nodes,
writes no settings, starts no service and never changes input-remapper.

Double-click a normal or HyperShift cell to edit an assignment. Shared mappings
and per-mouse overrides keep the V3 ring-finger control distinct from the V2.
Each cell identifies its source: shared, a mouse-specific override, inherited
Normal, or mouse memory. Editing **Shared mappings** opens the shared value even
when an override is active; the dialog explains which value currently applies.
Right-click to remove an assignment in the selected scope and reveal the inherited
value. Configured V3-only controls remain listed in the V2 view, including separate
standalone choices. Double-click those rows, or use **Show V3-only assignments**,
to switch to the V3 without moving the mapping onto a V2 button.
The control selector also exposes every button on the selected model; choose
Normal or HyperShift and click the physical control. In Program profiles,
**Choose running application…** fills a rule from an open game or program;
select **Save rules** to apply it. Title matching is optional.

**Duplicate** keeps the selected profile's mappings, standalone choices and saved
program rules. Buttons that select that same profile select the copy instead;
buttons for other profiles keep their targets. Copied rules start disabled.
In **Program profiles**, toggle **Enabled** and select **Save rules** to activate
or suspend a rule without deleting it. Existing rules remain enabled when reading
an older configuration.

**Export** saves the selected profile, every profile its buttons can switch to,
and their saved program rules in one portable JSON bundle. Save pending rule edits
first. **Import** reviews the profiles and rules before saving; existing profiles
are preserved and conflicting IDs/names receive distinct copies. Links between
imported profiles follow those copies, including self-switch buttons. Imported
rules start disabled unless **Keep enabled program rules active** is selected;
rules disabled in the export remain disabled. Existing rules win equal-priority
ties. Defaults, manual pins and startup choices stay as they were.
Older single-profile exports still import. A legacy link to another local profile
is shown in the review; missing linked profiles require a new bundle export.
Profile bundles contain local configuration, not a backup of mouse memory.

Unused profiles may remain unfinished while software control runs. In Automatic
mode, Gillete checks the selected mouse's default, all enabled program rules for
that mouse, and every profile their effective buttons can select on either
layer. A manual pin uses the pinned profile and its button-linked profiles;
choosing Automatic checks the automatic profiles again before switching.
Disabled rules do not activate a profile, but a button link still can.
Unknown stored actions and unusable HyperShift triggers block activation of any
of these selectable profiles. Editing an unrelated draft does not stop the
current mapping. Disabling the active program rule selects the applicable
fallback and cancels its macros if the selected profile changes.

DPI and native-device assignments show their software prerequisites in the
mapping cells, control selector and action editor. Native wheel-mode and
onboard-slot actions are V3-only; shared profiles can provide a different V2
override. A V3 with one assigned onboard slot has nothing to cycle. Cycling
multiple onboard slots from the service is still unimplemented; use **Switch
profile** for Linux profiles or choose another software mapping. DPI-stage
buttons need valid DPI/stage reads, and native wheel cycling needs a recognized
wheel-mode read. The next explicit V3 mouse read includes that optional query.
These checks apply before software input ownership, live pins and configuration
reloads. Inactive drafts remain editable, and the checks follow effective
overrides and HyperShift inheritance. Readable prerequisites do not establish
physical setter behavior; hardware acceptance remains pending.

The mapping page shows the HyperShift trigger for the selected mouse. An inherited
trigger stays **unverified** until you read its active slot in Mouse memory &
settings; the label then identifies the trigger from that read. A profile with
custom shifted mappings and no usable trigger is rejected before software control
takes ownership. To change a trigger, edit its **Normal** assignment. It stays
available on both layers. Scroll up/down can toggle software HyperShift; use a
button that can stay pressed for held HyperShift. V3-only shifted controls do not
require a trigger on the V2 unless that profile also assigns shifted V2 controls.

The macro editor supports recorded input, editable event rows, and comma-separated
chords such as `Alt+H, O, A` or `Ctrl+B, Alt+S`. Set **Key hold** and **Between
chords** before choosing **Build steps**. **Replace delays…** changes all existing
delay rows without inserting pauses between simultaneous chord members.
Recording opens physical input devices only after Start and never grabs them;
another remapper's exclusive ownership may make its mouse events unavailable.
Choose **Recorded timing** or **Fixed delay between events** before starting.
Press **F12** to finish without capturing the stop-button click. Keys still held
at that point are released in the recorded macro, with their final hold timing
preserved. A dropped or disconnected input ends the recording with a visible
error; **Start recording** then starts a fresh capture. Pointer movement is
optional and off by default; virtual inputs are excluded.

**Launch program** supports **Choose application…** for installed desktop apps,
or **Browse…** for an executable/script with explicit arguments. The app picker
uses the [system desktop registry](https://docs.gtk.org/gio/type_func.AppInfo.get_all.html)
and saves the application ID, so it can resolve the installed entry when used.
GIO handles desktop launch settings, including working directory and D-Bus
activation. Command arguments remain literal; Gillete does not interpret them
as a shell script. Failed launches appear in Software control without disabling
mouse remapping. Launch actions require the Linux service.

The shortcut examples are optional imports. Pin/Automatic selections persist
locally. The Software control tab starts the background service and explicitly
enables each mouse. Both mice start disabled by default. The Startup tab lets
you explicitly select which mice to enable on future service starts. It waits
for focus and suspend monitoring, then checks the emergency shortcut and input
ownership before activation. Saving startup choices does not change current
software control. Existing configurations retain the disabled default.
The tray menu provides profile pins and Automatic for each mouse, enable/disable,
and stopping software actions. Closing the editor hides it when a system tray
is available; **Quit editor** exits the UI while the service can continue.
Opening Gillete again brings back the existing editor for that profile file.
Ctrl+Alt+Pause stops generated actions while the service is active; an existing
Hyprland binding on that chord is preserved and prevents activation.

The service uses temporary driver mode and evdev ownership plus uinput output.
It restores normal mode on disable/shutdown. Program focus changes select local
profiles without writing onboard bindings. Suspend/disconnect/focus loss cancel
macros and turbo; ordinary unchanged mouse dragging survives a focus transition.
Buffered presses from before a cancellation are suppressed until release and a
fresh press, including reports still waiting in Linux's raw-input buffer.
Delayed button commands are discarded if their profile/focus context changed.
Generated keys are released before shutdown waits for an in-flight USB operation;
that operation completes before the transport closes and normal mode is restored.
Do not enable two remappers for the same mouse. The service reports ownership
conflicts instead of stopping another application.
If focus monitoring disconnects, new mapped input is blocked and normal mouse
mode is restored. Reconnection waits for monitoring to return; macros do not
resume automatically.
When a mouse disappears or its reply times out, the service waits five seconds
before trying a new session. Software control shows the retry countdown or the
reason it is waiting. Reconnection requires one transport for that model and
working desktop monitoring; any retained mode lease is recovered before new
input ownership. Mapping, permission, ownership and recovery errors stop automatic
activation and remain visible until addressed. A device retry never resends an
uncertain settings write or restarts an old macro.

**Start with desktop** is a separate opt-in in the Startup tab. It creates an
[XDG autostart entry](https://specifications.freedesktop.org/autostart/latest/)
for Hyprland/UWSM, opening the tray and starting the service at the next login.
It preserves a conflicting existing entry instead of overwriting it. Plain
Hyprland sessions need an XDG autostart manager, or may launch
`gillete gui --background --start-service` from their own session startup.
Neither desktop startup nor mouse startup choices have been enabled during
development; enable them only at the agreed migration. Desktop launch arguments
follow the [Desktop Entry Exec rules](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).

On Hyprland, Gillete compiles a complete keymap for its uniquely named virtual
output. F13–F24 keep their function-key symbols with all256 core modifier states;
modifiers remain available to application shortcuts. This also fixes the higher
level Shift+Super+F23 and Control+Super+F24 aliases left by the standard option.
Layouts, variants, other options and regular keys are preserved. The private
file is loaded only for Gillete's output, with symbol-based compositor shortcuts.
Input ownership waits until Hyprland reports the compiled map's unique layout
marker. Reloads, layout/option changes, replaced outputs or changed files stop
the affected software session. Disabling closes the output before removing its
private file, without changing global or physical-keyboard settings.

An inherited custom `kb_file` must use an absolute path (a leading `~` is
supported); invalid or unsupported maps block activation instead of falling
back to US. The integration and complete modifier matrix pass offline tests;
desktop acceptance of this new path remains pending. See
[virtual function-key maps](docs/virtual-function-keymap.md).
Onboard F-key assignments still depend on the receiving computer's keyboard
configuration; the [physical-keyboard research](docs/native-keyboard-compatibility-research.md)
records the limits of automatic setup for the real mice.

"Stored mouse assignment" refers to the actual saved binding, including existing
Synapse customizations. Unknown firmware actions stay intact in onboard previews
and recovery data. Software activation is blocked if a selectable profile inherits
an action whose software behavior is not implemented; it is never replaced with a guessed
factory mapping. Several existing V2 firmware actions still need this work.
The mouse-memory view now identifies stored turbo parameters and macro
references, while marking unverified timing and unavailable macro content.
On the V3 receiver with firmware1.1, **Read mouse** also retrieves supported
once-only, single-key keyboard macro bodies. It requires the reference to be in
the catalog, reads the complete bytes twice and rechecks the referring bindings.
**Keep stored** can then reproduce that exact key/delay sequence through the
Linux service; the virtual keyboard handles its base function-key mapping.
Activation rechecks bodies required by selectable profiles before input ownership.
Explicit host overrides do not depend on unused native bodies. Missing, changed,
multi-key, mouse, held/toggle and repeated native macros remain unresolved.
This integration is tested in simulation; its combined live acceptance is pending.
It does not upload, alter or delete any macro, and an inspection snapshot remains
insufficient for a complete native macro backup.
The [remaining protocol research](docs/remaining-protocol-research.md) records
the REA capture analysis and the evidence still needed for those actions and
the V3 wired transport.

**Standalone mappings…** lets each named profile keep separate alternatives for
each mouse and layer. For example, keep `Ctrl+K, M` as the Linux macro on side12,
then choose F24 as that button's standalone alternative. **Save choices locally**
stores the preference in the profile, including import/export; it does not write
mouse memory. **Follow profile** removes an alternative. **Keep stored** explicitly
preserves that layer's existing mouse assignment, including an unknown Synapse
function. Unassigned HyperShift alternatives inherit the normal alternative unless
the Linux profile already has an explicit shifted assignment.

The Mouse memory tab reads assigned slots and previews every button layer with
the Linux action, current mouse assignment and proposed saved assignment side by
side. Only **Save to Mouse** writes those assignments. Software-only actions still
block saving until you choose supported alternatives. The Linux service continues
using the original profile actions. For supported native macros, read the V3
receiver and select **Review native macro profile…**, then explicitly choose
**Save to Mouse**. The current acceptance gate covers firmware 1.1, active
slot1 as the sole assigned slot, and single-key timed macros played once on
normal/HyperShift layers. Multiple buttons can share their macro data.
Native multi-key sequences, repetition/turbo, mouse macros, V2 macro storage
and wired V3 remain gated; those actions continue to work through the Linux
service. Native F13–F23 desktop interpretation is also gated pending scoped
keyboard-map validation; the Linux service's virtual keyboard already has its
function-key correction. These are remaining implementation/acceptance requirements.

Native saves verify macro data before assigning references and preserve full
transaction originals. **Restore from recovery journal…** accepts the native
save's `profile.json`, restores affected original mappings and removes only
verified unreferenced new objects. Later unrelated DPI/button edits are preserved;
shared or unmatched macro objects are retained and reported. Missing/changed
original dependencies or edits to affected mappings block unsafe restoration.
Byte-identical objects from the same named profile
are reused after metadata/data verification; unchanged saves require no new
objects. Changed objects are retained for undo, and the preview shows new/reused
counts and free-space/slot limits. Explicit pruning of obsolete managed objects
remains pending. Assignment-only slot backups refuse nonzero native
macro references because they cannot restore the referenced data; retain the
full native recovery journal and exported Linux profile instead.
Recovery journals live under
`$XDG_STATE_HOME/gillete/onboard` (normally `~/.local/state/gillete/onboard`).
Disable software control for the selected mouse before direct mouse-memory
operations. Native macro review/save/undo queries the service's actual ownership
state: the selected model must have no requested, active, stopping or pending
startup session. An idle background service and software control of the other
mouse can remain running. Unknown or unavailable service status blocks the
operation; the app never disables a mouse or stops a service automatically.
Transport exclusivity and normal-mode checks still guard the subsequent access.
**Edit DPI and
polling…** opens the native settings editor after reading the active slot. It
supports 1–5 stages, a selected stage, separate or linked X/Y DPI, and receiver
rates of 125/500/1000 Hz. Review the before/after values before saving. Current
DPI and the stage table are preserved separately, including existing Synapse
values that differ. Settings saves reject stale previews and keep recovery
journals for the entire affected group. Physical settings acceptance is ongoing.
The same read shows reported battery level and firmware when those queries
succeed; unavailable values are identified explicitly.

**Verify a saved binding journal after restart…** opens a read-only, user-paced
check for either receiver. Select a completed **Save to Mouse** binding journal
and stop software control first. After the baseline is read, the dialog asks
you to power-cycle the mouse while leaving the receiver connected. Confirm
when it is awake. It then asks you to unplug the receiver, waits until its
absence is observed, and lets you check again after reconnecting to the same
USB port. A new USB enumeration, the same hardware identity and firmware,
unchanged assigned slots, and matching stored/active bindings are required.

The check writes a separate private receipt under the recovery directory and
leaves the save journal intact. Changed or restored journals, stale bindings,
and active-slot mismatches cannot pass. Each read has a bounded query/time
budget; the dialog has a five-minute overall limit and waits for an in-flight
read before closing. A transient timeout after preparation allows an explicit
retry. Closing the check leaves your saved assignments in place.
The receipt distinguishes a reported mouse power cycle from observed receiver
disconnection/re-enumeration. It verifies readback of the recorded bindings;
physical button output, settings persistence and broader model acceptance
remain separate tests. This workflow has been tested in simulation; the user's
receiver-replug acceptance is still pending.

## Diagnostics and tests

```bash
PYTHONPATH=src python -m gillete.cli devices
PYTHONPATH=src python -m gillete.cli validate
PYTHONPATH=src python -m gillete.cli example herdr
python -m pytest -q
```

The opt-in `.venv/bin/python tools/diagnose_fkeys.py --all-function-keys`
opens a short-lived Wayland window and checks actual F13–F24 delivery through
the engine and uinput. It requires focus, emits only into its own active window,
and never opens a physical mouse. The original F23 regression can be reproduced
with `--raw --uncorrected`; do not use that mode if TouchpadOff is bound to a
desktop action.

`example` uses a simulated output sink; it does not type into another program.
The explicit `snapshot --product 00b4` or `snapshot --product 00e8` command
requires hidraw access and reads firmware/mode/battery and assignment descriptors.
It submits read-query feature reports, never setting commands. Snapshot output
contains device identity and should be kept private. Running the entire GUI as
root is not required or recommended.

The development software-test harness supports both receivers, with a read-only
preview before live activation:

```bash
python -m gillete.guided_service prepare --product 00b4 --directory evidence/v2-software-test1.local
# Review the printed temporary mappings before running the test.
python -m gillete.guided_service run --directory evidence/v2-software-test1.local --seconds 180
```

Use `00e8` for V3 and a new directory for each attempt. This test changes live
mouse behavior and generates keys. Its private profile masks undecoded firmware
actions and device-setting actions explicitly; the preview lists the effect
inside and outside the test window. The current V2 plan also disables the four
old MapleStory macros retired by the owner. Normal decoding remains strict.
The test window shows model-specific instructions and starts its countdown only
when the service is active with that window's profile. Closing it stops the test;
Ctrl+Alt+Pause stops generated actions. Cleanup verifies normal mode, saved
bindings, profile selection and saved settings. Recovery journals remain under
the test directory's `run/state/gillete/onboard/` if verification fails.

An opt-in firmware diagnostic prepares private evidence for unresolved macro
storage and DPI selectors, without changing mappings or settings:

```bash
python -m gillete.firmware_probe --product 00b4 --output evidence/v2-firmware-read1.local.json
```

Use a new report path and an awake mouse in normal mode. Product `00e8` selects
the V3 receiver; wired probing remains separate and unverified. `--sections macros`
or `--sections dpi` narrows the queries. `--include-macro-data` captures bounded
raw bytes plus an inert interpretation of recognized key, mouse, wheel, delay and
cursor records beside the raw bytes. Unknown or incomplete records retain
their unparsed remainder; held inputs are reported without invented releases.
Only nonzero IDs enumerated from the catalog are read, within the source-backed
15-bit ID and existing byte/count limits. This does not create playable actions.
Reports contain device
identity and, if requested, macro contents; files are private and summaries omit
both. A rejected query stops that section. Readback alone establishes neither
native macro playback nor temporary DPI writes; this diagnostic enables no new
application capability automatically.

A separate development experiment can test DPI getter independence before
per-program hardware sensitivity is implemented:

For a user-paced sensitivity/power-cycle observation, `gillete.dpi_sensor_probe`
provides read-only `prepare` followed by explicit `run`. Preparation can select
an exact lower DPI with `--dpi` (prepare-only); otherwise it uses roughly half
the original value. The run waits up to three minutes for reported observations
in its private run directory, then verifies protected state and restores the
original settings. Timeout/cancellation also attempts restoration, with a
retained journal recoverable through `gillete.dpi_probe recover`. A reported
power cycle is labeled as user-reported, not observed USB removal. No automatic
hardware capability is enabled by these experiments.

`gillete.dpi_replug_probe` provides a separate receiver-retention experiment.
Its read-only `prepare` records the receiver's port and USB enumeration address
as well as the complete original mouse state. Explicit `run` writes the
prepared lower DPI, closes the descriptor and waits up to three minutes for
observed USB removal and a new enumeration address on that same port. It then
opens a fresh transport, reads protected state and restores the original values.
USB enumeration alone does not mean the mouse radio can answer yet. Reconnect
also waits for current read/write access to the new configuration HID node,
allowing udev/seat permissions to finish before opening it. This wait does not
change permissions or treat an inaccessible existing node as USB removal.
Reconnect
and restoration preflight retry only transient getter failures using fresh
transports, with a per-phase 2048-read allowance shared across attempts, at most 16 attempts and a
45-second limit checked between attempts. Identity/state errors stop the test;
setter failures never enter that retry loop.
If the receiver remains absent at timeout, restoration is unverified and the
journal is retained for `gillete.dpi_probe recover` after reconnecting it.

`gillete.dpi_driver_probe` isolates DPI validation in temporary driver mode.
Read-only preparation retains originals; explicit run journals both mode and
settings, enters driver mode, applies the prepared lower DPI and waits up to
three minutes for a movement-only observation. Use another mouse for clicks.
It restores normal mode before repairing/verifying original settings and
bindings. Recovery must use this module's `recover --directory` command so
the mode journal is restored before the DPI journal. This test neither grabs
input nor starts software remapping, and does not automatically enable DPI
switching in the application.

```bash
python -m gillete.dpi_probe prepare --product 00b4 --directory evidence/v2-dpi-selector1.local
# Review the exact proposed DPI change and original saved settings first.
python -m gillete.dpi_probe run --directory evidence/v2-dpi-selector1.local --hold-seconds 3
# Only if the experiment retains an unresolved recovery journal:
python -m gillete.dpi_probe recover --journal evidence/v2-dpi-selector1.local/run/journal.json
```

`prepare` is read only. `run` briefly changes DPI through candidate selector zero
and restores it; recovery may also restore original saved DPI/stages/polling if
their readback changed. Use a new private directory and an awake mouse in normal
mode, with software control disabled. Both receivers are supported by this
experiment; wired operation remains gated. All known controls in the active
mirror and every assigned slot are checked, including opaque Synapse bindings.
No binding, profile-selection or mode setter is used. Interrupting the experiment
requests cleanup; disconnected or unverifiable restoration retains its journal.

The hold is limited to 0–10 seconds, with a separate query/time budget checked
between device operations; restoration runs even after that budget expires.
Kernel I/O itself can exceed the deadline. A successful result establishes only
the observed getter separation and restoration. Coupled getters do not prove a
permanent write; separated getters do not prove sensor behavior or persistence.
Physical movement, power-cycle/receiver-replug checks and driver-mode validation
are still required before enabling automatic profile DPI. This tool neither
enables that feature nor substitutes software pointer scaling. Physical execution
of this experiment remains deferred during the current development session.

V3 wired inspection has its own read-only diagnostic:

```bash
# Read descriptors and driver associations from sysfs; no HID queries.
python -m gillete.wired_probe --output evidence/v3-wired-descriptors1.local.json
# Also test the two candidate configuration routes with getter requests.
python -m gillete.wired_probe --query-routes --output evidence/v3-wired-reads1.local.json
```

Use a new report path each time. The second command requires an awake V3 on its
USB cable in normal mode. Its receiver may stay attached: the cable is selected
by product ID and USB ancestry. The tool records all four descriptors, hashes,
report sizes and bound drivers. It checks device-node identity around queries
and tries interface03 only if the interface00 bootstrap fails. A working route
is checked for firmware, normal mode, profile inventory, active/stored bindings
and settings. Reports include private hardware identity and raw assignments.
Queries are bounded to 256 requests/120 seconds per route between kernel calls.

No input is captured, and no mode, setting, profile or binding setter is admitted.
A successful report identifies a read-only route; it does not enable wired
remapping or saving. Wired physical-control capture and write/persistence
acceptance remain separate requirements. The bundled descriptor fixtures and
firmware reply are public contributor evidence, not measurements of your mouse.

Service CLI commands:

```bash
gillete daemon
gillete control status
gillete control enable --model v3
gillete control stop-actions
gillete control disable --model v3
gillete control shutdown
```

Use `gillete recover --product 00e8 /path/to/journal.json` for an explicit
identity-checked recovery after an interrupted binding, mode or supported
device-setting transaction. Retain the journal until recovery is verified.

Build and check distributable artifacts with:

```bash
python tools/build_arch.py
python tools/check_package.py
```

The builder requires `uv` and `makepkg`, isolates Python build dependencies,
and creates a wheel, source archive and Arch package under `dist/`. The package
has passed staged launcher/GUI checks and the wheel has passed a separate
environment installation. The checks do not install anything on the host.
The development launcher remains the installed version during acceptance.
No service or input-remapper migration is automatically enabled by packaging.

See the [approved specification](docs/specification.md),
[feasibility and hardware evidence](docs/feasibility.md), and
[reuse investigation](docs/reuse-investigation.md).
