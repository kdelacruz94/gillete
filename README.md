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

Requires Python 3.11+, PySide6, and python-evdev (already present on the target
CachyOS machine). From this checkout:

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
The macro editor supports recorded input, editable event rows, and comma-separated
chords such as `Alt+H, O, A` or `Ctrl+B, Alt+S`. Delays/press timing are editable.
Recording opens physical input devices only after Start and never grabs them;
another remapper's exclusive ownership may make its mouse events unavailable.

The shortcut examples are optional imports. Pin/Automatic selections persist
locally. The Software control tab starts the background service and explicitly
enables each mouse. Starting the service alone leaves both mice disabled.
The tray menu provides profile pins and Automatic for each mouse, enable/disable,
and stopping software actions. Closing the editor hides it when a system tray
is available; **Quit editor** exits the UI while the service can continue.
Ctrl+Alt+Pause stops generated actions while the service is active; an existing
Hyprland binding on that chord is preserved and prevents activation.

The service uses temporary driver mode and evdev ownership plus uinput output.
It restores normal mode on disable/shutdown. Program focus changes select local
profiles without writing onboard bindings. Suspend/disconnect/focus loss cancel
macros and turbo; ordinary unchanged mouse dragging survives a focus transition.
Do not enable two remappers for the same mouse. The service reports ownership
conflicts instead of stopping another application.

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

The Mouse memory tab reads assigned slots and previews every changed binding.
Only **Save to Mouse** writes those assignments. Software-only actions block the
save and are listed for review. Recovery journals live under
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
