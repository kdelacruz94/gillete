"""Native picker for installed desktop applications; selection never launches."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .applications import installed_applications


class InstalledApplicationPicker(QDialog):
    def __init__(self, parent=None, applications=None, selected=''):
        super().__init__(parent)
        self.setWindowTitle('Choose an installed application')
        self.resize(580, 500)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search applications…')
        layout.addWidget(self.search)
        self.apps = QListWidget()
        layout.addWidget(self.apps)
        self.details = QLabel()
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for app in installed_applications() if applications is None else applications:
            item = QListWidgetItem(f'{app.name}\n{app.identifier}')
            item.setData(Qt.ItemDataRole.UserRole, app)
            self.apps.addItem(item)
            if app.identifier == selected:
                self.apps.setCurrentItem(item)
        self.search.textChanged.connect(self.filter)
        self.apps.currentItemChanged.connect(self.selection_changed)
        self.apps.itemDoubleClicked.connect(lambda _item: self.accept())
        self.selection_changed()

    def selected(self):
        item = self.apps.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and not item.isHidden() else None

    def filter(self, text):
        query = text.casefold().strip()
        for index in range(self.apps.count()):
            item = self.apps.item(index)
            app = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(query not in f'{app.name} {app.identifier} {app.description}'.casefold())
        self.selection_changed()

    def selection_changed(self, *_args):
        selected = self.selected()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(selected is not None)
        self.details.setText(selected.description if selected else 'Select an application. Nothing launches until you use the assigned mouse button.')

    def accept(self):
        if self.selected() is not None:
            super().accept()
