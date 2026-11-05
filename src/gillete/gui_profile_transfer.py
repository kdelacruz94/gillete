"""Review profile copies and optional program-rule activation before saving."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHeaderView,
                              QLabel, QTableWidgetItem, QVBoxLayout)

from .gui_diagnostics import DetailsTable
from .mapping_view import MODEL_NAMES


class ImportPreview(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import profiles — review')
        self.resize(820, 540)
        self.plan = plan
        layout = QVBoxLayout(self)
        caption = QLabel(f'Import {len(plan.profiles)} profile(s) and {len(plan.rules)} program rule(s).\n'
                         'Existing profiles, defaults and manual selections are preserved. '
                         'Linked profile switches follow the imported copies.')
        caption.setWordWrap(True)
        layout.addWidget(caption)
        table = DetailsTable(2)
        table.setHorizontalHeaderLabels(['Exported profile', 'New local profile'])
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setRowCount(len(plan.profiles))
        for row, (original, imported, identifier) in enumerate(plan.profiles):
            table.setItem(row, 0, QTableWidgetItem(original))
            table.setItem(row, 1, QTableWidgetItem(imported + (' (opens in editor)' if identifier == plan.root else '')))
        layout.addWidget(table)
        self.rules = DetailsTable(4)
        self.rules.setHorizontalHeaderLabels(['Profile', 'Program match', 'Mouse / priority', 'Exported state'])
        self.rules.setEditTriggers(self.rules.EditTrigger.NoEditTriggers)
        self.rules.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rules.setRowCount(len(plan.rules))
        for row, rule in enumerate(plan.rules):
            match = '\n'.join(f'{name}: {getattr(rule, name)}' for name in ('app_class', 'title', 'executable') if getattr(rule, name))
            for column, value in enumerate((plan.base.profiles[rule.profile].name, match,
                                             f'{MODEL_NAMES.get(rule.model, "Both mice")} / {rule.priority}',
                                             'Enabled' if rule.enabled else 'Disabled')):
                self.rules.setItem(row, column, QTableWidgetItem(value))
        self.rules.setVisible(bool(plan.rules))
        layout.addWidget(self.rules)
        self.activate = QCheckBox('Keep enabled program rules active')
        self.activate.setEnabled(any(rule.enabled for rule in plan.rules))
        layout.addWidget(self.activate)
        note = QLabel('By default, imported rules are saved disabled. Enable them later in Program profiles.\n'
                      'Keeping them active can switch profiles immediately if a matching program is focused. '
                      'Existing rules take precedence when priorities tie.')
        note.setWordWrap(True)
        layout.addWidget(note)
        if plan.existing_links:
            links = QLabel('Legacy profile-switch actions will use these existing local profiles: ' + ', '.join(plan.existing_links))
            links.setTextFormat(Qt.TextFormat.PlainText)
            links.setWordWrap(True)
            layout.addWidget(links)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton('Import locally', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
