# Physical Naga keyboard compatibility: Hyprland 0.57.2

Research date: 2026-11-10. Scope: first-party source inspection, read-only
`hyprctl version`, `hyprctl -j devices/getoption`, sysfs input metadata, installed
XKB files, and offline keymap compilation. **No live correction was tested.**
No device writes, settings changes, keyboard capture/injection, service operations,
GUI operations, or mouse configuration changes were performed. The combined
asynchronous hardware test remains awaiting user readiness; this research does
not advance that test. Only this repository document was edited.

## Decision for the implementation parent

Hyprland can apply `kb_options` and `resolve_binds_by_sym` to an **exact current
compositor name**, but the pinned version does not provide enough public IPC to
make an arbitrary physical-device correction both identity-safe and exactly
reversible. Do not simply relax `KeyboardMap`'s virtual-device prefix check.

A supported configuration expression, once identity and ownership have been
established independently, is:

```lua
hl.device({
    name = "razer-naga-v3-pro-keyboard", -- example from this session, not a model selector
    kb_options = "fkeys:basic_13-24",   -- merge with known existing options
    resolve_binds_by_sym = true,
})
```

This expresses the desired **base-level** correction; it is not a recommended
live command to execute now. Preserve other options, and require a known policy
for restoring both fields. A name-only runtime rule can outlive removal of the
original hardware and affect another device that receives its name. There is no
public address selector or public per-field unset in the inspected implementation.
For ambiguous physical names, stop before applying: neither USB enumeration order
nor the suffix is identity proof. For inherited settings, restoring their old
values creates overrides rather than restoring inheritance. These constraints
block a claim of fully automatic, session-only physical correction with the
existing public interfaces. [H1–H7 below]

## Exact source revisions

All code findings below refer to these resolved revisions, not floating `main`:

- Hyprland `v0.57.2`, **`11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947`**, confirmed
  by this host's `hyprctl version` (clean build). [Official revision](https://github.com/hyprwm/Hyprland/commit/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947).
