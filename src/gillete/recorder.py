"""Timed event recorder. Capture adapters call feed only during explicit recording."""

from __future__ import annotations

from dataclasses import replace
import math

from evdev import ecodes

from .model import Action, ConfigurationError, Step, integer, key_code


def replace_delays(steps, milliseconds):
    """Change explicit waits while preserving event order and simultaneous keys."""
    integer(milliseconds, 'Delay', 0, 3_600_000)
    return tuple(replace(step, milliseconds=milliseconds) if step.kind == 'wait' else step for step in steps)


class Recorder:
    def __init__(self, *, pointer_movement: bool = False, max_steps: int = 10000, fixed_delay_ms=None):
        self.pointer_movement = pointer_movement
        self.max_steps = integer(max_steps, 'Recording limit', 1, 10000)
        if fixed_delay_ms is not None:
            integer(fixed_delay_ms, 'Fixed delay', 0, 3_600_000)
        self.fixed_delay_ms = fixed_delay_ms
        self.steps: list[Step] = []
        self.held: list[str] = []
        self.last_time: float | None = None
        self.finished = False

    def feed(self, event_type: int, code: int, value: int, timestamp: float):
        if self.finished:
            raise ConfigurationError("Recording has ended")
        step = None
        if event_type == ecodes.EV_KEY and value in (0, 1):
            names = ecodes.bytype[ecodes.EV_KEY].get(code, ())
            if isinstance(names, str):
                names = [names]
            name = next((n for n in names if n.startswith(("KEY_", "BTN_"))), None)
            if not name:
                return
            if value == 1 and name not in self.held:
                step = Step("down", key=name)
            elif value == 0 and name in self.held:
                step = Step("up", key=name)
        elif event_type == ecodes.EV_REL and value:
            allowed = {ecodes.REL_WHEEL, ecodes.REL_HWHEEL}
            if self.pointer_movement:
                allowed |= {ecodes.REL_X, ecodes.REL_Y}
            if code in allowed:
                step = Step("relative", axis=ecodes.REL[code], value=value)
        if step is None:
            return
        if (type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0
                or self.last_time is not None and timestamp < self.last_time):
            raise ConfigurationError('Recording timestamps must be finite and monotonic')
        elapsed = 0
        if self.last_time is not None:
            elapsed = self.fixed_delay_ms if self.fixed_delay_ms is not None else round((timestamp - self.last_time) * 1000)
        wait = Step('wait', milliseconds=elapsed) if elapsed else None
        held = list(self.held)
        if step.kind == 'down':
            held.append(step.key)
        elif step.kind == 'up':
            held.remove(step.key)
        # Reserve room for releases before accepting this event.
        if len(self.steps) + bool(wait) + 1 + len(held) > self.max_steps:
            self.finished = True
            raise ConfigurationError("Recording limit reached; start a shorter recording")
        if wait:
            self.steps.append(wait)
        self.steps.append(step)
        self.held = held
        self.last_time = timestamp

    def finish(self, *, timestamp: float | None = None) -> Action:
        if self.finished:
            raise ConfigurationError("Recording already ended or exceeded its limit")
        if not self.steps:
            raise ConfigurationError('No keys or mouse events were recorded')
        if timestamp is not None:
            # A stop key ends a still-held chord at the stop time, rather than
            # making the final key press instantaneous. Feed also enforces the
            # configured timing policy and step limit on these releases.
            for key in reversed(self.held[:]):
                self.feed(ecodes.EV_KEY, key_code(key), 0, timestamp)
        self.finished = True
        self.steps.extend(Step("up", key=k) for k in reversed(self.held))
        self.held.clear()
        return Action("macro", steps=tuple(self.steps))
