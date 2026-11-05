"""Native settings editor and explicit before/after review; no device I/O."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                              QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
                              QVBoxLayout)

from .settings import (DPI_MAX, POLLING, SettingsDraft, Stages, decode_dpi,
                       decode_polling, describe, plan)


class SettingsPreview(QDialog):
    def __init__(self, snapshot, proposed, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Save device settings — review changes')
        self.resize(850, 410)
        layout = QVBoxLayout(self)
        label = QLabel('These changes will be saved to the connected mouse.\n'
                       'A recovery journal retains the original settings. Button assignments are preserved.')
        label.setWordWrap(True)
        layout.addWidget(label)
        table = QTableWidget(len(proposed.changes), 3)
        table.setHorizontalHeaderLabels(['Setting', 'Current', 'New'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        labels = {'dpi': 'Current DPI', 'stages': 'DPI stages', 'polling': 'Polling rate'}
        for row, (name, value) in enumerate(proposed.changes.items()):
            texts = (labels[name], describe(name, proposed.before[name], snapshot.product),
                     describe(name, value, snapshot.product))
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                table.setItem(row, column, item)
        table.resizeRowsToContents()
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = buttons.addButton('Save settings to mouse', QDialogButtonBox.ButtonRole.AcceptRole)
        save.setEnabled(bool(proposed.changes))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SettingsDialog(QDialog):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.draft = None
        self.syncing = False
        self.setWindowTitle('Mouse DPI and polling rate')
        self.resize(670, 640)
        layout = QVBoxLayout(self)
        caption = QLabel('Edit current DPI, stored stages and receiver polling rate.\n'
                         'Selecting a different stage also sets current DPI to that stage. '
                         'Existing current DPI is otherwise preserved until you edit it.')
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.errors = []
        dpi = stages = polling = None
        try:
            dpi = decode_dpi(bytes.fromhex(snapshot.settings['dpi']), snapshot.product)
            stages = Stages.decode(bytes.fromhex(snapshot.settings['stages']), snapshot.product)
        except (KeyError, ValueError, RuntimeError) as error:
            self.errors.append('DPI editing unavailable: ' + str(error))
        self.dpi_available = dpi is not None and stages is not None
        try:
            polling = decode_polling(bytes.fromhex(snapshot.settings['polling']), snapshot.product)
        except (KeyError, ValueError, RuntimeError) as error:
            self.errors.append('Polling editing unavailable: ' + str(error))
        self.polling_available = polling is not None

        self.link_axes = QCheckBox('Link X and Y DPI')
        self.link_axes.setChecked(self.dpi_available and dpi[0] == dpi[1] and all(x == y for x, y in stages.values))
        self.link_axes.setEnabled(self.dpi_available)
        layout.addWidget(self.link_axes)

        current = QGroupBox('Current DPI')
        current.setEnabled(self.dpi_available)
        row = QHBoxLayout(current)
        self.current = (self.dpi_box(dpi[0] if dpi else 800), self.dpi_box(dpi[1] if dpi else 800))
        for label, box in zip(('X', 'Y'), self.current):
            row.addWidget(QLabel(label))
            row.addWidget(box)
        layout.addWidget(current)

        stage_group = QGroupBox('Stored DPI stages')
        stage_group.setEnabled(self.dpi_available)
        stage_layout = QVBoxLayout(stage_group)
        form = QFormLayout()
        self.count = QSpinBox()
        self.count.setRange(1, 5)
        self.count.setValue(len(stages.values) if stages else 1)
        self.active = QSpinBox()
        self.active.setRange(1, self.count.value())
        self.active.setValue(stages.active if stages else 1)
        form.addRow('Number of stages', self.count)
        form.addRow('Selected stage', self.active)
        stage_layout.addLayout(form)
        self.table = QTableWidget(5, 2)
        self.table.setHorizontalHeaderLabels(['X DPI', 'Y DPI'])
        self.table.setVerticalHeaderLabels([str(i) for i in range(1, 6)])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.rows = []
        for i in range(5):
            pair = stages.values[i] if stages and i < len(stages.values) else (dpi or (800, 800))
            boxes = tuple(self.dpi_box(v) for v in pair)
            self.rows.append(boxes)
            for column, box in enumerate(boxes):
                self.table.setCellWidget(i, column, box)
            self.table.setRowHidden(i, i >= self.count.value())
        stage_layout.addWidget(self.table)
        layout.addWidget(stage_group)

        poll_group = QGroupBox('Receiver polling rate')
        poll_group.setEnabled(self.polling_available)
        poll_layout = QFormLayout(poll_group)
        self.polling = QComboBox()
        for rate in POLLING:
            self.polling.addItem(f'{rate} Hz', rate)
        self.polling.setCurrentIndex(self.polling.findData(polling or 1000))
        poll_layout.addRow('Rate', self.polling)
        layout.addWidget(poll_group)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.review = buttons.addButton('Review changes…', QDialogButtonBox.ButtonRole.ActionRole)
        self.review.clicked.connect(self.review_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.count.valueChanged.connect(self.count_changed)
        self.active.valueChanged.connect(self.stage_selected)
        self.polling.currentIndexChanged.connect(self.changed)
        for column, box in enumerate(self.current):
            box.valueChanged.connect(lambda value, c=column: self.pair_changed(self.current, c, value))
        for i, pair in enumerate(self.rows):
            for column, box in enumerate(pair):
                box.valueChanged.connect(lambda value, r=i, c=column: self.pair_changed(self.rows[r], c, value, r))
        self.changed()

    def dpi_box(self, value):
        box = QSpinBox()
        box.setRange(100, DPI_MAX[self.snapshot.product])
        box.setValue(value)
        box.setSingleStep(50)
        return box

    def pair_changed(self, pair, column, value, row=None):
        if self.syncing:
            return
        self.syncing = True
        try:
            if self.link_axes.isChecked():
                pair[1-column].setValue(value)
            if row is not None and row + 1 == self.active.value():
                for current, source in zip(self.current, pair):
                    current.setValue(source.value())
        finally:
            self.syncing = False
        self.changed()

    def count_changed(self):
        for i in range(5):
            self.table.setRowHidden(i, i >= self.count.value())
        self.active.setMaximum(self.count.value())
        self.changed()

    def stage_selected(self):
        self.syncing = True
        try:
            for current, source in zip(self.current, self.rows[self.active.value() - 1]):
                current.setValue(source.value())
        finally:
            self.syncing = False
        self.changed()

    def collect(self):
        return SettingsDraft(dpi=tuple(b.value() for b in self.current) if self.dpi_available else None,
                             stages=tuple(tuple(b.value() for b in pair) for pair in self.rows[:self.count.value()]) if self.dpi_available else None,
                             active=self.active.value() if self.dpi_available else None,
                             polling=self.polling.currentData() if self.polling_available else None)

    def changed(self):
        try:
            proposed = plan(self.snapshot, self.collect())
            self.review.setEnabled(bool(proposed.changes))
            text = f'{len(proposed.changes)} settings changed.' if proposed.changes else 'No changes to save.'
        except (ValueError, RuntimeError) as error:
            text = str(error)
            self.review.setEnabled(False)
        self.status.setText('\n'.join([*self.errors, text]))

    def review_changes(self):
        draft = self.collect()
        proposed = plan(self.snapshot, draft)
        if SettingsPreview(self.snapshot, proposed, self).exec() == QDialog.DialogCode.Accepted:
            self.draft = draft
            self.accept()
