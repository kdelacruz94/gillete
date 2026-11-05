"""Native service controls; opening this panel never enables a mouse."""

import asyncio
import sys

from PySide6.QtCore import QProcess, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .gui_hardware import HardwareJob
from .model import MODELS
from .service import request


class ServicePanel(QWidget):
    updated = Signal(object)
    command_finished = Signal(str, object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.job = None
        self.last = None
        self.pending = []
        layout = QVBoxLayout(self)
        label = QLabel('Software control applies program profiles, macros, turbo and launches.\n'
                       'Suspend any other remapper for a mouse before enabling it here. Stored bindings are preserved.\n'
                       'Emergency stop: Ctrl+Alt+Pause. Live remapping is still undergoing hardware validation.')
        label.setWordWrap(True)
        layout.addWidget(label)
        tools = QHBoxLayout()
        self.start_button = QPushButton('Start background service')
        self.start_button.clicked.connect(self.start_service)
        tools.addWidget(self.start_button)
        stop = QPushButton('Stop all software actions')
        stop.clicked.connect(lambda: self.send('stop-actions'))
        tools.addWidget(stop)
        quit_button = QPushButton('Stop background service')
        quit_button.clicked.connect(lambda: self.send('shutdown'))
        tools.addWidget(quit_button)
        layout.addLayout(tools)
        self.labels, self.enable, self.disable = {}, {}, {}
        for model, name in zip(MODELS, ('Naga V2 HyperSpeed', 'Naga V3 Pro')):
            row = QHBoxLayout()
            self.labels[model] = QLabel(name + ' — disabled')
            self.labels[model].setWordWrap(True)
            row.addWidget(self.labels[model], 1)
            for text, target, action in (('Enable software control', self.enable, 'enable'),
                                         ('Disable', self.disable, 'disable')):
                target[model] = QPushButton(text)
                target[model].setEnabled(False)
                target[model].clicked.connect(lambda _checked=False, m=model, a=action: self.send(a, m))
                row.addWidget(target[model])
            layout.addLayout(row)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        layout.addWidget(self.info)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def start_service(self):
        ok, _ = QProcess.startDetached(sys.executable, ['-m', 'gillete.cli', '--config', str(self.store.path), 'daemon'])
        self.info.setPlainText('Starting service… Mice remain disabled.' if ok else 'Could not start the service.')

    def poll(self):
        self.send('status', quiet=True)

    def send(self, command, model=None, quiet=False, profile=None):
        if self.job is not None:
            if not quiet:
                self.pending.append((command, model, quiet, profile))
            return
        self.job = HardwareJob(lambda: asyncio.run(request(command, model=model, profile=profile)), self)
        self.job.succeeded.connect(lambda data: self.succeeded(command, data))
        self.job.failed.connect(lambda error: self.failed(error, quiet))
        self.job.finished.connect(self.finished)
        self.job.start()

    def finished(self):
        self.job.deleteLater()
        self.job = None
        if self.pending:
            command, model, quiet, profile = self.pending.pop(0)
            self.send(command, model, quiet, profile)

    def succeeded(self, command, data):
        self.status(data)
        self.command_finished.emit(command, data)

    def failed(self, error, quiet):
        if quiet:
            self.last = None
            self.start_button.setEnabled(True)
            for model in MODELS:
                self.enable[model].setEnabled(False)
                self.disable[model].setEnabled(False)
                self.labels[model].setText(model.replace('_', ' ').title() + ' — service status unavailable')
            self.updated.emit(None)
        else:
            self.info.setPlainText(error)

    def status(self, data):
        self.last = data
        self.start_button.setEnabled(False)
        lines = ['Focus monitoring: ' + ('ready' if data['focus_available'] else data['focus_error'] or 'unavailable'),
                 'Suspend monitoring: ' + ('ready' if data['suspend_monitor'] else 'unavailable')]
        for model, name in zip(MODELS, ('Naga V2 HyperSpeed', 'Naga V3 Pro')):
            state = data['devices'][model]
            self.labels[model].setText(f"{name} — {'active' if state['active'] else 'starting' if state['requested'] else 'disabled'} · {state['mode']}"
                                       + (f" · profile {state['profile']}" if state['profile'] else ''))
            self.enable[model].setEnabled(not state['requested'])
            self.disable[model].setEnabled(state['requested'] or state['active'])
            if state['error']:
                lines.append(f"{name}: {state['error']}")
        if data['configuration_error']:
            lines.append('Configuration: ' + data['configuration_error'])
        self.info.setPlainText('\n'.join(lines))
        self.updated.emit(data)

    def shutdown_ui(self):
        self.timer.stop()
        self.pending.clear()
        if self.job is not None:
            self.job.wait()
