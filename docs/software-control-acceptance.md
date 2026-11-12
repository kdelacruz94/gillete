# Complete receiver control/layer software acceptance

Status: on2026-11-11 the V3 receiver completed all50 physical control/layer pairs
and the V2 receiver completed all42, with restored normal mode and unchanged saved
state on each. V2's original input-remapper preset was restored afterward.
Source:
`control_validation.py`, `control_pad.py`, `control_trace.py`, `guided_service.py`,
`runtime.py` and `validation_plan.py`.

## Temporary behavior and scope

The recipe checks every electronic control on the 12-button layout normally
and under held HyperShift: 42 V2 or 50 V3 taps. This includes clicks, scroll
directions, tilt, index buttons, all 12 sides and the V3 top/ring/underside controls.

The first phase uses front index/DPI-up as the V2 trigger or ring-finger as the
V3 trigger. The second uses rear index/DPI-down on V2 or top rear on V3, allowing
the first trigger itself to be tested normally and shifted. No control is
omitted because it served as HyperShift. Markers use F13–F24, Shift for the next
group, Ctrl for the 25th control and Alt for HyperShift. The preview prints every
first-phase, second-phase and outside-window assignment. Compositor shortcuts
can receive these concrete marker combinations; review them before authorizing
the live test. The pad consumes its received keys without editing binds.

The isolated service owns only the selected mouse, enters temporary driver mode
and uses its normal uniquely scoped virtual output/keymap. Exact class/title
rules select each phase. The title changes after the previous phase ends with
released buttons. Leaving the pad selects the reviewed outside profile and
cancels actions; no manual pin follows the user into another application.
Pointer motion continues, but clicks are test keys inside the pad: use Escape
to stop, or the other mouse to navigate.

Outside, known stored actions are preserved through the software decoder.
Unknown/device-setting actions and the four retired V2 MapleStory references
are explicitly masked. These are host choices, not Synapse-data edits. No
onboard binding, macro, slot, DPI, stage, polling or wheel-setting write is used.
Only the mode lease changes/restores. Main profiles, startup choices and
input-remapper configuration remain untouched.

## Preparation and run

The selected receiver mouse must be awake, with no second transport for that
model. An existing Gillete daemon blocks isolated preparation/activation rather
than being stopped automatically. Suspend another remapper for this mouse
before the separately authorized run. The other mouse remains available.

```bash
python -m gillete.guided_service prepare --product 00e8 --suite controls --directory evidence/v3-all-controls1.local
python -m gillete.guided_service run --directory evidence/v3-all-controls1.local --seconds 600
```

Use `00b4` for V2 and a new directory for each attempt. Preparation queries current
saved state, saves private originals and prints temporary overrides. It neither
activates software control nor opens a pad. Run re-derives the plan/recipe and
compares current identity, inventory, active/assigned slot, saved descriptors,
settings and supported native macro bodies before claiming a new `run`
directory. Changed plans require new preparation/review. Choose `--suite` during
prepare; run uses the reviewed saved plan.

After actual READY, tap/release only the displayed control. Hold the displayed
trigger for shifted taps; it may stay held between shifted taps, but release it
at the phase's end. Wait for the next READY before tapping again. R retries a
mistake without deleting its evidence. Escape/closing ends the run and triggers
restoration. The 30–600-second test limit starts after readiness; preparation has its
own timeout.

## Evidence and verification

Normal daemon launches never trace controls. This controller explicitly starts
its own daemon with `--trace-controls`. Each session has a fresh trace epoch
and a 512-edge buffer. The router records actual merged press/release, wheel
pulses, layer, generation, profile and source interface. It retains no raw
reports, keyboard-device input, pointer coordinates or action arguments.
Duplicate held reports do not create new presses; suppressed/disarmed reports
and buffer gaps cannot count as successful taps.

The pad opens no device or service socket. It reads private controller snapshots
and observes foreground Qt keys. Arming requires current focus/profile, released
outputs, no unrelated held control and no keyboard modifiers. A pass needs the
requested control's actual down/up in the expected layer plus the exact key/
modifier sequence. Ordinary typematic repeats are retained but not counted as
fresh taps. Keys without mouse edges, wrong controls/layers, extra keys,
incorrect modifiers, old reports and lost focus cannot pass.

