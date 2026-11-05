"""Explicit, non-grabbing evdev capture for the native macro recorder."""

import fcntl
import struct
import time
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices
from PySide6.QtCore import QSocketNotifier
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from .recorder import Recorder


def virtual_source(path):
    resolved = (Path('/sys/class/input') / Path(path).name / 'device').resolve()
    return '/virtual/' in str(resolved)


def recordable(capabilities):
    for code in capabilities.get(ecodes.EV_KEY, []):
        names = ecodes.bytype[ecodes.EV_KEY].get(code, ())
        names = [names] if isinstance(names, str) else names
        if any(name.startswith('KEY_') for name in names) or ecodes.BTN_LEFT <= code <= ecodes.BTN_TASK:
            return True
    return bool(set(capabilities.get(ecodes.EV_REL, [])) & {ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL})


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
        timing = QFormLayout()
        self.timing = QComboBox()
        self.timing.addItems(['Recorded timing', 'Fixed delay between events'])
        timing.addRow('Timing', self.timing)
        self.fixed_delay = QSpinBox()
        self.fixed_delay.setRange(0, 3_600_000)
        self.fixed_delay.setValue(100)
        self.fixed_delay.setSuffix(' ms')
        self.fixed_delay.setEnabled(False)
        self.timing.currentIndexChanged.connect(lambda index: self.fixed_delay.setEnabled(index == 1))
        timing.addRow('Fixed delay', self.fixed_delay)
        layout.addLayout(timing)
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
        if self.sources:
            return
        self.action = None
        self.finishing = False
        self.events.clear()
        self.held.clear()
        self.recorder = Recorder(pointer_movement=self.movement.isChecked(),
                                 fixed_delay_ms=self.fixed_delay.value() if self.timing.currentIndex() else None)
        self.movement.setEnabled(False)
        self.timing.setEnabled(False)
        self.fixed_delay.setEnabled(False)
        failures = []
        for path in list_devices():
            if virtual_source(path):
                continue
            device = None
            try:
                device = InputDevice(path)
                # Preserve kernel event timing rather than Qt callback timing.
                fcntl.ioctl(device.fd, 0x400445A0, struct.pack("i", time.CLOCK_MONOTONIC))
                if not recordable(device.capabilities()):
                    device.close()
                    continue
                # Ignore keys already down when recording starts.
                held = device.active_keys()
                notifier = QSocketNotifier(device.fd, QSocketNotifier.Type.Read, self)
                notifier.activated.connect(lambda *_args, d=device: self.drain(d))
                self.sources.append(device)
                self.held.update((path, code) for code in held)
                self.notifiers.append(notifier)
            except OSError as error:
                if device is not None and device not in self.sources:
                    device.close()
                failures.append(str(error))
        if not self.sources:
            self.failed('No readable physical keyboard or mouse. Check input-device permissions.')
            return
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        message = f"Recording from {len(self.sources)} input interfaces. Press F12 to finish."
        if failures:
            message += f"\n{len(failures)} interfaces were inaccessible."
        self.status.setText(message)

    def drain(self, device):
        if device not in self.sources or self.recorder is None:
            return  # A queued callback may belong to a discarded recording.
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
            self.failed(f'Recording stopped: {error}')

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
        if self.finishing or self.recorder is None:
            return
        self.finishing = True
        stop_time = time.monotonic() if stop_time is None else stop_time
        try:
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
            self.action = self.recorder.finish(timestamp=stop_time)
        except (ValueError, OSError) as error:
            self.failed(str(error))
            return
        self.accept()

    def failed(self, message):
        self.cleanup()
        self.action = self.recorder = None
        self.events.clear()
        self.held.clear()
        self.finishing = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.movement.setEnabled(True)
        self.timing.setEnabled(True)
        self.fixed_delay.setEnabled(self.timing.currentIndex() == 1)
        self.status.setText(message + '\nYou can start a new recording or discard.')

    def cleanup(self):
        for notifier in self.notifiers:
            notifier.setEnabled(False)
            notifier.deleteLater()
        self.notifiers.clear()
        for source in self.sources:
            try:
                source.close()
            except OSError:
                pass  # Continue closing siblings if a disconnected fd failed.
        self.sources.clear()

    def done(self, result):
        self.cleanup()
        self.events.clear()
        self.held.clear()
        self.recorder = None
        if result != self.DialogCode.Accepted:
            self.action = None
        super().done(result)
