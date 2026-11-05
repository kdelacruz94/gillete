"""Pick a running application without requiring compositor identifiers."""

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
                              QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .profiles import Rule, literal_pattern


class ApplicationPicker(QDialog):
    def __init__(self, windows, parent=None):
        super().__init__(parent)
        self.windows = sorted(windows, key=lambda w: (w.app_class.casefold(), w.title.casefold()))
        self.setWindowTitle('Choose a running game or program')
        self.resize(840, 430)
        layout = QVBoxLayout(self)
        text = QLabel('Select the application that should activate this profile when focused.\n'
                      'You can refine the rule or limit it to one mouse afterward.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.table = QTableWidget(len(self.windows), 3)
        self.table.setHorizontalHeaderLabels(['Application', 'Window title', 'Executable'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, window in enumerate(self.windows):
            for column, value in enumerate((window.app_class, window.title, window.executable)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(self.table)
        self.match_title = QCheckBox('Also match this window title (useful when games share an application ID)')
        layout.addWidget(self.match_title)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        choose = buttons.addButton('Add program rule', QDialogButtonBox.ButtonRole.AcceptRole)
        choose.setEnabled(bool(self.windows))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if self.windows:
            self.table.selectRow(0)
        else:
            layout.addWidget(QLabel('No selectable application windows are open.'))

    def rule(self, profile):
        index = self.table.currentRow()
        if not 0 <= index < len(self.windows):
            raise ValueError('Choose an application first')
        window = self.windows[index]
        return Rule(profile, app_class=literal_pattern(window.app_class),
                    title=literal_pattern(window.title) if self.match_title.isChecked() else '',
                    executable='' if window.app_class else literal_pattern(window.executable))