The final service observation must be at least 150 ms after the last event. Its
timestamp comes from the service, not reply arrival; a delayed reply cannot
invent a quiet interval. Source snapshots older than 2 seconds fail. A restarted session
or different USB transport aborts the run. The controller independently replays
every receipt against the exact 42/50-step recipe, captured live epoch, per-run
nonce and test interval. A window tally alone is not accepted.

`run/coverage.json` retains passes, failed attempts and unfinished observations,
bounded below the recovery reader's size limit. Failed writes cannot publish
completion; the last partial file remains. `control-state.json` holds the latest
bounded service observation; `service.json` holds profile/activity samples.
Files are mode `0600` in a mode `0700` experiment directory. No ongoing logging is enabled.

## Restoration and remaining work

The controller reaps only its own children and waits for daemon cleanup before
recovering matching mode leases. It then re-reads normal mode, captured saved
descriptors, profile inventory, settings and supported native macro bodies.
Known firmware/wheel-mode values must match too; battery changes are ignored.
Failures retain recovery data rather than issuing unapproved setting repairs.
This does not compare a raw flash image, unsupported metadata or every
unassigned bank, and does not claim that wider preservation was measured.

`coverage.json` complete means the input observations completed. Separately,
`restoration.json` must confirm normal mode and unchanged captured stored state.
CONTROL COVERAGE VERIFIED prints only after both succeed. Early close, timeout,
malformed evidence or failed restoration is not a passing run. After interruption,
retain the directory and review its actual matching mode journal before explicit
recovery, for example:

```bash
gillete recover --product 00e8 /path/to/run/state/gillete/onboard/mode-<id>.json
```

This earns receiver software control/layer evidence only. Timed macro modes,
turbo cancellation, recording, launches, suspend/replug/crash, manual/automatic
profile flows, native storage, wired operation and migration retain their own
acceptance requirements. The existing shortcut/turbo plan stays separate.
Virtual F-key results do not establish the physical mouse's standalone keymap.
No hardware capability is promoted automatically from any receipt.

## V3 receiver result — 2026-11-11

`evidence/v3-controls-20261111-01.local/run/coverage.json` is complete with50
passing receipts. Independent replay against the prepared recipe, readiness
nonce and captured service epoch passes. Four failed attempts remain recorded:
normal left-click received an unexpected Meta key, shifted sides8/9 crossed
the arming/cancellation boundary, and shifted top-rear received F23. Retries
passed; the first attempts are not counted as successful observations or erased.
No cause is attributed beyond the recorded errors.

The live controller exited0 after validating the source/Qt evidence within its
captured run interval. `restoration.json` verifies normal mode, unchanged stored
state and all50 original descriptors with no errors. Its owned mode lease is
`normal-mode-restored`; there are no shutdown notes. Saved DPI was1600×1600 in
the verified unchanged baseline. No permanent binding, setting or native object
write was required. The test's daemon and window exited.

This also exercises real virtual-keyboard F13–F24 delivery for the recipe's
base/Shift/Alt/Shift+Alt combinations plus Ctrl and Ctrl+Alt on F13. It does not
test all256 modifier masks live, physical onboard F-key mapping, every application,
layout/reload handling or the other lifecycle requirements above.

## V2 receiver result — 2026-11-11

The initial V2 attempt was blocked by another application's exclusive grab.
It verified normal mode and unchanged42 descriptors/settings without starting
coverage. A direct read of input-remapper's existing daemon reported the V2
preset RUNNING. The owner explicitly authorized stopping only that preset for
the test and restarting the same preset after cleanup.

`evidence/v2-controls-20261111-02.local/run/coverage.json` is complete with42
passing receipts. Replay against its prepared recipe, nonce and service epoch
passes. Seven failed attempts are retained: initial normal left-click lost
focus; shifted rear-index/sides1/3/4/10 crossed the arming boundary; another
shifted side1 attempt had a desktop order/count mismatch. Retries passed, without
attributing a cause beyond the recorded errors or treating failures as passes.

