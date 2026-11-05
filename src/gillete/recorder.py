"""Timed event recorder. Capture adapters call feed only during explicit recording."""

from __future__ import annotations

from evdev import ecodes

from .model import Action, ConfigurationError, Step


class Recorder:
    def __init__(self, *, pointer_movement: bool = False, max_steps: int = 10000):
        self.pointer_movement = pointer_movement
        self.max_steps = max_steps
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
                self.held.append(name)
                step = Step("down", key=name)
            elif value == 0 and name in self.held:
                self.held.remove(name)
                step = Step("up", key=name)
        elif event_type == ecodes.EV_REL and value:
            allowed = {ecodes.REL_WHEEL, ecodes.REL_HWHEEL}
            if self.pointer_movement:
                allowed |= {ecodes.REL_X, ecodes.REL_Y}
            if code in allowed:
                step = Step("relative", axis=ecodes.REL[code], value=value)
        if step is None:
            return
        if self.last_time is not None:
            elapsed = round((timestamp - self.last_time) * 1000)
            if elapsed < 0:
                raise ConfigurationError("Recording timestamps must be monotonic")
            if elapsed:
                self.steps.append(Step("wait", milliseconds=elapsed))
        self.steps.append(step)
        self.last_time = timestamp
        # Reserve room for key releases on stop.
        if len(self.steps) + len(self.held) > self.max_steps:
            self.finished = True
            raise ConfigurationError("Recording limit reached; start a shorter recording")

    def finish(self) -> Action:
        if self.finished:
            raise ConfigurationError("Recording already ended or exceeded its limit")
        self.finished = True
        self.steps.extend(Step("up", key=k) for k in reversed(self.held))
        self.held.clear()
        return Action("macro", steps=tuple(self.steps))
