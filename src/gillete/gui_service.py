"""Native service controls; opening this panel never enables a mouse."""

import asyncio
import sys

from PySide6.QtCore import QProcess, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .gui_hardware import HardwareJob
from .model import MODELS
from .service import request
from .profile_selection import Selection, select as select_profile


class ServicePanel(QWidget):
    updated = Signal(object)
    command_finished = Signal(str, object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.job = None
        self.last = None
        self.last_error = ''
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
        # Repeated desktop/manual launches reuse the current daemon. Only an
        # absent socket starts a process; timeouts and config conflicts do not.
        self.send('ensure-service')

    def spawn_service(self):
        ok, _ = QProcess.startDetached(sys.executable, ['-m', 'gillete.cli', '--config', str(self.store.path), 'daemon'])
        self.info.setPlainText('Starting service… Saved startup mouse choices will apply.' if ok else 'Could not start the service.')

    def poll(self):
        self.send('status', quiet=True)

    def send(self, command, model=None, quiet=False, profile=None):
        if self.job is not None:
            if not quiet:
                self.pending.append((command, model, quiet, profile))
            return
        async def run():
            if command == 'pin':
                return await select_profile(self.store, model, None if profile is None else profile)
            try:
                return await request('status' if command == 'ensure-service' else command,
                                     model=model, profile=profile, config_path=self.store.path)
            except (FileNotFoundError, ConnectionRefusedError):
                if command == 'ensure-service':
                    return None
                raise
        self.job = HardwareJob(lambda: asyncio.run(run()), self)
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
        if command == 'ensure-service' and data is None:
            self.spawn_service()
            return
        if command == 'pin' and isinstance(data, Selection):
            if data.status is not None:
                self.status(data.status)
            else:
                self.last = None
                self.last_error = ''
                self.start_button.setEnabled(True)
                for model in MODELS:
                    self.enable[model].setEnabled(False)
                    self.disable[model].setEnabled(False)
                    self.labels[model].setText(model.replace('_', ' ').title() + ' — service not running')
                self.updated.emit(None)
                self.info.setPlainText('Profile preference saved locally. The background service is not running; software control was not activated.')
            self.command_finished.emit(command, data.status)
            return
        self.status(data)
        self.command_finished.emit(command, data)

    def failed(self, error, quiet):
        self.last_error = error
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
        self.last_error = ''
        self.start_button.setEnabled(False)
        lines = ['Focus monitoring: ' + ('ready' if data['focus_available'] else data['focus_error'] or 'unavailable'),
                 'Suspend monitoring: ' + ('ready' if data['suspend_monitor'] else 'unavailable')]
        for model, name in zip(MODELS, ('Naga V2 HyperSpeed', 'Naga V3 Pro')):
            state = data['devices'][model]
            retry = state.get('retry_in_ms', 0)
            phase = ('active' if state['active'] else
                     f'retrying in {(retry + 999) // 1000}s' if state['requested'] and retry else
                     'waiting to reconnect' if state['requested'] and state['error'] else
                     'starting' if state['requested'] else
                     'waiting for desktop' if model in data.get('startup_pending', []) else 'disabled')
            self.labels[model].setText(f"{name} — {phase} · {state['mode']}"
                                       + (f" · profile {state['profile']}" if state['profile'] else ''))
            self.enable[model].setEnabled(not state['requested'])
            self.disable[model].setEnabled(state['requested'] or state['active'])
            if state['error']:
                lines.append(f"{name}: {state['error']}")
            if state.get('action_error'):
                lines.append(f"{name}: {state['action_error']}")
        if data['configuration_error']:
            lines.append('Configuration: ' + data['configuration_error'])
        self.info.setPlainText('\n'.join(lines))
        self.updated.emit(data)

    def shutdown_ui(self):
        self.timer.stop()
        self.pending.clear()
        if self.job is not None:
            self.job.wait()
