"""Explicit per-mouse alternatives for use without the Linux service."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                              QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .compile_onboard import SoftwareOnly, encode_action
from .hypershift import PULSE_CONTROLS
from .model import Action, Layers, MODEL_CONTROLS, STANDALONE_KINDS
from .shortcuts import describe


class StandaloneDialog(QDialog):
    def __init__(self, profile, model, parent=None):
        super().__init__(parent)
        self.profile, self.model = deepcopy(profile), model
        self.layers = self.profile.standalone.setdefault(model, Layers())
        self.rows = [(control, shifted) for control in MODEL_CONTROLS[model] for shifted in (False, True)]
        self.setWindowTitle('Standalone mappings — ' + model.replace('_', ' ').title())
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        explanation = QLabel('Choose what this profile saves to the mouse when the Linux service is unavailable.\n'
                             'Linux macros and other actions stay in the profile. Saving these choices is local; '
                             'use Mouse memory & settings → Preview Save to Mouse to review and write them.\n'
                             'An unassigned HyperShift action inherits the normal standalone action. '
                             'Keep stored preserves the assignment currently on that mouse layer.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.table = QTableWidget(len(self.rows), 5)
        self.table.setHorizontalHeaderLabels(['Control', 'Layer', 'Linux service action', 'Standalone action', 'Choice'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for label, callback in (('Edit alternative…', self.edit), ('Keep stored', lambda: self.choose(Action())),
                                ('Follow profile', lambda: self.choose(None))):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton('Save choices locally', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()
        self.table.selectRow(0)

    def refresh(self):
        effective = self.profile.for_onboard(self.model)
        blocked = 0
        for row, (control, shifted) in enumerate(self.rows):
            software = self.profile.resolve(self.model, control, shifted)
            action = effective.resolve(self.model, control, shifted)
            target = self.layers.shifted if shifted else self.layers.normal
            description = describe(action)
            try:
                if action.kind != 'passthrough':
                    encode_action(action, self.model)
                    if action.kind == 'hypershift' and control in PULSE_CONTROLS:
                        raise SoftwareOnly('Held HyperShift needs a button that can stay pressed')
            except SoftwareOnly:
                description += ' — needs an alternative'
                blocked += 1
            choice = describe(target[control]) if control in target else 'Follow profile / inherit normal'
            for column, text in enumerate((control.replace('_', ' ').title(), 'HyperShift' if shifted else 'Normal',
                                          describe(software), description, choice)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.status.setText(f'{blocked} layer assignments still require a supported standalone alternative.' if blocked else
                            'Choices use supported action types. The mouse preview checks saved triggers and device constraints.')

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def trigger_locked(self, control, shifted):
        if shifted and self.profile.for_onboard(self.model).resolve(self.model, control).kind == 'hypershift':
            QMessageBox.information(self, 'HyperShift activation button',
                                    'Edit the Normal standalone assignment to change this trigger. '
                                    'It stays available on both layers.')
            return True
        return False

    def choose(self, action):
        selected = self.selected()
        if selected is None:
            return
        control, shifted = selected
        if action is not None and self.trigger_locked(control, shifted):
            return
        target = self.layers.shifted if shifted else self.layers.normal
        if action is None:
            target.pop(control, None)
        else:
            target[control] = action
        self.refresh()

    def edit(self):
        selected = self.selected()
        if selected is None:
            return
        control, shifted = selected
        if self.trigger_locked(control, shifted):
            return
        from .gui import ActionDialog
        action = self.profile.for_onboard(self.model).resolve(self.model, control, shifted)
        if action.kind not in STANDALONE_KINDS or action.kind == 'hypershift' and action.playback != 'held':
            action = Action()
        dialog = ActionDialog(action, {}, self, standalone_model=self.model, control=control)
        dialog.setWindowTitle('Standalone alternative — ' + control.replace('_', ' ').title())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.choose(dialog.action)
