"""Native editor; service startup is opt-in and mouse-memory writes are explicit."""

from __future__ import annotations

from copy import deepcopy
import asyncio
from pathlib import Path
import shlex
import sys
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPushButton, QSpinBox, QSystemTrayIcon, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .gui_diagnostics import DiagnosticsPanel
from .gui_profile_transfer import ImportPreview
from .profile_transfer import duplicate as duplicate_profile, export_document, plan_import, read_bundle, write_export
from .examples import example_profiles
from .gui_recording import RecordingDialog
from .gui_hardware import HardwareJob, HardwarePanel
from .gui_service import ServicePanel
from .gui_controls import ControlSelector
from .gui_applications import ApplicationPicker
from .gui_startup import StartupPanel
from .gui_launch import InstalledApplicationPicker
from .gui_standalone import StandaloneDialog
from .applications import desktop_application
from .focus import query_windows
from .hypershift import availability, resolve_action
from .model import Action, ConfigurationError, Layers, MODEL_CONTROLS, MODELS, Profile, STANDALONE_KINDS, Step, sequence
from .mapping_view import (MODEL_NAMES, editing_action, explicit_action, rows as mapping_rows,
                           scoped_profile, view as mapping_view)
from .profiles import ProfileStore, Rule
from .recorder import replace_delays
from .shortcuts import describe, friendly_key, parse_chord, parse_key, parse_sequence
from .stored_actions import from_snapshot


def button(text, callback, layout):
    result = QPushButton(text)
    result.clicked.connect(callback)
    layout.addWidget(result)
    return result


def spin(value, low=1, high=3600000):
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


