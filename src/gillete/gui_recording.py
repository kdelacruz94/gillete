"""Explicit, non-grabbing evdev capture for the native macro recorder."""

import fcntl
import struct
import time
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices
from PySide6.QtCore import QSocketNotifier
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QVBoxLayout

from .recorder import Recorder


class RecordingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record a macro")
        self.resize(480, 230)
        self.action = None
        self.recorder = None
        self.sources = []
        self.notifiers = []
        self.held = set()
        self.events = []
        self.finishing = False
        layout = QVBoxLayout(self)
        self.status = QLabel("Recording starts only when you click Start.\n"
                             "Press F12 to stop without recording a mouse click.\n"
                             "Input owned by another remapper may not be visible.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.movement = QCheckBox("Include pointer movement (optional)")
        layout.addWidget(self.movement)
        self.start_button = QPushButton("Start recording")
        self.start_button.clicked.connect(self.begin)
        layout.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop and use recording (F12)")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.finish)
        layout.addWidget(self.stop_button)
        cancel = QPushButton("Discard")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def begin(self):
        self.recorder = Recorder(pointer_movement=self.movement.isChecked())
        self.movement.setEnabled(False)
        failures = []
        for path in list_devices():
            resolved = (Path("/sys/class/input") / Path(path).name / "device").resolve()
            if "/virtual/" in str(resolved):
                continue
            device = None
            try:
                device = InputDevice(path)
                # Preserve kernel event timing rather than Qt callback timing.
                fcntl.ioctl(device.fd, 0x400445A0, struct.pack("i", time.CLOCK_MONOTONIC))
                keys = device.capabilities().get(ecodes.EV_KEY, [])
                if ecodes.KEY_A not in keys and ecodes.BTN_LEFT not in keys:
                    device.close()
                    continue
                self.sources.append(device)
                # Ignore keys already down when recording starts.
                self.held.update((path, code) for code in device.active_keys())
                notifier = QSocketNotifier(device.fd, QSocketNotifier.Type.Read, self)
                notifier.activated.connect(lambda *_args, d=device: self.drain(d))
                self.notifiers.append(notifier)
            except OSError as error:
                if device is not None and device not in self.sources:
                    device.close()
                failures.append(str(error))
        if not self.sources:
            self.status.setText("No readable physical keyboard or mouse. Check input-device permissions.")
            self.movement.setEnabled(True)
            return
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        message = f"Recording from {len(self.sources)} input interfaces. Press F12 to finish."
        if failures:
            message += f"\n{len(failures)} interfaces were inaccessible."
        self.status.setText(message)

    def drain(self, device):
        try:
            for event in device.read():
                if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                    raise RuntimeError("Input was dropped; discard this recording and retry.")
                if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_F12:
                    if event.value == 1:
                        self.finish(stop_time=event.timestamp())
                        return
                    continue
                self.collect(device, event)
        except BlockingIOError:
            pass
        except (OSError, ValueError, RuntimeError) as error:
            self.cleanup()
            self.stop_button.setEnabled(False)
            self.status.setText(f"Recording stopped: {error}")

    def collect(self, device, event):
        if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_F12:
            return
        if event.type not in (ecodes.EV_KEY, ecodes.EV_REL):
            return
        if event.type == ecodes.EV_REL:
            axes = {ecodes.REL_WHEEL, ecodes.REL_HWHEEL}
            if self.recorder.pointer_movement:
                axes |= {ecodes.REL_X, ecodes.REL_Y}
            if event.code not in axes:
                return
        self.events.append((event.timestamp(), len(self.events), device.path,
                            event.type, event.code, event.value))
        if len(self.events) > 20000:
            raise ValueError("Recording limit reached; discard this recording and retry")

    def finish(self, _checked=False, *, stop_time=None):
        if self.finishing:
            return
        self.finishing = True
        stop_time = time.monotonic() if stop_time is None else stop_time
        try:
            if self.recorder is None:
                return
            # Drain siblings before sorting: Qt can dispatch interface callbacks
            # out of timestamp order, especially during multi-device chords.
            for device in self.sources:
                try:
                    for event in device.read():
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                            raise ValueError("Input dropped during recording")
                        self.collect(device, event)
                except BlockingIOError:
                    pass
            self.cleanup()
            for timestamp, _, path, event_type, code, value in sorted(self.events):
                if timestamp > stop_time:
                    continue
                if event_type == ecodes.EV_KEY:
                    identity = (path, code)
                    existing = any(c == code for _, c in self.held)
                    if value == 1:
                        if identity in self.held:
                            continue
                        self.held.add(identity)
                        if existing:
                            continue
                    elif value == 0:
                        if identity not in self.held:
                            continue
                        self.held.remove(identity)
                        if any(c == code for _, c in self.held):
                            continue
                self.recorder.feed(event_type, code, value, timestamp)
            self.action = self.recorder.finish()
        except (ValueError, OSError) as error:
            self.cleanup()
            self.status.setText(str(error))
            self.stop_button.setEnabled(False)
            return
        self.accept()

    def cleanup(self):
        for notifier in self.notifiers:
            notifier.setEnabled(False)
            notifier.deleteLater()
        self.notifiers.clear()
        for source in self.sources:
            source.close()
        self.sources.clear()

    def done(self, result):
        self.cleanup()
        super().done(result)
