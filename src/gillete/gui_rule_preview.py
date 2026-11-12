"""Read-only predictions from a frozen copy of the editor's program rules."""

from copy import deepcopy

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                              QDialogButtonBox, QFormLayout, QHBoxLayout,
                              QHeaderView, QLabel, QLineEdit, QPushButton,
                              QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .model import MODELS
from .mapping_view import MODEL_NAMES
from .profiles import Configuration, Window


class RulePreviewDialog(QDialog):
    load_windows_requested = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = Configuration.parse(deepcopy(config.json()))
        self.setWindowTitle('Preview program profiles')
        self.resize(880, 560)
        layout = QVBoxLayout(self)
        note = QLabel('Uses the rules currently shown in the editor, including unsaved edits. '
                      'Save rules to apply changes. Mapping readiness is checked when software control is enabled.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.windows = QComboBox()
        self.windows.setMinimumContentsLength(24)
        self.windows.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.windows.addItem('Enter window details manually', None)
        self.windows.currentIndexChanged.connect(self.use_window)
        row.addWidget(self.windows, 1)
        self.load_button = QPushButton('Load running windows')
        self.load_button.clicked.connect(self.request_windows)
        row.addWidget(self.load_button)
        layout.addLayout(row)
        self.window_status = QLabel('Enter window details or load running windows; then select one to preview it as focused.')
        self.window_status.setWordWrap(True)
        self.window_status.setTextFormat(Qt.TextFormat.PlainText)
        self.window_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.window_status)
        form = QFormLayout()
        self.fields = {}
        for name, label in (('app_class', 'Application class / ID'), ('title', 'Window title'), ('executable', 'Executable')):
            field = QLineEdit()
            field.setMaxLength(65536)
            field.textChanged.connect(self.render)
            field.textEdited.connect(self.manual_details)
            self.fields[name] = field
            form.addRow(label, field)
        layout.addLayout(form)
        self.no_window = QCheckBox('No program window is focused')
        self.no_window.toggled.connect(self.render)
        layout.addWidget(self.no_window)
        self.results = {}
        for model in MODELS:
            result = QLabel()
            result.setWordWrap(True)
            result.setTextFormat(Qt.TextFormat.PlainText)
            result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.results[model] = result
            layout.addWidget(result)
        tie_note = QLabel('Higher priority wins. Ties use the first matching row in the editor. Manual pins override program rules.')
        tie_note.setWordWrap(True)
        layout.addWidget(tie_note)
        self.rules = QTableWidget(len(self.config.rules), 5)
        self.rules.setHorizontalHeaderLabels(('Rule', 'Profile', 'Priority', 'V2 HyperSpeed', 'V3 Pro'))
        self.rules.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rules.setWordWrap(True)
        self.rules.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rules.verticalHeader().hide()
        layout.addWidget(self.rules, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.render()

    def request_windows(self):
        self.load_button.setEnabled(False)
        self.window_status.setText('Reading running windows…')
        self.load_windows_requested.emit()

    @Slot(object)
    def set_windows(self, windows):
        self.windows.blockSignals(True)
        self.windows.clear()
        self.windows.addItem('Enter window details manually', None)
        for window in sorted(windows, key=lambda w: (w.app_class.casefold(), w.title.casefold())):
            self.windows.addItem(f'{window.app_class or window.executable} · {window.title}'[:180], window)
        self.windows.blockSignals(False)
        self.load_button.setEnabled(True)
        self.window_status.setText(f'{len(windows)} running windows loaded. Select one to preview it as focused.'
                                   if windows else 'No selectable windows are open. You can still enter window details manually.')

    @Slot(str)
    def windows_failed(self, error):
        self.load_button.setEnabled(True)
        self.window_status.setText('Could not read running windows: ' + str(error) + '. Manual preview remains available.')

    def use_window(self, _index):
        window = self.windows.currentData()
        if window is None:
            return
        if any(len(getattr(window, name)) > field.maxLength() for name, field in self.fields.items()):
            self.windows.setCurrentIndex(0)
            self.window_status.setText('Window details exceed the preview limit; the previous input has been kept.')
            return
        self.no_window.setChecked(False)
        for name, field in self.fields.items():
            field.setText(getattr(window, name))
        self.render()

    def manual_details(self, _text):
        self.windows.setCurrentIndex(0)

    def focused_window(self):
        return Window('' if self.no_window.isChecked() else 'preview',
                      **{name: field.text() for name, field in self.fields.items()})

    def describe(self, decision):
        name = self.config.profiles[decision.profile_id].name
        if decision.source == 'pinned':
            reason = 'manual pin'
        elif decision.source == 'rule':
            reason = f'rule {decision.rule_index + 1}, priority {self.config.rules[decision.rule_index].priority}'
        else:
            reason = 'default profile'
        return f'{name} ({reason})'

    def render(self, *_):
        if not hasattr(self, 'rules'):
            return
        window = self.focused_window()
        for field in self.fields.values():
            field.setEnabled(not self.no_window.isChecked())
        automatic = {model: self.config.decision(model, window, automatic=True) for model in MODELS}
        for model in MODELS:
            actual = self.config.decision(model, window)
            text = f'{MODEL_NAMES[model]}: {self.describe(actual)}'
            if actual.source == 'pinned':
                text += '\nAutomatic would choose: ' + self.describe(automatic[model])
            self.results[model].setText(text)
        for index, rule in enumerate(self.config.rules):
            cells = [str(index + 1), self.config.profiles[rule.profile].name, str(rule.priority)]
            for model in MODELS:
                if not rule.enabled:
                    value = 'Disabled'
                elif rule.model and rule.model != model:
                    value = 'Other mouse'
                elif not window.address:
                    value = 'No focused window'
                elif not rule.matches(model, window):
                    value = 'No match'
                elif automatic[model].rule_index == index:
                    value = 'First automatic match'
                else:
                    value = 'Matches; earlier or higher priority rule wins'
                cells.append(value)
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.rules.setItem(index, column, item)
        self.rules.resizeRowsToContents()
