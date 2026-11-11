"""Startup preferences do not activate or disable any current mouse session."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .model import MODELS
from .startup import AutostartEntry
from .stop_shortcut import KEYS, MODIFIERS, StopShortcut


class StartupPanel(QWidget):
    saved = Signal()

    def __init__(self, store, parent=None, entry=None):
        super().__init__(parent)
        self.store = store
        self.entry = entry or AutostartEntry(store.path)
        layout = QVBoxLayout(self)
        intro = QLabel('Start Gillete in the system tray and start its background service when you sign in.\n'
                       'Desktop startup requires Hyprland with an XDG autostart manager, such as UWSM.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.desktop = QCheckBox('Start with desktop')
        layout.addWidget(self.desktop)
        self.desktop_status = QLabel()
        self.desktop_status.setWordWrap(True)
        layout.addWidget(self.desktop_status)
        self.load_desktop()
        self.desktop.toggled.connect(self.set_desktop)
        label = QLabel('Enable software control when the background service starts:\n'
                       'Choose a mouse only after validating it and suspending its other remapper.\n'
                       'These choices apply at the next service start; saved mouse memory is preserved.')
        label.setWordWrap(True)
        layout.addWidget(label)
        config = self.store.read()
        self.mice = {}
        for model, name in zip(MODELS, ('Naga V2 HyperSpeed', 'Naga V3 Pro')):
            box = QCheckBox(name)
            box.setChecked(model in config.startup_models)
            layout.addWidget(box)
            self.mice[model] = box
        save = QPushButton('Save startup mouse choices')
        save.clicked.connect(self.save_mice)
        layout.addWidget(save)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        emergency = QLabel('Emergency stop shortcut\n'
                           'Stops macros and releases generated keys. Changes apply after you stop and restart the background service. '
                           'The current shortcut stays active until then. Conflicting desktop bindings prevent mouse activation.')
        emergency.setWordWrap(True)
        layout.addWidget(emergency)
        current = StopShortcut.parse(config.emergency_shortcut)
        choices = QHBoxLayout()
        self.stop_mods = {}
        for modifier in MODIFIERS:
            box = QCheckBox(modifier)
            box.setChecked(modifier in current.modifiers)
            choices.addWidget(box)
            self.stop_mods[modifier] = box
        self.stop_key = QComboBox()
        self.stop_key.setAccessibleName('Emergency stop key')
        self.stop_key.addItems(KEYS)
        self.stop_key.setCurrentText(current.key)
        choices.addWidget(self.stop_key)
        layout.addLayout(choices)
        self.save_stop_button = QPushButton('Save emergency shortcut preference')
        self.save_stop_button.clicked.connect(self.save_stop)
        layout.addWidget(self.save_stop_button)
        self.stop_result = QLabel()
        self.stop_result.setWordWrap(True)
        layout.addWidget(self.stop_result)
        layout.addStretch()

    def load_desktop(self):
        self.desktop.blockSignals(True)
        try:
            enabled = self.entry.enabled()
            self.desktop.setChecked(enabled)
            self.desktop.setEnabled(True)
            self.desktop_status.setText('Enabled for the next desktop login.' if enabled else 'Desktop startup is off.')
        except (OSError, ValueError) as error:
            self.desktop.setEnabled(False)
            self.desktop_status.setText(str(error))
        finally:
            self.desktop.blockSignals(False)

    def set_desktop(self, enabled):
        try:
            self.entry.set_enabled(enabled)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Cannot change desktop startup', str(error))
        self.load_desktop()

    def save_mice(self):
        try:
            config = self.store.read()
            config.startup_models = [m for m in MODELS if self.mice[m].isChecked()]
            self.store.save(config, expected_revision=config.revision)
            self.result.setText('Saved. Applies at the next service start; current software control is unchanged.')
            self.saved.emit()
        except (OSError, ValueError) as error:
            self.result.setText('Not saved: ' + str(error))

    def save_stop(self):
        try:
            chord = '+'.join((*[mod for mod, box in self.stop_mods.items() if box.isChecked()],
                              self.stop_key.currentText()))
            config = self.store.read()
            config.emergency_shortcut = StopShortcut.parse(chord).label
            self.store.save(config, expected_revision=config.revision)
            self.stop_result.setText('Saved ' + config.emergency_shortcut + '. Stop and restart the background service to apply; no desktop binding changed now.')
            self.saved.emit()
        except (OSError, ValueError) as error:
            self.stop_result.setText('Not saved: ' + str(error))
