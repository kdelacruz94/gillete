"""Native asynchronous onboard preview/recovery; no implicit hardware writes."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                              QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                              QPushButton, QTableWidget, QTableWidgetItem,
                              QTextEdit, QVBoxLayout, QWidget)

from . import hardware
from .compile_onboard import CONTROL_IDS, describe_function
from .device_action_support import decode_wheel_mode
from .devices import discover
from .gui_settings import SettingsDialog
from .model import MODEL_CONTROLS, Layers
from .onboard import Location
from .settings import SPECS, describe
from .shortcuts import describe as describe_action


class HardwareJob(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except Exception as error:
            self.failed.emit(str(error))


class SavePreview(QDialog):
    def __init__(self, snapshot, profile, parent):
        super().__init__(parent)
        self.setWindowTitle("Save to Mouse — review changes")
        self.resize(1100, 650)
        layout = QVBoxLayout(self)
        self.plan = plan = snapshot.plan(profile)
        self.changes = changes = {w: value for w, value in plan.targets.items() if snapshot.baseline[w] != value}
        heading = QLabel(f"{profile.name} → {snapshot.model.replace('_', ' ').title()}, onboard slot {snapshot.bank}\n"
                         f"{len(changes)} changed assignments. This writes persistent mouse memory.\n"
                         "A recovery journal preserves the original assignments. Linux service actions stay in your profile.\n"
                         "Choose alternatives first with Standalone mappings in the profile editor. All button layers are shown below.")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        rows = [(control, shifted) for control in MODEL_CONTROLS[snapshot.model] for shifted in (False, True)]
        self.table = table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["Control", "Layer", "Linux service action", "Current mouse", "Save to mouse"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        alternatives = profile.standalone.get(snapshot.model, Layers())
        for row, (control, shifted) in enumerate(rows):
            where = Location(snapshot.bank, CONTROL_IDS[snapshot.model][control], int(shifted))
            value = plan.targets.get(where)
            saved = describe_function(value) if value is not None else 'Blocked — see issues below'
            if value == snapshot.baseline[where]:
                saved += ' (unchanged)'
            for column, text in enumerate((control.replace('_', ' ').title(), "HyperShift" if shifted else "Normal",
                                          describe_action(profile.resolve(snapshot.model, control, shifted)),
                                          describe_function(snapshot.baseline[where]), saved)):
                table.setItem(row, column, QTableWidgetItem(text))
            table.item(row, 3).setToolTip(snapshot.baseline[where].hex(" "))
            choices = alternatives.shifted if shifted else alternatives.normal
            explanation = ('Explicit standalone choice: ' + describe_action(choices[control]) if control in choices
                           else 'Follows the profile; unassigned HyperShift actions inherit normal standalone actions.')
            table.item(row, 4).setToolTip(explanation + ('\n' + value.hex(' ') if value is not None else ''))
        layout.addWidget(table)
        if plan.issues:
            issues = QTextEdit()
            issues.setReadOnly(True)
            issues.setPlainText("Save blocked. Choose supported alternatives with Standalone mappings, or correct these assignments:\n\n"
                                + "\n".join(plan.issues))
            layout.addWidget(issues)
        elif not changes:
            layout.addWidget(QLabel("No stored assignments would change."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = save = buttons.addButton("Save to Mouse", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setEnabled(plan.writable and bool(changes))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class HardwarePanel(QWidget):
    snapshot_changed = Signal(object)

    def __init__(self, current_profile, parent=None):
        super().__init__(parent)
        self.current_profile = current_profile
        self.snapshot = None
        self.job = None
        self.verification = None
        layout = QVBoxLayout(self)
        description = QLabel("Read the mouse before preparing an onboard save. Only assigned onboard slots are listed.\n"
                             "Local profiles, macros and automatic program switching are separate from mouse memory.")
        description.setWordWrap(True)
        layout.addWidget(description)
        controls = QHBoxLayout()
        self.devices = QComboBox()
        controls.addWidget(self.devices, 1)
        self.slots = QComboBox()
        self.slots.addItem("Active onboard slot", None)
        controls.addWidget(self.slots)
        for label, callback in (("Refresh devices", self.refresh_devices), ("Read mouse", self.read_mouse)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        layout.addWidget(self.info)
        actions = QHBoxLayout()
        self.preview = QPushButton("Preview Save to Mouse…")
        self.preview.setEnabled(False)
        self.preview.clicked.connect(self.save_mouse)
        actions.addWidget(self.preview)
        self.backup_button = QPushButton('Back up inspected slot…')
        self.backup_button.setEnabled(False)
        self.backup_button.clicked.connect(self.backup_slot)
        actions.addWidget(self.backup_button)
        self.settings_button = QPushButton('Edit DPI and polling…')
        self.settings_button.setEnabled(False)
        self.settings_button.clicked.connect(self.edit_settings)
        actions.addWidget(self.settings_button)
        restore = QPushButton("Restore from recovery journal…")
        restore.clicked.connect(self.restore_mouse)
        actions.addWidget(restore)
        layout.addLayout(actions)
        self.verify_button = QPushButton('Verify a saved binding journal after restart…')
        self.verify_button.clicked.connect(self.verify_persistence)
        layout.addWidget(self.verify_button)
        self.native_review_button = QPushButton('Review native macro profile…')
        self.native_review_button.setEnabled(False)
        self.native_review_button.clicked.connect(self.review_native)
        layout.addWidget(self.native_review_button)
        self.status = QLabel("No mouse configuration has been read in this window.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.devices.currentIndexChanged.connect(self.invalidate)
        self.slots.currentIndexChanged.connect(self.invalidate)
        self.refresh_devices()

    @property
    def busy(self):
        return self.job is not None or self.verification is not None

    def invalidate(self):
        self.snapshot = None
        self.preview.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.native_review_button.setEnabled(False)
        device = self.devices.currentData()
        self.verify_button.setEnabled(device is not None and device.product_id in (0xB4, 0xE8))
        self.verify_button.setToolTip('Read-only verification for the two validated receiver routes; wired support is pending.')
        self.snapshot_changed.emit(None)

    def refresh_devices(self):
        self.invalidate()
        self.devices.clear()
        self.slots.clear()
        self.slots.addItem("Active onboard slot", None)
        for device in discover():
            self.devices.addItem(f"{device.name} — {device.transport}", device)

    def run_job(self, message, operation, success):
        if self.busy:
            return
        self.status.setText(message)
        self.setEnabled(False)
        self.job = HardwareJob(operation, self)
        self.job.succeeded.connect(success)
        self.job.failed.connect(self.failed)
        self.job.finished.connect(self.finished)
        self.job.start()

    def finished(self):
        self.job.deleteLater()
        self.job = None
        self.setEnabled(True)

    def failed(self, error):
        self.invalidate()
        self.status.setText("Operation failed: " + error)
        if "Permission denied" in error:
            self.info.setPlainText("HID access is required. Install the scoped Gillete udev rule; then refresh.\n"
                                   "Run the desktop app as your normal user.")

    def read_mouse(self):
        device, bank = self.devices.currentData(), self.slots.currentData()
        if device is not None:
            self.invalidate()
            self.run_job("Reading mouse… Keep it awake. No assignments are being changed.",
                         lambda: hardware.inspect(device, bank), self.loaded)

    def loaded(self, snapshot):
        self.slots.blockSignals(True)
        self.slots.clear()
        for bank in snapshot.assigned:
            self.slots.addItem(f"Slot {bank}" + (" (active)" if bank == snapshot.active else ""), bank)
        self.slots.setCurrentIndex(self.slots.findData(snapshot.bank))
        self.slots.blockSignals(False)
        self.snapshot = snapshot
        self.preview.setEnabled(True)
        self.backup_button.setEnabled(True)
        self.settings_button.setEnabled(snapshot.bank == snapshot.active)
        from .native_profile_review import eligible
        self.native_review_button.setEnabled(eligible(snapshot))
        lines = [f"Read {len(snapshot.records)} normal/HyperShift assignments from slot {snapshot.bank}.",
                 f"Assigned onboard slots: {', '.join(map(str, snapshot.assigned))}",
                 "Device identity verified; serial omitted from this display."]
        for name, raw in snapshot.metadata.items():
            if name.endswith('_error'):
                lines.append(f'{name.removesuffix("_error").replace("_", " ").title()}: unavailable ({raw})')
                continue
            value = bytes.fromhex(raw)
            if name == 'battery' and len(value) == 2:
                lines.append(f'Battery: {round(value[1] * 100 / 255)}% (reported at this read)')
            elif name == 'firmware' and len(value) == 2:
                lines.append(f'Firmware: {value[0]}.{value[1]}')
            elif name == 'wheel_mode':
                try:
                    decode_wheel_mode(value)
                    lines.append('Wheel-mode control: read successfully; hardware-write validation is pending.')
                except ValueError as error:
                    lines.append('Wheel-mode control: unavailable (' + str(error) + ')')
            else:
                lines.append(f'{name.title()}: unrecognized response')
        settings = snapshot.settings
        lines.append('Device settings (current active profile):')
        for name in SPECS:
            if name in settings:
                try:
                    lines.append(f'{name.title()}: {describe(name, bytes.fromhex(settings[name]), snapshot.product)}')
                except (ValueError, RuntimeError) as error:
                    lines.append(f'{name.title()}: {error}')
        lines.extend(f"{k.removesuffix('_error')}: {v}" for k, v in settings.items() if k.endswith('_error'))
        lines.append('\nCurrent stored assignments:')
        for control, identifier in CONTROL_IDS[snapshot.model].items():
            from .onboard import Location
            normal = snapshot.baseline[Location(snapshot.bank, identifier, 0)]
            shifted = snapshot.baseline[Location(snapshot.bank, identifier, 1)]
            lines.append(f"{control.replace('_', ' ').title()}: {describe_function(normal)} | HyperShift: {describe_function(shifted)}")
        self.info.setPlainText("\n".join(lines))
        self.status.setText("Read complete. Preparing a preview does not write to the mouse.")
        self.snapshot_changed.emit(snapshot)

    def backup_slot(self):
        if self.snapshot is None:
            return
        name, _ = QFileDialog.getSaveFileName(self, 'Back up inspected onboard slot',
                                              f'{self.snapshot.model}-slot-{self.snapshot.bank}.json', 'JSON (*.json)')
        if name:
            try:
                hardware.backup(self.snapshot, Path(name))
                self.status.setText('Slot backup saved, including unrecognized Synapse assignments.')
            except (OSError, ValueError) as error:
                self.failed(str(error))

    def save_mouse(self):
        if self.snapshot is None:
            return
        device, snapshot, profile = self.devices.currentData(), self.snapshot, deepcopy(self.current_profile())
        if SavePreview(snapshot, profile, self).exec() != QDialog.DialogCode.Accepted:
            return
        path = hardware.journal_directory() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex + ".json")
        self.run_job(f"Saving to mouse… Recovery journal: {path}",
                     lambda: hardware.apply(device, snapshot, profile, path),
                     lambda result: self.saved(result, path))

    def review_native(self):
        if self.snapshot is None or self.busy:
            return
        from .native_profile_review import prepare_review
        from .gui_native_profile import NativeProfileReview
        device, snapshot, profile = self.devices.currentData(), self.snapshot, deepcopy(self.current_profile())
        self.run_job('Reading native macro catalog and profile dependencies… No settings are being changed.',
                     lambda: prepare_review(device, snapshot, profile),
                     lambda prepared: NativeProfileReview(prepared, self).exec())

    def saved(self, result, path):
        self.invalidate()
        self.status.setText(f"Stored assignments verified by readback. Recovery journal: {path}\n"
                            "This save has not been power-cycle tested. Read the mouse again before another save.")

    def verify_persistence(self):
        device = self.devices.currentData()
        if device is None or self.busy:
            return
        filename, _ = QFileDialog.getOpenFileName(self, 'Choose a completed binding save journal',
                                                  str(hardware.journal_directory()), 'JSON (*.json)')
        if not filename:
            return
        from .gui_persistence import PersistenceDialog
        directory = hardware.journal_directory() / f'persistence-{uuid4().hex}'
        self.verification = PersistenceDialog(device, Path(filename), directory, self)
        try:
            self.verification.exec()
            outcome = self.verification.verification
            self.invalidate()
            result = 'not started' if outcome.phase == 'new' else outcome.phase.replace('-', ' ')
            self.status.setText('Binding verification: ' + result +
                                (f' • Receipt: {outcome.path}' if outcome.owned else ''))
        finally:
            self.verification.deleteLater()
            self.verification = None

    def edit_settings(self):
        if self.snapshot is None:
            return
        device, snapshot = self.devices.currentData(), self.snapshot
        dialog = SettingsDialog(snapshot, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.draft
        path = hardware.journal_directory() / f'settings-{uuid4().hex}.json'
        self.run_job(f'Saving device settings… Recovery journal: {path}',
                     lambda: hardware.apply_settings(device, snapshot, draft, path),
                     lambda result: self.settings_saved(result, path))

    def settings_saved(self, result, path):
        self.invalidate()
        self.status.setText(f'Device settings verified by readback. Recovery journal: {path}\n'
                            'Read the mouse again before further edits. This save has not been power-cycle tested.')

    def restore_mouse(self):
        device = self.devices.currentData()
        if device is None:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Choose mouse recovery journal",
                                                  str(hardware.journal_directory()), "JSON (*.json)")
        if not filename:
            return
        path = Path(filename)
        try:
            document = hardware.read_journal(path)
            if document.get('kind') == 'driver-mode':
                summary = 'Restore the normal input mode from this interrupted service session?'
            elif document.get('kind') in ('device-setting', 'device-settings'):
                summary = 'Restore the original device settings from this journal?'
            else:
                entries = document.get("entries")
                if not isinstance(entries, list):
                    raise ValueError("Journal has no assignment list")
                summary = f"Restore {len(entries)} journaled assignments on {device.name}?"
        except (OSError, ValueError) as error:
            self.failed(str(error))
            return
        answer = QMessageBox.question(self, "Restore original mouse assignments",
                                      summary + '\n' +
                                      "This overwrites their current values. Device identity will be checked before writing.\n"
                                      f"Journal: {path}",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.run_job("Restoring the journal's original assignments…",
                         lambda: hardware.restore(device, path),
                         lambda _: self.restored(path))

    def restored(self, path):
        self.invalidate()
        self.status.setText(f"Original values restored and verified. Journal: {path}")