The controller exited0, its mode lease is normal-mode-restored, and restoration
verifies unchanged stored state/all42 original descriptors with no errors or
shutdown notes. Its verified baseline was1800×1800 DPI. The owner-authorized
handoff receipt is `original-preset-restored`; the exact original preset was
independently rechecked RUNNING through the existing daemon proxy. Preset,
config and xmodmap file hashes match their pre-stop values. Other devices were
not stopped, and no preset/autostart file or permanent mouse setting was changed.
This temporary coexistence test is not a production migration.

## Wired V3 isolated acceptance path

The separate 2026-11-11 wired raw capture identified all 25 controls and two
simultaneous holds, with normal mode and saved state restored at 1600 DPI.
It did not generate virtual keys or claim software HyperShift acceptance.

`gillete.wired_acceptance prepare --capture <completed-wired-capture> --directory <new-directory>`
requires the completed capture, matching before/after getter snapshots and
restored mode journal. It replays the reports and requires all controls,
both requested combinations and no held controls. Preparation then reads a
fresh normal-mode snapshot using only getters already proven on wired E7.
Firmware/serial and the tested assigned slot must match. It builds the same
50-tap controls recipe with an isolated configuration, without activating it.

After separate approval, `gillete.wired_acceptance run --directory <directory>`
uses an adapter-specific daemon with this exact configuration and journal root.
It takes input ownership and generates markers for up to 600 seconds; Escape
ends the pad. Its runtime decoder enforces wired lengths/report IDs, rejecting
receiver-only notifications. Its hardware transport permits only proven getters
and normal/driver mode setters backed by exactly one active owned journal.
Saved binding, macro, DPI, wheel and profile setters are rejected even during
driver mode. Device-setting/unknown stored fallback actions are masked by the
reviewed proposal. The V2 and main profiles/remapper configuration are untouched.
Keep the V3 receiver disconnected for this software test.

The same source/Qt matcher, readiness/epoch fencing, cleanup and independent
receipt replay apply. Restoration compares the 50 known stored descriptors,
slot, saved settings and firmware; it does not compare all flash or unsupported
macro bodies. After interruption, with software control stopped, use
`gillete.wired_acceptance recover --directory <directory>`. Recovery permits
new enumeration only with matching raw descriptors, serial and firmware. It
restores owned mode journals and compares the saved snapshot, preserving any
unrelated differences. It does not start input control or generate keys.

The isolated path admits no saved-state setters. The normal app now shares its
checked decoder/mode guards through a separate wired read/software backend,
requiring the captured hid-generic descriptors, firmware01010000 and sole slot1.
Ordinary onboard saves/settings stay gated. Unknown/device-setting fallbacks
need explicit software replacements or disabling. No main profile/startup choice
was changed by integration. Standalone writes/persistence and wider lifecycle
still need separate evidence.

## Wired V3 result — 2026-11-11

The first `.02.local` attempt never announced READY: activation or test-window
focus timed out. The controller restored normal mode and verified all 50 stored
descriptors/settings, with no errors or shutdown notes. Its incomplete coverage
is retained. The original timeout's exact cause is unknown.

The owner completed the fresh `.03.local` run. Its 50 successful receipts
independently replay against the prepared recipe, nonce and final trace epoch.
It includes every control on both layers and the ring trigger via trigger
rotation. Six failed attempts remain recorded: normal left-click saw wheel-up;
normal wheel-up had a desktop order/count mismatch; shifted wheel-up, front index
and side6 crossed an arming/cancellation boundary; shifted right tilt received
unexpected F17. Retries passed; no cause beyond those recorded errors is inferred.

The controller exited0. Normal mode, all 50 saved descriptors, profile selection,
settings and firmware were verified restored, with no errors or shutdown notes.
An independent post-test read matches the baseline and confirms 1600×1600 DPI.
Its owned mode journal is normal-mode-restored; no test daemon/window remains.
Bounded readiness observation on this retry records target focus throughout and
the transition from requested to active. This does not retrospectively diagnose
the first timeout. The observer was removed after collection.

All three transport suites now total 142 normal/HyperShift pairs. These results
establish wired software input/key delivery on the observed unit; they do not
establish wired native writes, macro storage or standalone persistence.
