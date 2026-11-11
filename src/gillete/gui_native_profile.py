"""Native profile review and gated save confirmation; no direct hardware I/O."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel,
                              QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout)

from .compile_onboard import CONTROL_IDS, describe_function
from .model import MODEL_CONTROLS, MODELS
from .native_profile_transaction import originals, validate
from .onboard import Location
from .shortcuts import describe


class NativeProfileReview(QDialog):
    def __init__(self, prepared, parent=None, *, allow_save=False):
        super().__init__(parent)
        preview = validate(prepared)
        self.setWindowTitle('Native macro profile — ' + ('review changes' if allow_save else 'read-only review'))
        self.resize(1100, 700)
        layout = QVBoxLayout(self)
        old = originals(prepared['before'])
        changes = {w: value for w, value in preview.bindings.items()
                   if old[w][3:] != value}
        heading = QLabel(f'{prepared["profile"]["name"]} · V3 receiver · slot 1\n'
                         f'{len(changes)} changed assignments; {len(preview.uploads)} new native macros, '
                         f'{len(preview.assets) - len(preview.uploads)} reused.\n'
                         f'Estimated storage: {preview.required_bytes} bytes; '
                         f'already free: {prepared["catalog_before"]["available_bytes"]} bytes.\n'
                         + ('Only Save to Mouse writes these persistent mappings. Original values are journaled for undo.'
                          if allow_save else 'This is a read-only review. Nothing has been uploaded or saved.'))
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        from .model import Profile
        profile = Profile.parse(prepared['profile'])
        assets = {a.identifier: a for a in preview.assets}
        rows = [(control, layer) for control in MODEL_CONTROLS[MODELS[1]] for layer in (0, 1)]
        self.table = table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(['Control', 'Layer', 'Linux service action', 'Current mouse', 'Planned mouse'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, (control, layer) in enumerate(rows):
            where = Location(1, CONTROL_IDS[MODELS[1]][control], layer)
            target = preview.bindings.get(where)
            asset = assets.get(int.from_bytes(target[2:4], 'big')) if target and target[0] in (3, 4, 5) else None
            proposed = f'Native macro: {asset.name}' if asset else describe_function(target) if target else 'Blocked'
            if target == old[where][3:]: proposed += ' (unchanged)'
            values = (control.replace('_', ' ').title(), 'HyperShift' if layer else 'Normal',
                      describe(profile.resolve(MODELS[1], control, bool(layer))), describe_function(old[where][3:]), proposed)
            for column, value in enumerate(values): table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        from .native_profile_support import save_issues
        issues = save_issues(prepared)
        self.notes.setPlainText('\n'.join((['Save blocked:'] + issues if issues else
                                          ['Native macro data is uploaded and verified before button references are saved.'])
                                         + ([] if allow_save else ['Native macro saving is not enabled in this screen.'])
                                         + ['Existing native objects are retained for undo; byte-identical objects are reused.']
                                         + preview.warnings))
        layout.addWidget(self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.save_button = None
        if allow_save:
            self.save_button = buttons.addButton('Save to Mouse', QDialogButtonBox.ButtonRole.AcceptRole)
            self.save_button.setEnabled(not issues and bool(changes))
            buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
