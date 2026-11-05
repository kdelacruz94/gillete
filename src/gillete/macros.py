"""Cancellable jobs with shared output ownership; no input devices at import time."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Protocol

from evdev import ecodes

from .model import Action, Step, key_code


class Output(Protocol):
    def key(self, code: int, value: int) -> None: ...
    def relative(self, code: int, value: int) -> None: ...


class KeyLedger:
    def __init__(self, output: Output):
        self.output = output
        self.owners: dict[str, list[int]] = {}
        self.holders: dict[int, set[str]] = defaultdict(set)

    def down(self, owner: str, code: int):
        if code in self.owners.get(owner, ()):
            return
        if not self.holders[code]:
            self.output.key(code, 1)
        self.owners.setdefault(owner, []).append(code)
        self.holders[code].add(owner)

    def up(self, owner: str, code: int):
        if code not in self.owners.get(owner, ()):
            return
        if self.holders[code] == {owner}:
            self.output.key(code, 0)
        self.owners[owner].remove(code)
        self.holders[code].remove(owner)
        if not self.holders[code]:
            del self.holders[code]
        if not self.owners[owner]:
            del self.owners[owner]

    def release(self, owner: str):
        for code in list(reversed(self.owners.get(owner, []))):
            self.up(owner, code)

    def release_all(self):
        for owner in list(self.owners):
            self.release(owner)


class MacroRunner:
    def __init__(self, ledger: KeyLedger):
        self.ledger = ledger
        self.jobs: dict[str, asyncio.Task] = {}
        self.errors: list[str] = []

    def running(self, owner: str) -> bool:
        return owner in self.jobs and not self.jobs[owner].done()

    async def start(self, owner: str, action: Action):
        if action.kind not in {"macro", "turbo"}:
            raise ValueError("Not a macro/turbo action")
        await self.cancel(owner)
        task = asyncio.create_task(self._run(owner, action), name=f"gillete:{owner}")
        self.jobs[owner] = task
        task.add_done_callback(lambda done: self._finished(owner, done))

    def _finished(self, owner: str, task: asyncio.Task):
        if self.jobs.get(owner) is task:
            self.jobs.pop(owner, None)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.errors.append(f"{owner}: {error}")
            self.errors[:] = self.errors[-100:]

    async def cancel(self, owner: str):
        task = self.jobs.pop(owner, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                # The done callback records failures; still release this job's keys.
                pass
        self.ledger.release(owner)

    async def cancel_all(self):
        # Signal every job first; awaiting one must not leave siblings running.
        owners = list(self.jobs)
        for task in list(self.jobs.values()):
            task.cancel()
        for owner in owners:
            await self.cancel(owner)

    async def _step(self, owner: str, step: Step):
        if step.kind == "down":
            self.ledger.down(owner, key_code(step.key))
        elif step.kind == "up":
            self.ledger.up(owner, key_code(step.key))
        elif step.kind == "relative":
            self.ledger.output.relative(ecodes.ecodes[step.axis], step.value)
        elif step.kind == "wait":
            await asyncio.sleep(step.milliseconds / 1000)
        # Also yield for zero-delay sequences so cancellation never starves.
        await asyncio.sleep(0)

    async def _run(self, owner: str, action: Action):
        completed = 0
        try:
            while True:
                if action.kind == "turbo":
                    for key in action.keys:
                        self.ledger.down(owner, key_code(key))
                    await asyncio.sleep(action.press_ms / 1000)
                    self.ledger.release(owner)
                else:
                    for step in action.steps:
                        await self._step(owner, step)
                completed += 1
                if action.playback == "once" or (action.playback == "count" and completed >= action.count):
                    break
                delay = action.interval_ms - action.press_ms if action.kind == "turbo" else action.interval_ms
                await asyncio.sleep(delay / 1000)
        finally:
            self.ledger.release(owner)


class RecordingOutput:
    """Deterministic output sink for tests and preview; emits no real input."""
    def __init__(self):
        self.events: list[tuple[str, int, int]] = []

    def key(self, code: int, value: int):
        self.events.append(("key", code, value))

    def relative(self, code: int, value: int):
        self.events.append(("relative", code, value))
