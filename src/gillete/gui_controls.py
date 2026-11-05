"""Native control selector for the shared 12-button Naga layouts."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QGroupBox,
                              QLabel, QPushButton, QVBoxLayout, QWidget)

from .model import MODEL_CONTROLS, MODELS
from .hypershift import resolve_action
from .shortcuts import describe


class ControlSelector(QWidget):
    edit_requested = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(350)
        self.buttons = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel('Click a control to edit its assignment.'))
        self.layer = QComboBox()
        self.layer.addItem('Edit normal layer', False)
        self.layer.addItem('Edit HyperShift layer', True)
        layout.addWidget(self.layer)
        top = QGroupBox('Top, wheel and extra controls')
        grid = QGridLayout(top)
        for control, label, row, column, row_span, column_span in (
                ('left_click', 'Left click', 0, 0, 2, 1),
                ('wheel_up', 'Scroll ↑', 0, 1, 1, 1),
                ('right_click', 'Right click', 0, 2, 2, 1),
                ('wheel_click', 'Wheel click', 1, 1, 1, 1),
                ('wheel_tilt_left', 'Tilt ←', 2, 0, 1, 1),
                ('wheel_down', 'Scroll ↓', 2, 1, 1, 1),
                ('wheel_tilt_right', 'Tilt →', 2, 2, 1, 1),
                ('dpi_up', 'Front index', 3, 0, 1, 1),
                ('dpi_down', 'Rear index', 4, 0, 1, 1),
                ('top_front', 'Top front', 3, 1, 1, 1),
                ('top_rear', 'Top rear', 4, 1, 1, 1),
                ('ring_finger', 'Ring finger', 3, 2, 2, 1),
                ('profile_button', 'Underside profile button', 5, 0, 1, 3)):
            button = self.add_control(control, label)
            grid.addWidget(button, row, column, row_span, column_span)
        layout.addWidget(top)
        side = QGroupBox('12-button side plate')
        grid = QGridLayout(side)
        for i in range(12):
            grid.addWidget(self.add_control(f'side_{i + 1}', str(i + 1)), i // 3, i % 3)
        layout.addWidget(side)
        self.assignment = QLabel()
        self.assignment.setWordWrap(True)
        layout.addWidget(self.assignment)
        layout.addStretch()
        self.current_model = MODELS[0]
        self.profile = None
        self.stored = None
        self.selected = None
        self.layer.currentIndexChanged.connect(self.update_assignment)

    def add_control(self, control, label):
        button = QPushButton(label)
        button.setMinimumHeight(32)
        button.setCheckable(True)
        button.setAccessibleName(control.replace('_', ' '))
        self.group.addButton(button)
        self.buttons[control] = button
        button.clicked.connect(lambda _checked=False, c=control: self.activate(c))
        return button

    def activate(self, control):
        self.select(control)
        self.edit_requested.emit(control, self.layer.currentData())

    def select(self, control):
        if control in MODEL_CONTROLS[self.current_model]:
            self.selected = control
            self.buttons[control].setChecked(True)
            self.update_assignment()

    def refresh(self, model, profile, stored=None):
        self.current_model, self.profile = model, profile
        self.stored = stored
        for control, button in self.buttons.items():
            supported = control in MODEL_CONTROLS[model]
            button.setVisible(supported)
            if supported:
                button.setToolTip(f'{control.replace("_", " ").title()}\n'
                                  f'Normal: {self.describe_assignment(control, False)}\n'
                                  f'HyperShift: {self.describe_assignment(control, True)}')
        if self.selected not in MODEL_CONTROLS[model]:
            self.selected = 'side_1'
        self.select(self.selected)

    def describe_assignment(self, control, shifted):
        action = self.profile.resolve(self.current_model, control, shifted)
        resolved = resolve_action(self.profile, self.current_model, control, shifted, self.stored)
        if resolved is not None and resolved != action and resolved.kind == 'hypershift':
            return 'Stored HyperShift trigger (hold)'
        return describe(action)

    def update_assignment(self):
        if self.profile is not None and self.selected in MODEL_CONTROLS[self.current_model]:
            name = self.selected.replace('_', ' ').title()
            description = self.describe_assignment(self.selected, self.layer.currentData())
            self.assignment.setText(f'{name}: {description}')
