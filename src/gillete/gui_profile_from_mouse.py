"""Review recognized assignments and explicit unresolved choices before copying."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView,
                              QLabel, QLineEdit, QTableWidgetItem, QTextEdit, QVBoxLayout)

from .gui_diagnostics import DetailsTable
from .device_action_support import issues as device_issues, support as device_support
from .hypershift import availability
from .mapping_view import MODEL_NAMES
from .shortcuts import describe


class MouseProfileReview(QDialog):
    def __init__(self, draft, identifier, name, parent=None):
        super().__init__(parent)
        self.draft, self.identifier = draft, identifier
        self.profile = None
        self.setWindowTitle('Create Linux profile from mouse read')
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        caption = QLabel(f'{MODEL_NAMES[draft.model]} — stored slot {draft.bank}, from the last read.\n'
                         'Recognized actions become explicit overrides for this mouse. Other mice keep their stored assignments.\n'
                         'This creates an inactive local profile. It does not write the mouse, choose a default, pin a profile or start remapping.')
        caption.setWordWrap(True)
        caption.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(caption)
        self.name = QLineEdit(name)
        self.name.setMaxLength(256)
        self.name.setAccessibleName('New Linux profile name')
        layout.addWidget(self.name)
        self.table = DetailsTable(4)
        self.table.setHorizontalHeaderLabels(['Control', 'Layer', 'From mouse', 'New Linux profile'])
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(draft.rows))
        self.choices = {}
        for row, where in enumerate(draft.rows):
            control, shifted = where
            action = draft.actions.get(where)
            for column, value in enumerate((control.replace('_', ' ').title(), 'HyperShift' if shifted else 'Normal',
                                             describe(action) if action is not None else 'Unresolved stored assignment')):
                self.table.setItem(row, column, QTableWidgetItem(value))
            choice = QComboBox()
            choice.addItem('Keep stored assignment (unresolved)' if action is None else 'Copy ' + describe(action), False)
            choice.addItem('Disable in this Linux profile', True)
            choice.currentIndexChanged.connect(self.refresh)
            self.choices[where] = choice
            self.table.setCellWidget(row, 3, choice)
            if action is not None:
                support = device_support(action, draft.model, draft.snapshot)
                if support is not None and support.available is not True:
                    choice.setToolTip(support.text)
                    self.table.item(row, 2).setToolTip(support.text)
        layout.addWidget(self.table)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.readiness = QTextEdit()
        self.readiness.setReadOnly(True)
        self.readiness.setMaximumHeight(100)
        layout.addWidget(self.readiness)
        limit = QLabel('Unresolved assignments and unavailable device actions can block software activation until edited. Disable only the rows you choose; originals stay on the mouse.\n'
                       'This copies recognized actions, not a complete onboard backup. DPI/polling values and opaque native data are not imported. '
                       'Edit the new profile’s mouse overrides to customize it; shared mappings remain separate.')
        limit.setWordWrap(True)
        layout.addWidget(limit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = buttons.addButton('Create local profile', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.textChanged.connect(self.refresh)
        self.refresh()

    def selected_profile(self):
        return self.draft.profile(self.identifier, self.name.text().strip(),
            disabled={where for where, choice in self.choices.items() if choice.currentData()})

    def refresh(self, *_):
        try:
            for (control, shifted), choice in self.choices.items():
                if not shifted:
                    continue
                normal = self.draft.actions.get((control, False))
                follows_normal = (normal is not None and normal.kind == 'hypershift'
                                  and not self.choices[control, False].currentData())
                if follows_normal:
                    choice.blockSignals(True)
                    choice.setCurrentIndex(0)
                    choice.blockSignals(False)
                choice.setEnabled(not follows_normal)
                if follows_normal:
                    choice.setToolTip('The normal HyperShift trigger stays available on both layers.')
            profile = self.selected_profile()
            remaining = sum(not self.choices[where].currentData() for where in self.draft.unknown)
            disabled = sum(bool(choice.currentData()) for choice in self.choices.values())
            self.note.setText(f'{remaining} unresolved assignment(s) remain stored; '
                              f'{disabled} will be disabled only in this Linux profile.')
            self.readiness.setPlainText('\n'.join((availability(profile, self.draft.model).message,
                *device_issues(profile, self.draft.model, None, self.draft.snapshot))))
            self.create_button.setEnabled(True)
        except ValueError as error:
            self.note.setText(str(error))
            self.create_button.setEnabled(False)

    def accept(self):
        try:
            self.profile = self.selected_profile()
        except ValueError as error:
            self.note.setText(str(error))
            return
        super().accept()
