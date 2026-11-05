"""Durable, reversible binding transactions, independent of device I/O.

Readback is evidence of the immediate stored value, not proof of power-cycle
persistence. A completed transaction never claims that physical test occurred.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Protocol

from .protocol import ProtocolError


class BindingIO(Protocol):
    product: int
    def device_serial(self) -> str: ...
    def require_normal_mode(self) -> None: ...
    def read_binding(self, bank: int, control: int, layer: int) -> bytes: ...
    def write_binding(self, bank: int, control: int, layer: int, function: bytes): ...


@dataclass(frozen=True, order=True)
class Location:
    bank: int
    control: int
    layer: int

    def json(self) -> dict:
        return {"bank": self.bank, "control": self.control, "layer": self.layer}


def durable_json(path: Path, document: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(document, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


class Programmer:
    def __init__(self, io: BindingIO, journal: Path, serial: str, control_ids: set[int]):
        self.io, self.path, self.serial, self.controls = io, journal, serial, frozenset(control_ids)

    def _identity(self):
        if not self.serial or self.io.device_serial() != self.serial:
            raise ProtocolError("The connected mouse does not match the programming identity")
        self.io.require_normal_mode()

    def _validate(self, targets: dict[Location, bytes]):
        banks = (1,) if self.io.product == 0xB4 else (1, 2, 3, 4, 5) if self.io.product in (0xE7, 0xE8) else ()
        if not targets or len(targets) > 790:
            raise ProtocolError("Empty or oversized binding plan")
        for where, function in targets.items():
            if where.bank not in banks or where.layer not in (0, 1) or where.control not in self.controls:
                raise ProtocolError("Binding plan is outside the observed bank/control inventory")
            if not isinstance(function, bytes) or len(function) != 7:
                raise ProtocolError("Malformed binding function")

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def _write_verified(self, where: Location, function: bytes):
        self.io.write_binding(where.bank, where.control, where.layer, function)
        if self.io.read_binding(where.bank, where.control, where.layer) != function:
            raise ProtocolError(f"Stored readback mismatch: {where}")

    def _read(self, where: Location):
        reader = getattr(self.io, "read_binding_record", None)
        if reader is None:
            return self.io.read_binding(where.bank, where.control, where.layer), None
        raw = reader(where.bank, where.control, where.layer)
        if len(raw) != 10 or raw[:2] != bytes((where.bank, where.control)) or raw[2] not in (0, 1):
            raise ProtocolError("Unknown binding metadata; no programming is permitted")
        return raw[3:], raw[2]

    def _record_best_effort(self, document):
        try:
            durable_json(self.path, document)
        except OSError as error:
            # The original prepared journal is already durable. Losing the
            # ability to update its status must not prevent restoring hardware.
            document["journal_update_error"] = str(error)

    def _restore_values(self, before, flags):
        for where in self._order(before):
            self._write_verified(where, before[where])
        groups = {(w.bank, w.control) for w, flag in flags.items() if flag == 1}
        for bank, control in sorted(groups):
            shifted = Location(bank, control, 1)
            if shifted not in before:
                raise ProtocolError("Missing shifted function for original reply metadata")
            # A final same-value shifted write restores the original reply flag
            # to 1 without changing either action. Observed on the user's V2.
            self._write_verified(shifted, before[shifted])
        for where, expected in flags.items():
            if expected is not None and self._read(where)[1] != expected:
                raise ProtocolError("Original binding reply metadata was not restored")

    @staticmethod
    def _order(locations):
        # Shifted writes precede normal writes, including during restoration.
        return sorted(locations, key=lambda w: (w.bank, -w.layer, w.control))

    def apply(self, targets: dict[Location, bytes]) -> dict:
        self._validate(targets)
        with self._lock():
            self._identity()
            if self.path.exists():
                raise ProtocolError("This journal already exists; restore it or choose a new transaction path")
            targets = dict(targets)
            # A normal write clears reply metadata changed by a shifted write.
            # Preserve its original function if this plan only edits the layer.
            for where in list(targets):
                if where.layer == 1:
                    normal = Location(where.bank, where.control, 0)
                    if normal not in targets:
                        targets[normal] = self.io.read_binding(normal.bank, normal.control, 0)
            observations = {w: self._read(w) for w in targets}
            for where, (_, flag) in list(observations.items()):
                if flag == 1:
                    companion = Location(where.bank, where.control, 1 - where.layer)
                    if companion not in targets:
                        observations[companion] = self._read(companion)
                        targets[companion] = observations[companion][0]
                    if observations[companion][1] != flag:
                        raise ProtocolError("Inconsistent reply flags; restore behavior is not established")
            before = {w: value for w, (value, _) in observations.items()}
            flags = {w: flag for w, (_, flag) in observations.items()}
            if any(len(value) != 7 for value in before.values()):
                raise ProtocolError("Incomplete pre-write readback")
            changed_shift = {w for w in targets if w.layer == 1 and targets[w] != before[w]}
            changed = {w for w in targets if targets[w] != before[w]}
            changed |= {Location(w.bank, w.control, 0) for w in changed_shift}
            recovery = set(changed)
            for where in list(changed):
                if flags[where] == 1:
                    recovery.add(Location(where.bank, where.control, 1 - where.layer))
            document = {"version": 1, "product": self.io.product, "serial": self.serial,
                        "status": "prepared", "power_cycle_verified": False,
                        "entries": [{**w.json(), "before": before[w].hex(), "after": targets[w].hex(),
                                     "reply_flag_before": flags[w]}
                                    for w in self._order(recovery)]}
            durable_json(self.path, document)  # Must reach disk before the first SET.
            try:
                for where in self._order(changed):
                    self._write_verified(where, targets[where])
                document["status"] = "applied-readback-verified"
                durable_json(self.path, document)
                return document
            except BaseException as failure:
                document["status"] = "restore-required"
                document["failure"] = str(failure)
                self._record_best_effort(document)
                try:
                    self._identity()
                    # Include every planned write: timeout may follow a completed SET.
                    self._restore_values({w: before[w] for w in recovery}, {w: flags[w] for w in recovery})
                except BaseException as restore_failure:
                    document["restore_failure"] = str(restore_failure)
                    self._record_best_effort(document)
                    raise ProtocolError("Programming interrupted; restore is required. Journal retained.") from restore_failure
                document["status"] = "rolled-back-readback-verified"
                self._record_best_effort(document)
                raise failure

    def restore(self) -> dict:
        with self._lock():
            self._identity()
            with self.path.open("rb") as file:
                raw = file.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ProtocolError("Oversized recovery journal")
            document = json.loads(raw)
            if document.get("version") != 1 or document.get("product") != self.io.product or document.get("serial") != self.serial:
                raise ProtocolError("Recovery journal belongs to another device or format")
            entries = document.get("entries", [])
            before = {}
            flags = {}
            for entry in entries:
                where = Location(entry["bank"], entry["control"], entry["layer"])
                if where in before:
                    raise ProtocolError("Duplicate recovery location")
                before[where] = bytes.fromhex(entry["before"])
                flag = entry.get("reply_flag_before")
                if flag is not None and (type(flag) is not int or flag not in (0, 1)):
                    raise ProtocolError("Invalid recovery metadata")
                flags[where] = flag
            if before:
                self._validate(before)
            # Journals must contain the companion normal binding, even if its
            # function was unchanged, so restores clear shifted reply metadata.
            if any(w.layer == 1 and Location(w.bank, w.control, 0) not in before for w in before):
                raise ProtocolError("Recovery journal is missing a normal-layer companion")
            if any(flag == 1 and Location(w.bank, w.control, 1 - w.layer) not in before
                   for w, flag in flags.items()):
                raise ProtocolError("Recovery journal is missing a reply-metadata companion")
            document["status"] = "restore-required"
            self._record_best_effort(document)
            self._restore_values(before, flags)
            document["status"] = "restored-readback-verified"
            self._record_best_effort(document)
            return document
