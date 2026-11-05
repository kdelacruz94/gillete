# Remapping reuse investigation

Read-only investigation of installed input-remapper and primary upstream sources.
No services were stopped, inputs captured, or device configuration changed.

## Recommended boundary

Use python-evdev for Linux input access and uinput output, with Gillete-owned
profile resolution and cancellable macro execution. Keep onboard programming
in a separate serialized hardware backend. Treat input-remapper presets as
possible migration inputs; do not depend on its running daemon for the finished
product or import its internal macro runtime into the GUI.

This is an engineering recommendation for the draft specification, not evidence
that the new implementation already exists or has passed hardware tests.

## input-remapper

Installed package: `2.2.1.r18.gd18d486d-1`. Source directory:
`/usr/lib/python3.14/site-packages/inputremapper/`.

Its DSL is a useful reference for chords, delays, individual key-down/up,
finite repeat, while-held repetition, toggle repetition, movement, and scrolling.
The inspected GUI recorder captures binding inputs/combinations, not a proven
Synapse-style timed macro sequence.

Local implementation observations:

- `injection/macros/macro.py:38` sets multiprocessing start behavior and creates
  shared state at import time.
- `injection/mapping_handlers/macro_handler.py:91` starts a macro without retaining
  its task handle. Its reset releases remembered outputs rather than directly
  canceling that task.
- `injection/macros/tasks/hold.py:60` and `toggle.py:47` check repeat termination
  between child iterations.
- `injection/injector.py:380` stops through an event and event-loop shutdown.

Inference: copying a parser or calling reset does not establish immediate
cancellation during long delays. Implement explicit job ownership and
interruptible waits. Import only an explicitly supported preset subset and
report unsupported expressions; do not execute imported expressions as Python.

Sources: [macro documentation](https://github.com/sezanzeb/input-remapper/blob/main/readme/macros.md),
[usage](https://github.com/sezanzeb/input-remapper/blob/main/readme/usage.md),
installed source paths above. Inspected source headers declare GPL-3.0-or-later.

## Naga Control

Pinned revision: `824fac8a3951471af15a80586ac4c65d07c6bf00`.
Its V3 discovery/signature evidence and separation of Qt/service/input handling
are relevant. Its architecture covers complete input frames, resolving an action
on press and retaining it through release, output reference counts, dropped-event
recovery, and relinquishing grabs when forwarding fails. Its runtime explicitly
cancels input readers and cleans up outputs.

Its manual profiles and lack of onboard binding upload do not satisfy Gillete's
scope. Reusing this project wholesale would still leave major features missing.

Sources: [architecture](https://github.com/Rainexn0b/naga-control/blob/824fac8a3951471af15a80586ac4c65d07c6bf00/docs/architecture.md),
[runtime](https://github.com/Rainexn0b/naga-control/blob/824fac8a3951471af15a80586ac4c65d07c6bf00/src/naga_control/application/remapping.py),
[README and declared GPL-2.0-only license](https://github.com/Rainexn0b/naga-control/blob/824fac8a3951471af15a80586ac4c65d07c6bf00/README.md).

## keyd and evdev

keyd revision `f564288ac2b19d2305a5b39023c474805ff8fce5` is a useful layer-semantics
reference. Its application mapper supports class/title matching, but the inspected
script has no Hyprland-specific route. Its documented exclusion of arbitrary
individual key-up/down programming makes it a poor sole runtime for this macro
editor. Use Hyprland IPC directly for program-profile selection.

Sources: [README](https://github.com/rvaiya/keyd/blob/f564288ac2b19d2305a5b39023c474805ff8fce5/README.md),
[application mapper](https://github.com/rvaiya/keyd/blob/f564288ac2b19d2305a5b39023c474805ff8fce5/scripts/keyd-application-mapper),
[MIT license](https://github.com/rvaiya/keyd/blob/f564288ac2b19d2305a5b39023c474805ff8fce5/LICENSE).

Installed python-evdev is `2.0.0-1.1`; its upstream
[license](https://github.com/gvalkov/python-evdev/blob/master/LICENSE) is BSD-style.
Different source projects carry different licenses. Track provenance and required
notices for any code actually adapted; the current research copies no implementation.

## Engine invariants to verify

- Ordered input-frame processing; no accidental recursion through virtual devices.
- Retain each press's resolved binding through its matching release.
- Track generated-key ownership across simultaneous actions.
- Interrupt waits and repeats when canceling a macro; release its outputs.
- Disarm canceled held/toggled triggers until a fresh physical press.
- Keep program launch, focus matching, and hardware programming outside input
  forwarding so a slow operation cannot stall the mouse stream.
- Verify all of the above with meaningful fault/transition tests, then on the
  actual devices; reference-project behavior alone is not acceptance evidence.