class ActionDialog(QDialog):
    def __init__(self, action: Action, profiles, parent=None, *, standalone_model=None, control=None):
        super().__init__(parent)
        self.action = action
        self.standalone_model, self.control = standalone_model, control
        self.setWindowTitle("Edit assignment")
        self.resize(650, 620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.form = form
        layout.addLayout(form)
        self.kind = QComboBox()
        for label, kind in [("Keep stored mouse assignment", "passthrough"), ("Disabled", "disabled"),
                            ("Key / chord / mouse button", "keys"), ("Macro sequence", "macro"),
                            ("Turbo", "turbo"), ("HyperShift", "hypershift"),
                            ("Switch profile", "profile"), ("Launch program", "launch"),
                            ("Scroll", "scroll"), ("DPI stage", "dpi"), ("Native V3 control", "device")]:
            if standalone_model and (kind not in STANDALONE_KINDS or kind == 'device' and standalone_model != MODELS[1]):
                continue
            self.kind.addItem(label, kind)
        self.kind.setCurrentIndex(max(0, self.kind.findData(action.kind)))
        form.addRow("Action", self.kind)
        self.keys = QLineEdit("+".join(friendly_key(k) for k in action.keys))
        self.keys.setPlaceholderText("Ctrl+K, Alt+H, 1, LeftClick … (one chord here)")
        form.addRow("Key or chord", self.keys)
        self.scroll_axis = QComboBox()
        self.scroll_axis.addItem("Vertical (+ up / − down)", "REL_WHEEL")
        self.scroll_axis.addItem("Horizontal (+ right / − left)", "REL_HWHEEL")
        self.scroll_axis.setCurrentIndex(self.scroll_axis.findData(action.axis))
        self.scroll_amount = spin(action.value, -120, 120)
        form.addRow("Scroll direction", self.scroll_axis)
        form.addRow("Scroll amount", self.scroll_amount)
        self.dpi_direction = QComboBox()
        self.dpi_direction.addItem("Next stage", "up")
        self.dpi_direction.addItem("Previous stage", "down")
        self.dpi_direction.setCurrentIndex(1 if action.target == "down" else 0)
        form.addRow("DPI action", self.dpi_direction)
        self.device_action = QComboBox()
        self.device_action.addItem('Cycle wheel mode', 'wheel_mode_cycle')
        self.device_action.addItem('Cycle onboard profile', 'onboard_profile_cycle')
        self.device_action.setCurrentIndex(1 if action.target == 'onboard_profile_cycle' else 0)
        form.addRow('Native device action', self.device_action)
        self.playback = QComboBox()
        for label, mode in [("Once", "once"), ("Fixed count", "count"),
                            ("While held", "held"), ("Toggle on/off", "toggle")]:
            self.playback.addItem(label, mode)
        self.playback.setCurrentIndex(self.playback.findData(action.playback))
        form.addRow("Playback", self.playback)
        self.count = spin(action.count, 1, 1000000)
        self.interval = spin(action.interval_ms)
        self.press = spin(action.press_ms, 1, 60000)
        form.addRow("Repeat count", self.count)
        form.addRow("Repeat interval / macro gap (ms)", self.interval)
        form.addRow("Turbo press duration (ms)", self.press)
        self.target = QComboBox()
        for profile in profiles.values():
            self.target.addItem(profile.name, profile.id)
        index = self.target.findData(action.target)
        if index >= 0:
            self.target.setCurrentIndex(index)
        form.addRow("Destination profile", self.target)
        self.launch_type = QComboBox()
        self.launch_type.addItem('Executable or script', 'command')
        self.launch_type.addItem('Installed application', 'desktop')
        self.launch_type.setCurrentIndex(1 if action.desktop_id else 0)
        form.addRow('Launch using', self.launch_type)
        self.argv = QLineEdit(shlex.join(action.argv))
        self.argv.setPlaceholderText('/usr/bin/code "path with spaces" — arguments, not a shell command')
        self.command_row = QWidget()
        command_layout = QHBoxLayout(self.command_row)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.addWidget(self.argv, 1)
        button('Browse…', self.choose_program, command_layout)
        form.addRow("Program and arguments", self.command_row)
        self.desktop_id = action.desktop_id
        self.desktop_name = QLineEdit()
        self.desktop_name.setReadOnly(True)
        self.desktop_name.setPlaceholderText('Choose an installed application')
        if action.desktop_id:
            try:
                self.desktop_name.setText(desktop_application(action.desktop_id).get_display_name())
            except (OSError, ValueError, RuntimeError):
                self.desktop_name.setText('Unavailable: ' + action.desktop_id)
            self.desktop_name.setToolTip(action.desktop_id)
        self.desktop_row = QWidget()
        desktop_layout = QHBoxLayout(self.desktop_row)
        desktop_layout.setContentsMargins(0, 0, 0, 0)
        desktop_layout.addWidget(self.desktop_name, 1)
        button('Choose application…', self.choose_desktop, desktop_layout)
        form.addRow('Application', self.desktop_row)
        self.sequence_text = QLineEdit()
        self.sequence_text.setPlaceholderText("Alt+H, O, A   or   Ctrl+B, Alt+S")
        self.macro_caption = QLabel("Build a timed sequence (each comma releases the preceding chord):")
        layout.addWidget(self.macro_caption)
        row = QHBoxLayout()
        self.macro_build = row
        row.addWidget(self.sequence_text)
        button("Build steps", self.build, row)
        button("Record…", self.record, row)
        layout.addLayout(row)
        self.sequence_timing = QHBoxLayout()
        self.sequence_hold = spin(40, 1, 60000)
        self.sequence_gap = spin(100, 0, 3_600_000)
        for label, widget in (('Key hold (ms)', self.sequence_hold), ('Between chords (ms)', self.sequence_gap)):
            self.sequence_timing.addWidget(QLabel(label))
            self.sequence_timing.addWidget(widget)
        layout.addLayout(self.sequence_timing)
        self.steps = QTableWidget(0, 3)
        self.steps.setHorizontalHeaderLabels(["Operation", "Key / axis", "Delay (ms) / amount"])
        self.steps.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.steps)
        self.load_steps(action.steps)
        tools = QHBoxLayout()
        self.macro_tools = tools
        button("Add step", lambda: self.add_step(Step("wait", milliseconds=100)), tools)
        button("Remove step", self.remove_step, tools)
        button("Move up", lambda: self.move_step(-1), tools)
        button("Move down", lambda: self.move_step(1), tools)
        button('Replace delays…', self.retime, tools)
        layout.addLayout(tools)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.launch_type.currentIndexChanged.connect(self.refresh)
        self.playback.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        kind = self.kind.currentData()
        self.keys.setEnabled(kind in {"keys", "turbo"})
        self.target.setEnabled(kind == "profile")
        self.argv.setEnabled(kind == "launch")
        self.form.setRowVisible(self.launch_type, kind == 'launch')
        self.form.setRowVisible(self.command_row, kind == 'launch' and self.launch_type.currentData() == 'command')
        self.form.setRowVisible(self.desktop_row, kind == 'launch' and self.launch_type.currentData() == 'desktop')
        self.scroll_axis.setEnabled(kind == "scroll")
        self.scroll_amount.setEnabled(kind == "scroll")
        self.dpi_direction.setEnabled(kind == "dpi")
        self.device_action.setEnabled(kind == 'device')
        self.steps.setEnabled(kind == "macro")
        self.steps.setVisible(kind == 'macro')
        self.macro_caption.setVisible(kind == 'macro')
        for row in (self.macro_build, self.sequence_timing, self.macro_tools):
            for index in range(row.count()):
                row.itemAt(index).widget().setVisible(kind == 'macro')
        self.playback.setEnabled(kind in {"macro", "turbo", "hypershift"})
        self.count.setEnabled(kind == "macro")
        self.interval.setEnabled(kind in {"macro", "turbo"})
        self.press.setEnabled(kind == "turbo")
        if kind in {"turbo", "hypershift"} and self.playback.currentData() not in {"held", "toggle"}:
            self.playback.setCurrentIndex(self.playback.findData("held"))
        for widget, visible in (
                (self.keys, kind in {'keys', 'turbo'}), (self.target, kind == 'profile'),
                (self.scroll_axis, kind == 'scroll'), (self.scroll_amount, kind == 'scroll'),
                (self.dpi_direction, kind == 'dpi'), (self.device_action, kind == 'device'),
                (self.playback, kind in {'macro', 'turbo', 'hypershift'}),
                (self.count, kind == 'macro' and self.playback.currentData() == 'count'),
                (self.interval, kind == 'turbo' or kind == 'macro' and self.playback.currentData() != 'once'),
                (self.press, kind == 'turbo')):
            self.form.setRowVisible(widget, visible)

    def choose_program(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Choose an executable or script')
        if filename:
            try:
                arguments = shlex.split(self.argv.text())[1:]
            except ValueError:
                arguments = []
            self.argv.setText(shlex.join([filename, *arguments]))

    def choose_desktop(self):
        try:
            dialog = InstalledApplicationPicker(self, selected=self.desktop_id)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                app = dialog.selected()
                self.desktop_id = app.identifier
                self.desktop_name.setText(app.name)
                self.desktop_name.setToolTip(app.identifier)
        except (OSError, ValueError, RuntimeError) as error:
            self.error.setText(str(error))

    def add_step(self, step):
        row = self.steps.rowCount()
        self.steps.insertRow(row)
        kind = QComboBox()
        kind.addItems(["down", "up", "wait", "relative"])
        kind.setCurrentText(step.kind)
        self.steps.setCellWidget(row, 0, kind)
        text = friendly_key(step.key) if step.key else step.axis
        self.steps.setItem(row, 1, QTableWidgetItem(text))
        self.steps.setItem(row, 2, QTableWidgetItem(str(step.milliseconds if step.kind == "wait" else step.value)))

    def load_steps(self, steps):
        self.steps.setRowCount(0)
        for step in steps:
            self.add_step(step)

    def read_steps(self):
        result = []
        for row in range(self.steps.rowCount()):
            kind = self.steps.cellWidget(row, 0).currentText()
            text = self.steps.item(row, 1).text().strip()
            value = self.steps.item(row, 2).text().strip()
            if kind in {"down", "up"}:
                result.append(Step(kind, key=parse_key(text)))
            elif kind == "wait":
                result.append(Step(kind, milliseconds=int(value)))
            else:
                result.append(Step(kind, axis=text, value=int(value)))
        return tuple(result)

    def build(self):
        try:
            action = sequence(*parse_sequence(self.sequence_text.text()),
                              press_ms=self.sequence_hold.value(), gap_ms=self.sequence_gap.value())
            self.load_steps(action.steps)
            self.kind.setCurrentIndex(self.kind.findData("macro"))
            self.error.clear()
        except ValueError as error:
            self.error.setText(str(error))

    def retime(self):
        value, accepted = QInputDialog.getInt(self, 'Replace macro delays',
                                             'Set every existing delay to (ms):', 100, 0, 3_600_000)
        if not accepted:
            return
        try:
            steps = self.read_steps()
            if not any(step.kind == 'wait' for step in steps):
                self.error.setText('This macro has no delay steps. Use Add step to insert one.')
                return
            self.load_steps(replace_delays(steps, value))
            self.error.clear()
        except ValueError as error:
            self.error.setText(str(error))

    def record(self):
        dialog = RecordingDialog(self)
        if dialog.exec() and dialog.action:
            self.load_steps(dialog.action.steps)
            self.kind.setCurrentIndex(self.kind.findData("macro"))

    def remove_step(self):
        if self.steps.currentRow() >= 0:
            self.steps.removeRow(self.steps.currentRow())

    def move_step(self, direction):
        row = self.steps.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < self.steps.rowCount():
            return
        try:
            steps = list(self.read_steps())
            steps[row], steps[target] = steps[target], steps[row]
            self.load_steps(steps)
            self.steps.selectRow(target)
        except ValueError as error:
            self.error.setText(str(error))

    def save(self):
        kind = self.kind.currentData()
        try:
            desktop = kind == 'launch' and self.launch_type.currentData() == 'desktop'
            if desktop and not self.desktop_id:
                raise ConfigurationError('Choose an installed application')
            self.action = Action(kind, keys=parse_chord(self.keys.text()) if kind in {"keys", "turbo"} else (),
                                 steps=self.read_steps() if kind == "macro" else (),
                                 playback=self.playback.currentData() if kind in {"macro", "turbo", "hypershift"} else "once",
                                 count=self.count.value(), interval_ms=self.interval.value(), press_ms=self.press.value(),
                                 target=self.target.currentData() if kind == "profile" else self.dpi_direction.currentData() if kind == "dpi" else self.device_action.currentData() if kind == 'device' else "",
                                 argv=tuple(shlex.split(self.argv.text())) if kind == "launch" and not desktop else (),
                                 desktop_id=self.desktop_id if desktop else '',
                                 axis=self.scroll_axis.currentData(), value=self.scroll_amount.value())
            if self.standalone_model and kind != 'passthrough':
                from .compile_onboard import encode_action
                from .hypershift import PULSE_CONTROLS
                encode_action(self.action, self.standalone_model)
                if kind == 'hypershift' and self.control in PULSE_CONTROLS:
                    raise ConfigurationError('Held HyperShift needs a button that can stay pressed')
            self.accept()
        except ValueError as error:
            self.error.setText(str(error))


class MainWindow(QMainWindow):
    def __init__(self, store: ProfileStore):
        super().__init__()
        self.store, self.config = store, store.read()
        self.saved_config = deepcopy(self.config)
        self.application_job = None
        self.setWindowTitle("Gillete — Naga profiles")
        self.resize(1050, 750)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.status = QLabel("Profile editor • Local profiles and mouse memory are saved separately")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        selectors = QHBoxLayout()
        self.model = QComboBox()
        self.model.addItem("Naga V2 HyperSpeed", MODELS[0])
        self.model.addItem("Naga V3 Pro · 12-button plate", MODELS[1])
        selectors.addWidget(self.model)
        self.profile = QComboBox()
        selectors.addWidget(self.profile, 1)
        self.scope = QComboBox()
        self.scope.addItem("Shared mappings", "common")
        self.scope.addItem("This mouse's overrides", "device")
        selectors.addWidget(self.scope)
        layout.addLayout(selectors)
        toolbar = QHBoxLayout()
        for text, callback in [("New", self.new_profile), ("Duplicate", self.duplicate), ("Rename", self.rename),
                               ("Delete", self.delete), ("Import", self.import_profile), ("Export", self.export_profile),
                               ("Add shortcut examples", self.add_examples)]:
            button(text, callback, toolbar)
        layout.addLayout(toolbar)
        button('Standalone mappings…', self.edit_standalone, toolbar)
        selection = QHBoxLayout()
        button("Pin selected profile", self.pin, selection)
        button("Automatic", self.automatic, selection)
        button("Set as default", self.set_default, selection)
        self.mode_label = QLabel()
        selection.addWidget(self.mode_label, 1)
        layout.addLayout(selection)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        self.mapping = QTableWidget(0, 3)
        self.mapping_rows = []
        self.mapping.setHorizontalHeaderLabels(["Physical control", "Normal", "HyperShift"])
        self.mapping.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.mapping.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapping.cellDoubleClicked.connect(self.edit_mapping)
        self.mapping.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mapping.customContextMenuRequested.connect(self.mapping_menu)
        mapping_page = QWidget()
        mapping_page_layout = QVBoxLayout(mapping_page)
        self.mapping_scope = QLabel()
        self.mapping_scope.setWordWrap(True)
        self.mapping_scope.setTextFormat(Qt.TextFormat.PlainText)
        mapping_page_layout.addWidget(self.mapping_scope)
        self.other_mouse = QPushButton('Show V3-only assignments on the Naga V3 Pro')
        self.other_mouse.clicked.connect(lambda: self.model.setCurrentIndex(self.model.findData(MODELS[1])))
        mapping_page_layout.addWidget(self.other_mouse)
        self.shift_status = QLabel()
        self.shift_status.setWordWrap(True)
        self.shift_status.setTextFormat(Qt.TextFormat.PlainText)
        mapping_page_layout.addWidget(self.shift_status)
        mapping_layout = QHBoxLayout()
        mapping_page_layout.addLayout(mapping_layout, 1)
        self.control_selector = ControlSelector(self)
        self.control_selector.edit_requested.connect(self.edit_selected_control)
        self.mapping.currentCellChanged.connect(self.mapping_selected)
        mapping_layout.addWidget(self.control_selector)
        mapping_layout.addWidget(self.mapping, 1)
        tabs.addTab(mapping_page, "Buttons & macros")
        rules_page = QWidget()
        rules_layout = QVBoxLayout(rules_page)
        rules_layout.addWidget(QLabel("Application class/title/executable patterns support * and ?. Higher priority wins. Only enabled rules match."))
        self.rules = QTableWidget(0, 7)
        self.rules.setHorizontalHeaderLabels(["Profile", "Application class", "Window title", "Executable", "Mouse", "Priority", "Enabled"])
        self.rules.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rules.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        rules_layout.addWidget(self.rules)
        rule_tools = QHBoxLayout()
        button("Add rule", self.add_rule, rule_tools)
        self.application_button = button('Choose running application…', self.choose_application, rule_tools)
        button("Remove rule", lambda: self.rules.removeRow(self.rules.currentRow()) if self.rules.currentRow() >= 0 else None, rule_tools)
        button("Save rules", self.save_rules, rule_tools)
        rules_layout.addLayout(rule_tools)
        tabs.addTab(rules_page, "Program profiles")
        self.diagnostics = DiagnosticsPanel(self)
        tabs.addTab(self.diagnostics, "Devices & diagnostics")
        self.hardware = HardwarePanel(self.current, self)
        self.hardware.snapshot_changed.connect(lambda _snapshot: self.refresh())
        tabs.addTab(self.hardware, "Mouse memory & settings")
        self.service = ServicePanel(self.store, self)
        self.service.updated.connect(self.service_status)
        self.service.command_finished.connect(self.service_command_finished)
        tabs.addTab(self.service, 'Software control')
        self.startup = StartupPanel(self.store, self)
        self.startup.saved.connect(lambda: self.service_command_finished('pin', None))
        tabs.addTab(self.startup, 'Startup')
        self.profile.currentIndexChanged.connect(self.refresh)
        self.model.currentIndexChanged.connect(self.refresh)
        self.scope.currentIndexChanged.connect(self.refresh)
        self.load_profiles()
        self.load_rules()
        self.refresh_devices()
        self.tray = None
        self.tray_menu = QMenu(self)
        self.tray_menu.aboutToShow.connect(self.populate_tray_menu)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon.fromTheme("input-mouse"), self)
            self.tray.setToolTip("Gillete — profile editor (service not active)")
            self.tray.setContextMenu(self.tray_menu)
            self.tray.show()
            QApplication.instance().setQuitOnLastWindowClosed(False)

    def open_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def populate_tray_menu(self):
        menu = self.tray_menu
        menu.clear()
        menu.addAction('Open Gillete', self.open_from_tray)
        try:
            config = self.store.read()
        except (ValueError, OSError) as error:
            menu.addAction('Cannot read profiles: ' + str(error)).setEnabled(False)
            config = self.config
        menu.addSeparator()
        for model, name in zip(MODELS, ('Naga V2 HyperSpeed', 'Naga V3 Pro')):
            pinned = config.pinned.get(model)
            mode = 'Pinned: ' + config.profiles[pinned].name if pinned else 'Automatic'
            submenu = menu.addMenu(f'{name} — {mode}')
            group = QActionGroup(submenu)
            group.setExclusive(True)
            for label, identifier in [('Automatic', None), *[(p.name, p.id) for p in config.profiles.values()]]:
                action = submenu.addAction(label)
                action.setData(identifier or 'automatic')
                action.setCheckable(True)
                action.setChecked(identifier == pinned)
                group.addAction(action)
                action.triggered.connect(lambda _checked=False, m=model, p=identifier: self.select_pin(m, p))
            submenu.addSeparator()
            state = self.service.last['devices'][model] if self.service.last else None
            active_name = config.profiles.get(state['profile']).name if state and state['profile'] in config.profiles else ''
            submenu.addAction('Active: ' + active_name if state and state['active'] else 'Software control inactive').setEnabled(False)
            enabled = state and (state['requested'] or state['active'])
            command = 'disable' if enabled else 'enable'
            control = submenu.addAction('Disable software control' if enabled else 'Enable software control')
            control.setEnabled(state is not None)
            control.triggered.connect(lambda _checked=False, m=model, c=command: self.service.send(c, m))
        menu.addSeparator()
        if self.service.last is None:
            menu.addAction('Start background service', self.service.start_service)
        stop = menu.addAction('Stop all software actions', lambda: self.service.send('stop-actions'))
        stop.setEnabled(self.service.last is not None)
        menu.addAction('Quit editor', self.request_quit)

    def select_pin(self, model, identifier):
        if self.service.last is not None:
            # The running service validates inherited bindings before saving
            # and activating the pin. Do not claim success from a local edit.
            self.service.send('pin', model, profile=identifier or 'automatic')
            return
        try:
            config = self.store.read()
            if identifier is None:
                config.pinned.pop(model, None)
            else:
                config.pinned[model] = identifier
            self.store.save(config, expected_revision=config.revision)
            self.config = config
            self.saved_config = deepcopy(config)
            self.load_profiles()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, 'Cannot select profile', str(error))

    def service_command_finished(self, command, _data):
        if command == 'pin':
            try:
                self.config = self.store.read()
                self.saved_config = deepcopy(self.config)
                self.load_profiles()
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, 'Cannot reload profiles', str(error))

    def service_status(self, state):
        self.diagnostics.set_service_state(state, self.service.last_error)
        active = [model.replace('_', ' ') for model in MODELS if state and state['devices'][model]['active']]
        text = ('Software control: ' + ', '.join(active)) if active else 'Software control is inactive' if state else 'Background service is not reachable'
        self.status.setText(text + ' • Local profiles and mouse memory are saved separately')
        if self.tray:
            details = [f"{m.replace('_', ' ')}: {d['profile']} ({d['mode']})" for m, d in state['devices'].items() if d['active']] if state else []
            self.tray.setToolTip('Gillete — ' + ('; '.join(details) if details else text))

    def current(self):
        return self.config.profiles[self.profile.currentData()]

    def edit_standalone(self):
        model = self.model.currentData()
        dialog = StandaloneDialog(self.current(), model, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.layers.normal or dialog.layers.shifted:
            self.current().standalone[model] = dialog.layers
        else:
            self.current().standalone.pop(model, None)
        self.save_config()
        self.refresh()

    def request_quit(self):
        if self.hardware.busy:
            QMessageBox.information(self, "Mouse operation in progress", "Wait for the current mouse operation to finish before quitting.")
        else:
            QApplication.instance().quit()

    def closeEvent(self, event):
        if self.hardware.busy:
            event.ignore()
            QMessageBox.information(self, "Mouse operation in progress", "Wait for the current mouse operation to finish before closing.")
        elif self.tray is not None and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            super().closeEvent(event)

    def save_config(self):
        try:
            self.store.save(self.config, expected_revision=self.config.revision)
            self.saved_config = deepcopy(self.config)
            self.status.setText("Saved locally • Mouse memory unchanged")
            return True
        except (ValueError, OSError) as error:
            self.config = deepcopy(self.saved_config)
            self.load_profiles()
            QMessageBox.warning(self, "Cannot save", str(error))
            return False

    def load_profiles(self, selected=None):
        selected = selected or self.profile.currentData()
        self.profile.blockSignals(True)
        self.profile.clear()
        for profile in self.config.profiles.values():
            self.profile.addItem(profile.name, profile.id)
        index = self.profile.findData(selected)
        self.profile.setCurrentIndex(max(index, 0))
        self.profile.blockSignals(False)
        self.refresh_rule_profiles()
        self.refresh()

    def refresh_rule_profiles(self):
        # Preserve unsaved rule edits while names and available profiles change.
        for row in range(self.rules.rowCount()):
            choice = self.rules.cellWidget(row, 0)
            identifier = choice.currentData()
            choice.clear()
            for profile in self.config.profiles.values():
                choice.addItem(profile.name, profile.id)
            if identifier not in self.config.profiles:
                choice.addItem("Missing profile — choose another", identifier)
            choice.setCurrentIndex(choice.findData(identifier))

    def refresh(self):
        if not self.profile.currentData():
            return
        model = self.model.currentData()
        profile = self.current()
        snapshot = self.hardware.snapshot
        stored_models = {snapshot.model: from_snapshot(snapshot)[0]} if snapshot and snapshot.bank == snapshot.active else {}
        stored = stored_models.get(model)
        self.shift_status.setText(availability(profile, model, stored).message)
        self.control_selector.refresh(model, profile, stored)
        row = self.mapping.currentRow()
        selected_column = max(1, self.mapping.currentColumn())
        selected = self.mapping_rows[row][1] if 0 <= row < len(self.mapping_rows) else 'side_1'
        self.mapping.blockSignals(True)
        self.mapping_rows = mapping_rows(profile, model)
        self.mapping.setRowCount(len(self.mapping_rows))
        for row, (row_model, control) in enumerate(self.mapping_rows):
            foreign = row_model != model
            name = control.replace('_', ' ').title() + (' · V3 only' if foreign else '')
            self.mapping.setItem(row, 0, QTableWidgetItem(name))
            row_stored = stored_models.get(row_model)
            for column, shifted in ((1, False), (2, True)):
                assignment = mapping_view(profile, row_model, control, shifted, row_stored)
                text = assignment.text
                if foreign:
                    alternatives = profile.standalone.get(row_model, Layers())
                    alternative = (alternatives.shifted if shifted else alternatives.normal).get(control)
                    if alternative is not None:
                        text += '\nStandalone: ' + describe(alternative)
                item = QTableWidgetItem(text)
                item.setToolTip(assignment.text + ('\nAvailable on the Naga V3 Pro only. Double-click to view that mouse.'
                                if foreign else '\nDouble-click to edit the selected scope. Right-click to remove an explicit assignment.'))
                self.mapping.setItem(row, column, item)
            if foreign:
                for column in range(3):
                    font = self.mapping.item(row, column).font()
                    font.setItalic(True)
                    self.mapping.item(row, column).setFont(font)
        selected_row = next((i for i, (_, control) in enumerate(self.mapping_rows) if control == selected), 0)
        self.mapping.setCurrentCell(selected_row, selected_column)
        self.mapping.blockSignals(False)
        self.mapping.resizeRowsToContents()
        self.mapping_selected(selected_row, selected_column, -1, -1)
        shared = self.scope.currentData() == 'common'
        self.mapping_scope.setText('Editing shared mappings. Each cell shows the effective action and its source. '
                                  'A mouse-specific override takes priority over a shared edit.' if shared else
                                  f'Editing {MODEL_NAMES[model]} overrides. Shared mappings apply where no override is assigned.')
        self.other_mouse.setVisible(any(m != model for m, _ in self.mapping_rows))
        pinned = self.config.pinned.get(model)
        self.mode_label.setText("Pinned: " + self.config.profiles[pinned].name if pinned else "Automatic (saved preference)")

    def edit_selected_control(self, control, shifted):
        row = MODEL_CONTROLS[self.model.currentData()].index(control)
        column = 2 if shifted else 1
        self.mapping.setCurrentCell(row, column)
        self.mapping.scrollToItem(self.mapping.item(row, column))
        self.edit_mapping(row, column)

    def mapping_selected(self, row, column, _old_row, _old_column):
        if 0 <= row < len(self.mapping_rows):
            model, control = self.mapping_rows[row]
            if model != self.model.currentData():
                self.control_selector.show_unavailable(control.replace('_', ' ').title() + ' is available on the Naga V3 Pro only.')
                return
            self.control_selector.select(control)
            if column in (1, 2):
                self.control_selector.layer.setCurrentIndex(column - 1)

    def edit_mapping(self, row, column):
        if column not in (1, 2) or not 0 <= row < len(self.mapping_rows):
            return
        model = self.model.currentData()
        row_model, control = self.mapping_rows[row]
        if row_model != model:
            self.model.setCurrentIndex(self.model.findData(row_model))
            return
        profile = self.current()
        scope = self.scope.currentData()
        snapshot = self.hardware.snapshot
        stored = from_snapshot(snapshot)[0] if snapshot and snapshot.model == model and snapshot.bank == snapshot.active else None
        normal = resolve_action(scoped_profile(profile, scope), model, control, stored=stored)
        if column == 2 and normal is not None and normal.kind == 'hypershift':
            QMessageBox.information(self, 'HyperShift activation button',
                                    'This button activates HyperShift and stays available on both layers. '
                                    'Edit its Normal assignment to change the trigger.')
            return
        action = editing_action(profile, model, control, column == 2, scope)
        dialog = ActionDialog(action, self.config.profiles, self)
        name = 'Shared mapping' if scope == 'common' else MODEL_NAMES[model] + ' override'
        dialog.setWindowTitle(name + ' — ' + control.replace('_', ' ').title() + (' · HyperShift' if column == 2 else ' · Normal'))
        current = mapping_view(profile, model, control, column == 2, stored)
        explanation = f'{name}. Currently on {MODEL_NAMES[model]}: {current.description} ({current.source}).'
        if scope == 'common' and 'This mouse’s override' in current.source:
            explanation += '\nThis mouse’s override takes priority over this shared value.'
        note = QLabel(explanation, dialog)
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        dialog.layout().insertWidget(0, note)
        if dialog.exec():
            self.change_mapping(control, column == 2, dialog.action)

    def change_mapping(self, control, shifted, action):
        model, profile = self.model.currentData(), self.current()
        if control not in MODEL_CONTROLS[model]:
            raise ValueError('Select the mouse that has this physical control before editing it')
        scope = self.scope.currentData()
        if action is None and explicit_action(profile, model, control, shifted, scope) is None:
            return
        layers = profile.common if scope == 'common' else profile.overrides.setdefault(model, Layers())
        target = layers.shifted if shifted else layers.normal
        if action is None:
            target.pop(control)
        else:
            target[control] = action
        if scope == 'device' and not layers.normal and not layers.shifted:
            profile.overrides.pop(model, None)
        self.save_config()  # On failure this restores the complete saved configuration.
        self.refresh()

    def mapping_menu(self, position):
        index = self.mapping.indexAt(position)
        if not index.isValid() or index.column() == 0:
            return
        model = self.model.currentData()
        row_model, control = self.mapping_rows[index.row()]
        if row_model != model:
            menu = QMenu(self)
            show = menu.addAction('Show this assignment on the Naga V3 Pro')
            if menu.exec(self.mapping.viewport().mapToGlobal(position)) == show:
                self.model.setCurrentIndex(self.model.findData(row_model))
            return
        profile = self.current()
        layer = profile.common if self.scope.currentData() == "common" else profile.overrides.get(model)
        if layer is None:
            return
        target = layer.shifted if index.column() == 2 else layer.normal
        if control not in target:
            return
        menu = QMenu(self)
        reset = menu.addAction('Remove shared assignment' if self.scope.currentData() == 'common' else 'Remove this mouse’s override')
        if menu.exec(self.mapping.viewport().mapToGlobal(position)) == reset:
            self.change_mapping(control, index.column() == 2, None)

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Name")
        if ok and name.strip():
            p = Profile(uuid4().hex, name.strip())
            self.config.profiles[p.id] = p
            self.save_config()
            self.load_profiles(p.id)

    def duplicate(self):
        try:
            config, identifier, rules = duplicate_profile(self.config, self.current().id)
            self.config = config
            if not self.save_config():
                return
            self.load_profiles(identifier)
            for rule in rules:
                self.add_rule(rule)
            self.status.setText(f'Profile copied locally; {len(rules)} program rules added disabled.')
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, 'Cannot duplicate profile', str(error))

    def rename(self):
        name, ok = QInputDialog.getText(self, "Rename profile", "Name", text=self.current().name)
        if ok and name.strip():
            self.current().name = name.strip()
            self.save_config()
            self.load_profiles()

    def delete(self):
        identifier = self.current().id
        p = self.config.profiles.pop(identifier)
        try:
            self.config.validate()
        except ValueError as error:
            self.config.profiles[identifier] = p
            QMessageBox.information(self, "Profile is in use", str(error))
            return
        if not self.save_config():
            self.config.profiles[identifier] = p
        self.load_profiles()

    def pin(self):
        self.select_pin(self.model.currentData(), self.current().id)

    def automatic(self):
        self.select_pin(self.model.currentData(), None)

    def set_default(self):
        self.config.defaults[self.model.currentData()] = self.current().id
        self.save_config()

    def add_examples(self):
        for p in example_profiles():
            if p.id not in self.config.profiles:
                self.config.profiles[p.id] = p
        self.save_config()
        self.load_profiles()

    def export_profile(self):
        name, _ = QFileDialog.getSaveFileName(self, "Export profile and linked profiles", self.current().name + ".json", "JSON (*.json)")
        if name:
            try:
                document = export_document(self.config, self.current().id)
                write_export(Path(name), document)
                self.status.setText(f'Exported {len(document["profiles"])} profiles and {len(document["rules"])} saved program rules.')
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, "Export failed", str(error))

    def import_profile(self):
        name, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "JSON (*.json)")
        if not name:
            return
        try:
            plan = plan_import(self.config, read_bundle(Path(name)))
            preview = ImportPreview(plan, self)
            if preview.exec() != QDialog.DialogCode.Accepted:
                return
            config = plan.configuration(activate_rules=preview.activate.isChecked())
            imported_rules = config.rules[len(self.config.rules):]
            self.config = config
            if not self.save_config():
                return
            self.load_profiles(plan.root)
            for rule in imported_rules:
                self.add_rule(rule)
            self.status.setText(f'Imported {len(plan.profiles)} profiles and {len(imported_rules)} program rules '
                                f'({sum(rule.enabled for rule in imported_rules)} enabled).')
        except (ValueError, TypeError, KeyError, OSError, AttributeError) as error:
            QMessageBox.warning(self, "Import failed", str(error))

    def add_rule(self, rule=None):
        # QPushButton.clicked passes a boolean.
        rule = rule if isinstance(rule, Rule) else None
        row = self.rules.rowCount()
        self.rules.insertRow(row)
        choice = QComboBox()
        for profile in self.config.profiles.values():
            choice.addItem(profile.name, profile.id)
        choice.setCurrentIndex(max(choice.findData(rule.profile if rule else self.current().id), 0))
        self.rules.setCellWidget(row, 0, choice)
        for column, field in ((1, "app_class"), (2, "title"), (3, "executable")):
            self.rules.setItem(row, column, QTableWidgetItem(getattr(rule, field) if rule else ""))
        model = QComboBox()
        model.addItem("Both", "")
        for name in MODELS:
            model.addItem(name.replace("_", " "), name)
        model.setCurrentIndex(max(model.findData(rule.model if rule else ""), 0))
        self.rules.setCellWidget(row, 4, model)
        self.rules.setItem(row, 5, QTableWidgetItem(str(rule.priority if rule else 0)))
        enabled = QCheckBox()
        enabled.setAccessibleName('Enable program rule')
        enabled.setChecked(rule.enabled if rule else True)
        self.rules.setCellWidget(row, 6, enabled)

    def choose_application(self):
        if self.application_job is not None:
            return
        self.application_button.setEnabled(False)
        self.application_job = HardwareJob(lambda: asyncio.run(query_windows()), self)
        self.application_job.succeeded.connect(self.applications_loaded)
        self.application_job.failed.connect(lambda error: QMessageBox.warning(self, 'Cannot list applications', error))
        self.application_job.finished.connect(self.applications_finished)
        self.application_job.start()

    def applications_loaded(self, windows):
        dialog = ApplicationPicker(windows, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_rule(dialog.rule(self.current().id))
            self.status.setText('Program rule added. Select Save rules to apply it.')

    def applications_finished(self):
        self.application_job.deleteLater()
        self.application_job = None
        self.application_button.setEnabled(True)

    def load_rules(self):
        self.rules.setRowCount(0)
        for rule in self.config.rules:
            self.add_rule(rule)

    def save_rules(self):
        old = self.config.rules
        try:
            self.config.rules = [Rule(self.rules.cellWidget(r, 0).currentData(),
                                      self.rules.item(r, 1).text(), self.rules.item(r, 2).text(),
                                      self.rules.item(r, 3).text(), self.rules.cellWidget(r, 4).currentData(),
                                      int(self.rules.item(r, 5).text()), self.rules.cellWidget(r, 6).isChecked())
                                 for r in range(self.rules.rowCount())]
            if not self.save_config():
                self.config.rules = old
        except ValueError as error:
            self.config.rules = old
            QMessageBox.warning(self, "Invalid rule", str(error))

    def refresh_devices(self):
        self.diagnostics.refresh_devices()


def start(store=None, *, background=False, start_service=False):
    from .gui_instance import EditorInstance
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Gillete")
    app.setDesktopFileName('org.gillete.Gillete')
    store = store or ProfileStore()
    instance = EditorInstance(store.path, app)
    window = None
    try:
        if not instance.claim(show=not background, start_service=start_service):
            return 0
        window = MainWindow(store)
        def requested(data):
            if data['show']:
                window.open_from_tray()
            if data['start_service']:
                window.service.start_service()
        instance.received.connect(requested)
        if not background or window.tray is None:
            window.show()
        if start_service:
            QTimer.singleShot(0, window.service.start_service)
        return app.exec()
    finally:
        # Dispose of the top-level widget before QApplication's shutdown walk.
        # Signal callbacks can otherwise keep its Python wrapper alive while
        # Qt is destroying its children (observed with Python 3.14/PySide 6.12).
        import shiboken6
        if window is not None:
            window.service.shutdown_ui()
            if window.application_job is not None:
                window.application_job.wait()
            if window.hardware.job is not None:
                window.hardware.job.wait()
            shiboken6.delete(window)
        instance.close()
        shiboken6.delete(instance)
