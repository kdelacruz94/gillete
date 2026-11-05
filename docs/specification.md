# Gillete implementation specification

Status: approved for implementation after three interview rounds. The source
tree now contains an initial editor and tested macro/profile core; full hardware
and service integration is not yet complete.

## Product and supported hardware

Build a native CachyOS application with a Qt desktop interface, tray menu, and
Linux background service. Target Hyprland on Wayland first. The GUI may close
while the service continues serving program profiles and software actions.

Required devices and transports:

- Razer Naga V2 HyperSpeed, 2.4 GHz receiver (`1532:00b4`).
- Razer Naga V3 Pro, 2.4 GHz receiver (`1532:00e8`) and USB wired (`1532:00e7`).
- The 12-button side plate only. Bluetooth and 6/2-button plates are deferred.
- RGB control/synchronization is outside the requested scope.

Every electronic control must be independently inventoried and remappable:
the 12 side buttons, left/right/middle click, wheel tilt and scroll directions,
DPI/top controls, and the V3 ring-finger and underside profile controls.
Capabilities differ by model; do not invent a V2 counterpart to a V3-only button.
Investigate any unexposed control before classifying it as a hardware limitation.
Purely mechanical controls, if any, cannot be promised programmable without
evidence of an electronic interface.

## Profile model

A named profile contains common mappings, per-device overrides, normal and
HyperShift layers, sensitivity settings, and program matching rules. Common
controls have semantic names such as `side_1`, `wheel_tilt_left`, and
`left_click`, independent of USB IDs and Linux event codes. Model-specific
controls such as `ring_finger` retain their own identity.

A V3-only assignment remains visible as V3-only when viewing that profile for
the V2. It must not be silently transferred onto an unrelated V2 control.
Users can select a different HyperShift activation button per device while
sharing the shifted actions. The editor identifies an unreachable shifted
layer if the selected device has no assigned activation button.

Profiles support create, rename, duplicate, delete, import, and export. Changes
save locally; local saving is distinct from writing onboard memory. Both mice
have independent default profiles and manual selections, including when both
are connected. Identify physical devices separately from their transports;
ambiguous identity must not pick a backup or receiver arbitrarily.

Program rules select profiles on focus. Provide a window picker and meaningful
application identity for native Wayland and XWayland/Proton windows. Matching
must distinguish games that share a launcher/process name. Permit explicit
priority where rules overlap; unmatched applications select the device default.

Accepted default: a manual profile selection remains pinned until the
user chooses Automatic. The tray and GUI show whether selection is automatic
or manually pinned. App rules and the pin persist across service restarts.

## Actions and HyperShift

Required assignments: keyboard keys and modifier chords, mouse buttons, scroll,
media keys, disabled controls, DPI adjustments, profile changes, HyperShift,
macros, turbo/repeat, and program launches. Program launching supports a desktop
application or an executable/script with an explicit argument list; window
titles and profile names are never interpreted as shell commands.

HyperShift supports hold-to-activate and optional toggle. Prefer verified
firmware execution for onboard-compatible assignments; show software-only
status when the service implements an action. Unassigned shifted controls
inherit their normal mappings. Releasing the shift trigger returns to normal
for subsequent presses without losing the matching release of already-held
outputs. An activation control remains usable to exit its layer.

## Macro recorder, editor, and turbo

Macros record keyboard presses/releases, mouse clicks and wheel events, and
timing after an explicit Record action. The editor can insert, delete, reorder,
and change events/delays. Support recorded timing and fixed delays. Recording
ends visibly and has a keyboard stop mechanism.

Playback supports once, an explicit repeat count, while the trigger is held,
and toggle-to-repeat. Turbo has an adjustable rate and hold/toggle behavior.
Users can launch programs from normal or shifted bindings.

Cancel active macros/turbo on leaving the originating program, profile changes,
suspend, disconnect, and emergency stop. Release outputs owned by the canceled
action even during a delay; no automatic resume on return. A fresh physical
press is required. Synthetic input must not recursively trigger the recorder or
remapper. Concurrent actions must not release one another's held modifiers.

