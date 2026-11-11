# Modifier-stable virtual function keys

2026-11-10. Implemented and verified offline, without configuring the running
desktop or starting a service. On2026-11-11 the V3 receiver's complete50-tap
test additionally accepted actual Qt delivery for F13–F24 with base, Shift, Alt
and Shift+Alt, plus Ctrl/Ctrl+Alt on F13. Other live scenarios remain pending.
This supersedes the standard-option implementation for Gillete's virtual
output; it does not correct the physical mice's onboard output.

The old `fkeys:basic_13-24` option corrected base F23, but preserved the key's
extra level/type. Offline tests reproduced Shift+Super+F23 as XF86Assistant
and Control+Super+F24 as XF86TouchpadToggle even with that option. Those specific
failures are now regression cases against the real installed XKB library.

`function_keymap` compiles the current rules/model/layout/variant/options, or a
provided complete custom keymap. It uses a typed ctypes binding to the stable
libxkbcommon API, with explicit context/map/state ownership and string freeing.
No xkbcli executable, input device or system XKB-file write is required.
Compiler error callbacks reject partial results returned after an invalid
component was ignored, as well as null results. Requested layout count cannot
silently shrink. Source and serialized text have a1MiB admission limit.

The compiler appends explicit replacement F13–F24 definitions in every layout.
Each uses ONE_LEVEL, the desired Fn symbol and NoAction, preserves its original
repeat policy, and clears its real modifier-map entry. XKB's documented
replacement, type and modifier-map semantics support those operations.
[XKB format specification](https://xkbcommon.org/doc/current/keymap-text-format-v1-v2.html).
The compiler rejects a custom map whose function-key names do not correspond
to the Linux evdev codes emitted by uinput; it cannot certify the wrong keys.

It recompiles the result and verifies all256 core modifier masks, all12 keys
and every compiled layout. Every Fn must produce the expected symbol, consume
no modifier, and leave modifier/layout state unchanged on press/release. Layout
labels carry a unique ownership marker. Other regression tests compare letters,
number keys, modifier keys, media keys, F1/F12, variants and options across all
masks in US/German, US/Russian and Dvorak maps. A custom file test retains a
Greek letter mapping and removes a deliberately configured Fn modifier action.
Format2 custom maps with five groups are tested; production currently emits
format1 for interchange compatibility and fails unsupported configurations.

## Virtual-output lifecycle

Each `UInputOutput` receives a fresh UUID in its name. `KeyboardMap` accepts
only that owned-name form, discovers its exact compositor object, captures
RMLVO and the global custom-file source, and prepares the private map before
any physical input ownership. Relative custom-file paths are rejected because
the compositor's configuration-relative path cannot be inferred safely.

The file lives in a private0700 temporary directory with0600 permissions.
The exact unique virtual name receives `kb_file` and
`resolve_binds_by_sym=true`. Lua and the existing legacy keyword fallback are
supported. The compositor's actual `active_keymap` must equal one of the unique
compiled layout labels. Unchanged RMLVO strings alone do not prove file loading:
Hyprland may silently use an RMLVO fallback if a custom file cannot load.
[Pinned Hyprland loader](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/devices/IKeyboard.cpp#L61).

A watcher checks object address, RMLVO, active marker, generated-file fingerprint,
global custom-file choice and any inherited source-file fingerprint. Changed
or missing state stops the session through existing output release and mode
recovery. Switching between compiled layout groups retains valid markers;
changing the source configuration requires rebuilding on the next activation.

Shutdown releases generated keys, closes the uniquely named output, then
retires its file. Cleanup sends no inverse compositor setters. The name-keyed
runtime entry can remain in Hyprland until reload, but its device is gone and
the UUID name is never reused. This avoids guessing inherited settings or
restoring an effective value as a permanent override. A forced process kill
can leave a private temporary file; no future output uses that name or file.

The public API still cannot inspect per-device bind-policy explicitness or
atomically unset a field. The unique-name ownership model is deliberately
limited to outputs Gillete creates. It supplies no permission or implementation
for changing a physical Naga keyboard. See
[the physical-device research](native-keyboard-compatibility-research.md).

Remaining live acceptance: other modifier combinations and actual applications,
compositor shortcut behavior, layout switching, reload handling,
custom-file replacement and shutdown cleanup with the real virtual output.
Earlier F23 live results exercised the old standard-option path.