- Aquamarine `v0.16.0`, **`b77d67648336223a6c8fb88844ae316e7b72b574`**, resolved
  from its official tag. Host reports Aquamarine 0.16.0; that version string does
  not independently prove the installed library has no distribution patches.
  [Official tag resolution](https://api.github.com/repos/hyprwm/aquamarine/git/ref/tags/v0.16.0).
- xkeyboard-config `xkeyboard-config-2.49`, **`2ec770a0085bf776de749e185ca40e50213fb21f`**.
  Host package: `xkeyboard-config 2.49-1`. [Official tag resolution](https://gitlab.freedesktop.org/api/v4/projects/xkeyboard-config%2Fxkeyboard-config/repository/tags/xkeyboard-config-2.49).
  Installed `symbols/fkeys` and `symbols/inet` exactly matched the fetched release
  sources by SHA-256: respectively
  `5e52e79433881737f067094387913a56f70a589d82262fbd0e788d81b51811f8` and
  `40bc8d95f9a7a134c6d427a4d6274b8157633ae4b85f89cb088b1b600c9b3c89`.
- Hyprland wiki snapshot **`f20353c27c09fd146baf5de7d17ff3b0f596c8ae`**, resolved
  from official `main` during research. Its [devices page](https://github.com/hyprwm/hyprland-wiki/blob/f20353c27c09fd146baf5de7d17ff3b0f596c8ae/content/configuring/core/devices.md)
  documents `hl.device`, names from `hyprctl devices`, and per-device
  `resolve_binds_by_sym`. Source code takes precedence where public documentation
  omits lifecycle or introspection limits.

## Exact selectors and duplicate names

`CKeyboard` takes its raw device name from Aquamarine. The libinput backend takes
that name from `libinput_device_get_name`. Hyprland's
`deviceNameToInternalString` lowercases bytes and replaces **space, newline, and
comma** with `-`; it does not trim, collapse consecutive hyphens, remove all
punctuation, or append a USB route. Empty names use `unknown-device`.
`getNameForNewDevice` tries the base, then `base-1`, `base-2`, etc., choosing the
first name absent from **all current `m_hids`**, not just keyboards. These are
exact string keys, not fuzzy model matches or regular expressions. [H1, H2, A1]

`hl.device` itself replaces spaces with hyphens but does **not** perform the
full lowercasing/newline/comma normalization. Use the exact lowercase name
reported by `devices`; do not pass a human-facing product label and assume it
will match. It stores fields in a name-keyed map. There is no matching by sysfs
path, event node, VID:PID, serial, regex, or address. [H3, H4]

Suffixes are allocation-time collision resolution. Removing a device removes its
HID entry; a new device can take a vacant base/suffix. Already connected devices
are not renumbered. Pointer and keyboard facets of one libinput device can get
different names because they are registered separately; two devices whose raw
names normalize to the same string also collide. Consequently, sorting sysfs
`eventN` nodes or sorting IPC keyboard names and zipping them is unsound. [H1, A1]

Read-only session snapshot (all keyboard `options` strings were empty):

| Current keyboard selector | Current address |
| --- | --- |
| `razer-naga-v3-pro-keyboard` | `0x55e7eb39b780` |
| `razer-naga-v3-pro-1` | `0x55e7ebdec940` |
| `razer-razer-naga-v2-hyperspeed-1` | `0x55e7ec46d160` |
| `razer-razer-naga-v2-hyperspeed-3` | `0x55e7ec4944b0` |
| `razer-razer-naga-v2-hyperspeed-4` | `0x55e7ecacb7f0` |

These addresses are process-local object pointers serialized by Hyprland, **not**
USB addresses, event node numbers, or durable identifiers. They are useful as a
same-session stale-object guard, but can change on reconnect and can eventually
be reused. `hl.device({name="0x...", ...})` would configure a literal name key
rather than dereference a pointer. Adding an `address` field is an unknown-field
error, not an alternative selector. Lua `hl.get_devices()` exposes read-only
device userdata with address/name but supplies no configuration-by-object API.
[H3, H5, H6]

## Mapping sysfs USB identity to a compositor keyboard

A safe kernel-side inventory starts with an exact event device and resolved
`/sys/class/input/eventN/device`, records input name, `phys`, `uniq`, capabilities,
and its physical USB ancestor/interface (VID:PID, serial when meaningful, port
route). Group by USB ancestor to associate composite interfaces; do not group
all devices merely by product name or serial. Receiver and wired transport can
have distinct routes and IDs; repeated/zero serials cannot distinguish units.
This establishes kernel identity, **not** the compositor suffix.

Observed metadata illustrates the problem:

- V3 event10: raw `Razer Naga V3 Pro Keyboard`, physical USB route `6-2.3`,
  interface `6-2.3:1.1`, HID `1532:00E8`, `phys` ending `2.3/input1`.
- V3 event9/event12/event13: raw `Razer Naga V3 Pro`, same USB ancestor but
  interfaces `1.0`, `1.1`, `1.2`. A product label alone loses facet identity.
- V2 event4/event6/event19: identical raw `Razer Razer Naga V2 HyperSpeed`, route
  `5-1.4`, interfaces `1.0`, `1.1`, `1.2`, HID `1532:00B4`; `uniq` was all zeros.
- V2 event27: **the same raw model name**, but resolved under
  `/sys/devices/virtual/input/input32`, `phys` prefixed `input-remapper/`.
  A model-name filter can select this virtual remapper instead of hardware.

The above event numbers and routes are observations, not persistent selectors.
Reading sysfs metadata does not establish which interface emits F13–F23; that
requires capability inspection and ultimately the authorized hardware test.

`devices` JSON publishes name/address/RMLVO but no event node, sysfs path,
libinput handle, serial or `phys`. Lua device properties also omit these.
Thus the public responses cannot uniquely join same-name keyboards to sysfs.
Aquamarine internally retains the libinput device handle, but that is a C++
interface, not exposed by these IPC queries. [H5, H6, A1]

**Conservative matching rule:** use normalized names only to generate candidates;
require independent proof that exactly one relevant keyboard facet and no
normalization-equivalent competing device exist, then select the exact IPC name
and retain its address. A unique candidate can support a constrained setup; it
is not a general proof under hotplug races. If two physical units, receiver plus
wired paths, same-name composite facets, or a same-name virtual output remain,
fail closed. A stronger general solution needs a compositor-side bridge exposing
`libinput handle → sysfs identity → Hyprland name/address`, or separately
established explicit user ownership. No such bridge was installed or tested.
Even address validation followed by a separate name-based setter is not atomic.

## Queries: options are visible; per-device bind policy is not

The following read-only commands were executed:

```text
hyprctl -j devices
hyprctl -j getoption input.resolve_binds_by_sym
hyprctl -j getoption 'device[razer-naga-v3-pro-keyboard]:resolve_binds_by_sym'
hyprctl -j getoption 'device[razer-naga-v3-pro-keyboard]:kb_options'
```

The global query returned `bool: false, set: false`. Both device queries returned
`no such option`. This is explained by `getConfigValue`: it looks exclusively in
the global config-value map (including colon/dot translation), never the device
map. `hl.get_config` also reads only global values. There is no public syntax in
this revision to query device-field presence, its `setByUser` flag, or effective
per-device `resolve_binds_by_sym`. Lua device userdata does not expose that field
either. A global false result therefore does **not** prove a keyboard's effective
policy is false. [H4–H6]

For **each keyboard**, `devices.keyboards[].options` exposes
`m_currentRules.options`, alongside layout/model/rules/variant and address. It
shows the applied RMLVO string, not whether it was explicitly configured for the
device or inherited. `kb_options` is a complete string override, not an additive
list merged by Hyprland. Getters choose an explicitly set device field, otherwise
the corresponding global value. Empty string is explicitly empty; it does not
mean inherit. [H1, H4, H5]

Even the RMLVO string is not a complete assertion about the actual keymap:
`kb_file` can load a full custom keymap instead, an overridden keymap can ignore
`setKeymap`, and compilation failure can fall back to US defaults. Verify the
relevant compiled symbols and bind behavior in the eventual authorized test;
string equality alone cannot prove correctness. `resolve_binds_by_sym=true`
selects the keyboard-specific symbol state for compositor binding resolution;
it affects **all** symbol binds on that keyboard, not only F13–F23. Other
per-device layout differences must therefore be considered. [H7, H8]

## Mutation lifetime and restoration limits

This pinned revision initializes only the Lua config manager. Socket commands
register `eval`/`repl`, but no `keyword` handler. The old
`hyprctl keyword device[NAME]:kb_options ...` path is **not supported here**;
legacy removal/reset behavior on older releases is outside this research and
must not be inferred from current Lua behavior. [H9]

`hl.device` inserts/replaces only fields present in its table and schedules an
input-device refresh. It does not return a removable configuration object.
Calling it again with only `name`, or omitting a previously set field, does not
clear that field. Lua table entries with `nil` are absent and therefore do not
unset anything. False explicitly overrides a boolean. Empty string explicitly
overrides a string. An extra `remove`, `reset` or `address` field is rejected as
unknown. The inspected map has no exported per-field/per-device erase API.
[H3, H4]

The name-keyed map survives hardware disconnects; new keyboard setup reapplies
configuration for the newly allocated name. Hence a reconnect **can** inherit
the runtime rule when it gets the same name, or miss it when it gets another.
Another physical or virtual device can inherit a vacant name's stale rule. An
address watcher noticing a disconnect cannot by itself delete the lingering
rule. This makes physical hotplug safety materially different from configuring
an owned ephemeral virtual keyboard. [H1, H3, H4]

A reload that reaches phase 2 clears the entire device map, recreates Lua state,
and reloads configuration from disk. Runtime-only `hl.device` entries disappear
unless configuration recreates them. A syntax failure during phase 1 returns
before clearing the map, so “any reload always removes it” is too strong. A
configuration-file entry can recreate the same selector after successful reload;
none of this makes a runtime command persist across compositor restart. Do not
issue a global reload merely as a local rollback: it reloads unrelated user
configuration and clears other runtime state. No reload was performed. [H4]

Exact rollback requires both fields' prior explicit/inherited state and any
explicit values. Public queries cannot obtain all of this here:

- Previously explicit options and bind policy, **if independently known**, can
  be restored by setting both old values, conditional on continued ownership.
- Previously inherited options restored as their old effective string become a
  new explicit override. A subsequent global options change will no longer flow
  through. Empty options have the same inheritance problem.
- Restoring false rather than inherited false has the analogous problem for
  bind policy. Not restoring the policy leaves the correction's true behind.
- Conditional rollback must check identity and all owned fields, account for
  reload/user edits, and avoid overwriting new owners. Public IPC cannot verify
  every such condition or atomically apply it in this revision.

The existing `src/gillete/keyboard_map.py` records only the options string;
`set_options` always writes `resolve_binds_by_sym=true`, including during restore.
It cannot serve as an exact physical rollback implementation. Also, its
`before == applied` early return can leave the policy changed even when no option
needed adding. Its guard limits the current exposure to Gillete virtual names;
this report does not change that code or claim a new virtual-path validation.

## XKB rule correctness and F19/F24 scope

The release rule is correctly spelled **`fkeys:basic_13-24`**. Both installed
`rules/evdev` and `rules/base` translate it to `+fkeys(basic_13-24)`; the symbols
file defines `<FK13>` through `<FK24>` with F13 through F24. It is a standard
option, not a Hyprland-specific hack. [X1, X2]

Offline verification used the installed compiler and data only:

```sh
xkbcli compile-keymap --rules evdev --model pc105 --layout us --options ''
xkbcli compile-keymap --rules evdev --model pc105 --layout us --options fkeys:basic_13-24
```

The resulting maps showed:

| Keys | Default US/evdev | With option |
| --- | --- | --- |
| F13 | XF86Tools | F13 |
| F14–F18 | XF86Launch5–XF86Launch9 | F14–F18 |
| F19 | F19 | F19, unchanged |
| F20 | XF86AudioMicMute | F20 |
| F21 | XF86TouchpadToggle | F21 |
| F22 | XF86TouchpadOn | F22 |
| F23 | base XF86TouchpadOff; Shift+Super XF86Assistant | base F23; **Shift+Super still XF86Assistant** |
| F24 | base F24; Control+Super XF86TouchpadToggle | **same base, level-two symbol, and type** |

This is a source-plus-offline-compilation result, **not a live keyboard test**.
The important
counterexample is that the option overlays symbols rather than replacing whole
key definitions: existing explicit key types and additional levels can survive.
The installed `PC_SHIFT_SUPER_LEVEL2` type selects level two for Shift+Super;
`PC_CONTROL_SUPER_LEVEL2` does so for Control+Super. Thus it is incorrect to
promise that every modified F23 becomes an ordinary F23 under this option.
[Installed compile evidence; X1, X3, X4]

For the inspected default US map the option does **not** unnecessarily change
F19 or F24's compiled behavior, although its source mentions both keys. In a
custom map with a different F19/F24 assignment it can overwrite the first symbol;
there is no universal preservation guarantee. If the requirement is strictly
“change only F13–F18 and F20–F23”, or “F23 under every modifier”, this option is
not sufficient evidence of that narrower contract. A purpose-built XKB symbols
section using explicit replacement/types could express it, but requires its own
installation/merge strategy and offline validation across actual layouts; no
custom map was written or installed here.

## Supported next steps and unresolved pieces

1. Keep the current virtual-only boundary until physical identity and restoration
   ownership are explicit. An additive options string alone is not enough.
2. For a narrowly owned physical configuration, use the exact proven keyboard
   name with Lua, retain all pre-existing options, and account for the keyboard's
   complete bind policy and keymap. Never configure the pointer facets.
3. For unattended general physical hotplug support, first supply missing identity,
   effective-field inspection, and field-unset/ownership semantics, preferably
   through an upstream interface or a separately reviewed compositor bridge.
   A future bridge is a design proposal, not an available feature established here.
4. The authorized hardware test still needs to establish which event interfaces
   emit the intended usages, base and modified F13–F23 delivery in clients,
   compositor shortcuts, modifier transitions, reconnect ordering, and reload/user
   edit handling. Do not infer those results from source or options strings.

Unresolved: exact per-device bind-policy values in this live session; exact
explicit-versus-inherited states; a unique sysfs join for the V2's multiple
same-name keyboards; proof of no hidden/ignored competing device in any future
matching heuristic; a public exact rollback API; and all live correction behavior.
The research establishes limits, not readiness to apply a physical correction.

## Primary-source anchors

- **H1:** [Hyprland InputManager.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/managers/input/InputManager.cpp):
  `setupKeyboard` (1137+), `applyConfigToKeyboard` (1215+), `removeFromHIDs` /
  `destroyKeyboard` (1533+), `getNameForNewDevice` (2180+).
- **H2:** [MiscFunctions.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/helpers/MiscFunctions.cpp#L413):
  `deviceNameToInternalString`; [Keyboard.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/devices/Keyboard.cpp): raw name from Aquamarine.
- **H3:** [LuaBindingsConfigRules.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/lua/bindings/LuaBindingsConfigRules.cpp#L994):
  `hlGetConfig`, `hlDevice` (1020–1075): name-keyed insertion, allowed fields, refresh.
- **H4:** [Lua ConfigManager.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/lua/ConfigManager.cpp):
  `reload` (609+, clear at 686), getters and explicitness (943–1002),
  `getConfigValue` (1004+). [Bool parsing](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/lua/types/LuaConfigBool.cpp)
  and [string parsing](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/lua/types/LuaConfigString.cpp): explicit-set state.
- **H5:** [IPC Commands.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/ipc/s1/Commands.cpp):
  `devicesRequest` (873+), `dispatchGetOption` (1717+), command registration (2080+).
- **H6:** [LuaDevice.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/lua/objects/LuaDevice.cpp)
  and [LuaBindingsQuery.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/lua/bindings/LuaBindingsQuery.cpp): device properties and `hl.get_devices`.
- **H7:** [IKeyboard.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/devices/IKeyboard.cpp#L61):
  `setKeymap`, custom file, override, fallback and reported rules.
- **H8:** [Keybind Manager.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/keybinds/Manager.cpp#L208):
  per-keyboard symbol-state selection; [PropRefresher.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/supplementary/propRefresher/PropRefresher.cpp#L61): input refresh.
- **H9:** [ConfigManager.cpp](https://github.com/hyprwm/Hyprland/blob/11cbc6c577b84ffb1edf4df3fc5b6128c3ae6947/src/config/ConfigManager.cpp):
  Lua-only initialization; H5 command registration contains no `keyword`.
- **A1:** [Aquamarine Session.cpp](https://github.com/hyprwm/aquamarine/blob/b77d67648336223a6c8fb88844ae316e7b72b574/src/backend/Session.cpp#L949):
  libinput device name/capabilities, separate facets, `CLibinputKeyboard::getLibinputHandle` (1034+).
- **X1:** [xkeyboard-config symbols/fkeys](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/2ec770a0085bf776de749e185ca40e50213fb21f/symbols/fkeys).
- **X2:** [rules/rules.in](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/2ec770a0085bf776de749e185ca40e50213fb21f/rules/rules.in#L396)
  (option-to-symbols generation template; installed generated `evdev:664`,
  `base:753` establish the exact translation locally).
- **X3:** [symbols/inet](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/2ec770a0085bf776de749e185ca40e50213fb21f/symbols/inet):
  `evdev` and `fkeys` sections, including F19–F24 historical mappings.
- **X4:** [types/pc](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/2ec770a0085bf776de749e185ca40e50213fb21f/types/pc):
  preserved explicit multi-level types and modifier maps.
