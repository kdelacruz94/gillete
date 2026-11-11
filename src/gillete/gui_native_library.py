"""Explicit selection of unused managed objects; no device I/O in this dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHeaderView,
                              QLabel, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout)

from .native_cleanup import proposal


class NativeLibraryReview(QDialog):
    def __init__(self, prepared, parent=None):
        super().__init__(parent)
        self.prepared = prepared
        self.setWindowTitle('Native macro storage — review unused objects')
        self.resize(1050, 660)
        layout = QVBoxLayout(self)
        inventory = prepared['catalog_before']
        caption = QLabel(f'{inventory["count"]} native macro objects. '
                         f'{inventory["available_bytes"]} bytes already free; '
                         f'{inventory["recyclable_bytes"]} bytes reported reclaimable.\n'
                         'Only selected unused macros matching Gillete save artifacts can be deleted. '
                         'Assigned, changed and unmanaged objects stay on the mouse.\n'
                         'Deletion can free object slots; bytes may become reclaimable rather than immediately free. '
                         'No formatting or defragmentation is performed.')
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.table = table = QTableWidget(len(prepared['rows']), 5)
        table.setHorizontalHeaderLabels(['Delete', 'Macro', 'Current use / ownership', 'Original recovery records', 'Estimated bytes'])
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for index, row in enumerate(prepared['rows']):
            select = QTableWidgetItem()
            select.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                            if row['deletable'] else Qt.ItemFlag.NoItemFlags)
            select.setCheckState(Qt.CheckState.Unchecked)
            select.setData(Qt.ItemDataRole.UserRole, row['id'])
            table.setItem(index, 0, select)
            references = row['reason']
            if row['references']:
                references += f' · {len(row["references"])} stored/active layer references'
            values = (f'{row["name"]} · ID {row["id"]}', references,
                      str(len(row['undo'])), str(row.get('asset', {}).get('estimated_bytes', '—')))
            for column, value in enumerate(values, 1): table.setItem(index, column, QTableWidgetItem(value))
        layout.addWidget(table)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)
        note = QLabel('Deleting original macro data can prevent an older recovery record from restoring mappings '
                      'or verifying its complete original state. External copies may also depend on that data. '
                      'Review the affected records below; their files are preserved.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.acknowledge = QCheckBox('Allow deleting original data used by the listed recovery records')
        layout.addWidget(self.acknowledge)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton('Delete selected unused macros', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.previous_selection = None
        table.itemChanged.connect(self.refresh)
        self.acknowledge.toggled.connect(self.refresh)
        self.refresh()

    def selected(self):
        return [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(self.table.rowCount())
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def refresh(self, *_):
        selected = set(self.selected())
        if selected != self.previous_selection:
            self.previous_selection = selected
            self.acknowledge.blockSignals(True)
            self.acknowledge.setChecked(False)
            self.acknowledge.blockSignals(False)
        affected = {}
        for row in self.prepared['rows']:
            if row['id'] in selected:
                for entry in row['undo']:
                    label = ('original mapping dependency' if entry['mapping_dependency'] else 'original catalog verification')
                    record = affected.setdefault(entry['path'], {'profile': entry['profile'], 'items': []})
                    record['items'].append(f'ID {row["id"]}: {label}')
        self.details.setPlainText('\n\n'.join(f'{record["profile"]} — {path}\n' + '\n'.join(record['items'])
                                             for path, record in sorted(affected.items()))
                                  or 'No original recovery records are affected by the current selection.')
        self.acknowledge.setEnabled(bool(affected))
        try:
            document = proposal(self.prepared, sorted(selected), acknowledge_undo=self.acknowledge.isChecked())
            self.status.setText(f'{len(document["selected"])} objects selected. A private receipt retains their exact bytes. '
                                'Existing save records and Linux profiles are kept. Deleted objects are not automatically re-uploaded.')
            self.delete_button.setEnabled(True)
        except ValueError as error:
            self.status.setText(str(error))
            self.delete_button.setEnabled(False)
