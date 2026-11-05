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

Requires Python 3.11+, PySide6, python-evdev, python-gobject and GLib 2.84+
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

Double-click a normal or HyperShift cell to edit an assignment. Shared mappings
and per-mouse overrides keep the V3 ring-finger control distinct from the V2.
The control selector also exposes every button on the selected model; choose
Normal or HyperShift and click the physical control. In Program profiles,
**Choose running application…** fills a rule from an open game or program;
select **Save rules** to apply it. Title matching is optional.

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
Do not enable two remappers for the same mouse. The service reports ownership
conflicts instead of stopping another application.
If focus monitoring disconnects, new mapped input is blocked and normal mouse
mode is restored. Reconnection waits for monitoring to return; macros do not
resume automatically.

**Start with desktop** is a separate opt-in in the Startup tab. It creates an
[XDG autostart entry](https://specifications.freedesktop.org/autostart/latest/)
for Hyprland/UWSM, opening the tray and starting the service at the next login.
It preserves a conflicting existing entry instead of overwriting it. Plain
Hyprland sessions need an XDG autostart manager, or may launch
`gillete gui --background --start-service` from their own session startup.
Neither desktop startup nor mouse startup choices have been enabled during
development; enable them only at the agreed migration. Desktop launch arguments
follow the [Desktop Entry Exec rules](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).

On Hyprland, Gillete applies `fkeys:basic_13-24` and symbol-based shortcut
resolution only to its virtual output keyboard. This prevents standard XKB
media/touchpad aliases from changing F13–F24 mappings. It requires
`xkeyboard-config >= 2.43`, preserves other keyboard options, and restores its
option change when disabled. A compositor configuration change that removes the
correction stops the affected session; enable it again to recheck the setup.
This is a Linux software-output correction. Onboard F-key assignments still
depend on the receiving computer's keyboard configuration.

"Stored mouse assignment" refers to the actual saved binding, including existing
Synapse customizations. Unknown firmware actions stay intact in onboard previews
and recovery data. Software activation is blocked if a profile inherits an action
whose software behavior is not implemented; it is never replaced with a guessed
factory mapping. Several existing V2 firmware actions still need this work.
The mouse-memory view now identifies stored turbo parameters and macro
references, while marking unverified timing and unavailable macro content.
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
using the original profile actions; this does not add native firmware macro/turbo
support, which remains under investigation. Recovery journals live under
`$XDG_STATE_HOME/gillete/onboard` (normally `~/.local/state/gillete/onboard`).
Disable software control before direct mouse-memory operations. **Edit DPI and
polling…** opens the native settings editor after reading the active slot. It
supports 1–5 stages, a selected stage, separate or linked X/Y DPI, and receiver
rates of 125/500/1000 Hz. Review the before/after values before saving. Current
DPI and the stage table are preserved separately, including existing Synapse
values that differ. Settings saves reject stale previews and keep recovery
journals for the entire affected group. Physical settings acceptance is ongoing.
The same read shows reported battery level and firmware when those queries
succeed; unavailable values are identified explicitly.

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
or `--sections dpi` narrows the queries. `--include-macro-data` additionally
captures bounded raw bytes for enumerated nonzero IDs. Reports contain device
identity and, if requested, macro contents; files are private and summaries omit
both. A rejected query stops that section. Readback alone establishes neither
native macro playback nor temporary DPI writes; this diagnostic enables no new
application capability automatically.

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
