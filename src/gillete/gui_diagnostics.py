"""Native diagnostics using sysfs/permission metadata and existing service status."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                              QPushButton, QTableWidget, QTableWidgetItem,
                              QTabWidget, QVBoxLayout, QWidget)

from .devices import discover
from .diagnostics import device_key, feature_validation, findings, label


class DetailsTable(QTableWidget):
    def __init__(self, columns):
        super().__init__(0, columns)
        self.fit = QTimer(self)
        self.fit.setSingleShot(True)
        self.fit.timeout.connect(self.resizeRowsToContents)
        self.horizontalHeader().sectionResized.connect(lambda *_: self.fit.start(0))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        # Hidden tabs were populated before their final viewport width existed.
        self.fit.start(0)


class DiagnosticsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices = []
        self.discovery_error = ''
        self.service, self.service_error = None, ''
        self.uinput_access = None
        self.last_report = None
        layout = QVBoxLayout(self)
        description = QLabel('Connection checks read device listings and permissions. They do not wake the mouse, '
                             'read its settings, grab input or activate remapping.')
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.selector = QComboBox()
        row.addWidget(self.selector, 1)
        self.refresh_button = QPushButton('Refresh connection checks')
        self.refresh_button.clicked.connect(self.refresh_devices)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        tabs = QTabWidget()
        self.checks = self.table(('Check', 'Status', 'Details'))
        tabs.addTab(self.checks, 'Connection and service')
        self.nodes = self.table(('Interface / node', 'Read / write', 'Driver'))
        tabs.addTab(self.nodes, 'Device permissions')
        validation = QWidget()
        validation_layout = QVBoxLayout(validation)
        note = QLabel('These results describe development testing for this transport. '
                      'They do not verify the connected unit or its current bindings.')
        note.setWordWrap(True)
        validation_layout.addWidget(note)
        self.capabilities = self.table(('Feature', 'Validation', 'Evidence / remaining work'))
        validation_layout.addWidget(self.capabilities)
        tabs.addTab(validation, 'Feature validation')
        layout.addWidget(tabs, 1)
        self.selector.currentIndexChanged.connect(self.render)

    def table(self, headings):
        table = DetailsTable(len(headings))
        table.setHorizontalHeaderLabels(headings)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setWordWrap(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(len(headings) - 1, QHeaderView.ResizeMode.Stretch)
        return table

    def refresh_devices(self):
        previous = self.selector.currentData()
        previous = device_key(previous) if previous is not None else None
        try:
            devices = discover()
            uinput_access = os.access('/dev/uinput', os.W_OK)
        except OSError as error:
            # Never retain a formerly accessible/active device after a failed refresh.
            self.devices = []
            self.discovery_error = str(error)
            self.selector.clear()
            self.render()
            return
        self.devices, self.uinput_access = devices, uinput_access
        self.discovery_error = ''
        self.selector.blockSignals(True)
        self.selector.clear()
        for device in devices:
            self.selector.addItem(label(device), device)
        index = next((i for i, device in enumerate(devices) if device_key(device) == previous), 0)
        self.selector.setCurrentIndex(index if devices else -1)
        self.selector.blockSignals(False)
        self.render()

    def set_service_state(self, state, error=''):
        self.service, self.service_error = state, error
        self.render()

    def fill(self, table, rows):
        table.setRowCount(len(rows))
        for row, cells in enumerate(rows):
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(row, column, item)
        table.resizeRowsToContents()

    def render(self):
        device = self.selector.currentData()
        if device is None:
            self.last_report = None
            for table in (self.checks, self.nodes, self.capabilities):
                table.setRowCount(0)
            self.summary.setText('Connection discovery failed: ' + self.discovery_error if self.discovery_error else
                                 'No supported Naga transport is listed. Connect a receiver or cable, then refresh.')
            return
        checks = findings(device, self.devices, uinput_access=self.uinput_access,
                          service=self.service, service_error=self.service_error)
        capabilities = feature_validation(device.product_id)
        def access(value):
            return 'yes' if value is True else 'no' if value is False else 'unknown'
        nodes = [(f"{n['number']} · {n['path']}",
                  f"{access(n.get('readable'))} / {access(n.get('writable'))}", n.get('driver') or 'Unknown / unbound')
                 for n in device.interfaces]
        report = device_key(device), checks, capabilities, nodes
        if report == self.last_report:
            return
        self.last_report = report
        self.summary.setText(f'{device.name} · {device.transport} · 1532:{device.product_id:04x}\n'
                             'Permissions reflect the last connection refresh; service status updates while the editor is open.')
        self.fill(self.checks, [(r.name, r.status, r.detail) for r in checks])
        self.fill(self.capabilities, [(r.name, r.status, r.detail) for r in capabilities])
        self.fill(self.nodes, nodes)