Pointer-movement recording is a nice-to-have, explicitly deprioritized relative
to reliable timed keys/chords and toggled turbo. It is off by default.
If enabled, record relative movement; do not promise pixel-identical
playback across application acceleration, DPI, or display changes.

## Onboard storage and device controls

Save to Mouse is explicit. Present the chosen device/bank, supported assignments,
and actions that require the service before writing. Never report an unsupported
macro, toggle, or launch as stored successfully. The user can choose an explicit
standalone mapping for a software-only action; no silent substitution.

Back up the device's original bindings/settings with sufficient identity and
format metadata to restore them. Preserve unknown bindings and untargeted banks.
The user confirmed the V2 was customized using Synapse on Windows: its current
contents are not factory defaults. "Original" always means the captured current
state, never a generic reset. Preserve these customizations during onboarding.
Journal interrupted changes and read back both stored state and active state
where supported. Report partial failure accurately and retain recovery data.
Verification after power cycling and receiver reconnection is required before
calling a model's persistence support complete.

Expose the hardware's verified bank/slot capacity; do not mistake an active
mirror for an extra stored profile. The V3's advertised onboard slots and
profile button need independent protocol and physical verification.

Automatic program switching must not write permanent storage. Use proven
temporary device assignments where possible or explicit software execution.
Do not silently equate temporary assignments with permanent saves. Arbitrary
existing onboard outputs may obscure physical button identities; resolving
that is a backend requirement, not grounds to omit controls.

Provide DPI stages and polling-rate controls with device-specific limits.
Display connection and battery information when available. Unsupported device
features remain visibly unavailable rather than displaying invented state.

## Interface and implementation boundaries

Proposed engineering approach: Python/PySide6 native desktop UI, a separate
user-session service, typed profile/action data, and isolated hardware backends.
Keep protocol encoders, input state transitions, macro scheduling, and profile
resolution testable without physical devices or a running desktop.

The UI has device selection/status, a visual control selector with normal and
HyperShift editing, profile/application rules, macro recording/editing, device
settings, and an explicit onboard save/restore view. The tray exposes current
profile, Automatic/manual mode, and stopping software actions. Add a diagnostic
view identifying the exact model/transport, permission or ownership conflicts,
and actual verified capabilities.

Use a single serialized hardware transport owner per physical device. The
service processes only the selected mice for remapping; a keyboard is involved
only in explicitly enabled recording/shortcut functions. Handle multi-interface
devices, key releases, scroll frames, reconnect, and sleep/resume. Preserve
unmapped pointer movement and standard mouse behavior.

Protocol/source reuse decisions are documented separately. REA is available
for artifact or trace investigation, especially unresolved V3 onboard behavior.
Use a Windows VM and Synapse captures if needed; runtime Windows dependence is
not an acceptable final design.

## Coexistence, delivery, and acceptance

Keep the current input-remapper setup in place during development. Do not
silently grab its devices, change its presets, stop its service, or replace the
OpenRazer driver to make a prototype appear functional. Controlled hardware
tests need explicit, reversible ownership transitions with restoration.

Deliver reproducible CachyOS packaging and launch instructions, scoped device
permissions, service startup/shutdown, diagnostics, import/export, and rollback.
The GUI and service must not require running the entire application as root.
Autostart and migration are enabled after product verification and the agreed
cutover; preserve existing configurations. Unrelated devices remain untouched.

Completion requires automated protocol/state-machine/error-path tests plus
physical verification on both actual mice, covering every required control and
both layers, macro playback/cancellation, application matching and manual
override, device disconnect/reconnect, suspend/resume, and onboard readback and
power-cycle persistence. Unit tests or upstream reports alone do not establish
working hardware support. Any remaining firmware uncertainty is unfinished
work until investigated and accurately bounded with the user.

## Final accepted examples and priorities

The user approved implementation and persistent manual pins. Required examples:

- Excel: Alt+H, then O, then A.
- VS Code: Ctrl+K, then M.
- Herdr: Ctrl+B, then Alt+S.
- WoW: toggle repeated presses of 1; a second trigger press stops repetition.

Each comma separates sequential chords; modifiers must not accidentally remain
held into the following chord. Delays and press durations are editable. These
examples are offered for explicit import, not automatically activated. The
user's actual application keymaps remain authoritative.
