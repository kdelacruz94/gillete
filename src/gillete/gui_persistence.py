"""User-paced power-cycle and receiver reconnect checks, without setters."""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .devices import discover
from .gui_hardware import HardwareJob
from .persistence import Verification
from .protocol import DeviceStatusError, DeviceUnavailable


class PersistenceDialog(QDialog):
    def __init__(self, device, source, directory, parent=None, *, seconds=300):
        super().__init__(parent)
        self.verification = Verification(device, source, directory)
        self.job = None
        self.pending_close = None
        self.retry = None
        self.seconds = seconds
        self.deadline = None
        self.setWindowTitle('Verify saved bindings after restart')
        self.resize(720, 370)
        layout = QVBoxLayout(self)
        heading = QLabel(f'{device.name} — {device.transport}\n'
                         'This check reads saved and active button assignments. It changes no mouse settings.\n'
                         'Stop software control first. You will power-cycle the mouse, then unplug and '
                         'reconnect its receiver to the same USB port.')
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.status = QLabel('Choose Start when the mouse is awake. Leave its receiver connected for the first step.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status, 1)
        self.time_left = QLabel('')
        layout.addWidget(self.time_left)
        note = QLabel('Readback proves the recorded binding values survived these steps. '
                      'It does not test physical key output, macro timing, device settings or every possible assignment.\n'
                      'Closing this check leaves the saved assignments in place. Use the original recovery journal to restore them.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.receipt = QLabel('')
        self.receipt.setTextFormat(Qt.TextFormat.PlainText)
        self.receipt.setWordWrap(True)
        self.receipt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.receipt)
        row = QHBoxLayout()
        self.action = QPushButton('Start read-only check')
        self.action.clicked.connect(self.advance)
        row.addWidget(self.action)
        self.close_button = QPushButton('Cancel')
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)

    def advance(self):
        if self.job is not None:
            return
        operation = self.retry or {'new': self.verification.prepare,
                                   'awaiting-power-cycle': self.verification.power_cycle,
                                   'awaiting-reconnect': self.verification.reconnect}.get(self.verification.phase)
        if operation is None:
            return
        if self.deadline is None:
            self.deadline = time.monotonic() + self.seconds
            self.timer.start()
        self.retry = None
        self.action.setEnabled(False)
        self.status.setText('Reading and comparing bindings… Keep this mouse awake. No assignments are being changed.')
        def read():
            try:
                operation()
            except (DeviceUnavailable, DeviceStatusError) as error:
                if isinstance(error, DeviceStatusError) and error.status not in (1, 4):
                    raise
                # Retrying a getter is explicit and never resubmits a setter.
                return str(error)
            return None
        self.job = HardwareJob(read, self)
        self.job.succeeded.connect(lambda error: self.completed(error, operation))
        self.job.failed.connect(self.failed)
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def completed(self, error, operation):
        if self.pending_close:
            return
        if error:
            # A failed initial read may have claimed its new receipt directory.
            # Start a new check instead of reusing an incomplete baseline.
            if self.verification.phase == 'new':
                self.failed(error)
                return
            self.retry = operation
            self.status.setText('Read incomplete: ' + error + '\nMove the mouse to wake it, then retry this read.')
            self.action.setText('Retry read')
            self.action.setEnabled(True)
            return
        self.render()

    def job_finished(self):
        self.job.deleteLater()
        self.job = None
        if self.pending_close:
            self.close_check(self.pending_close)

    def render(self):
        phase = self.verification.phase
        if self.verification.owned:
            self.receipt.setText('Verification receipt: ' + str(self.verification.path))
        text = {
            'awaiting-power-cycle': 'READY — Switch this mouse OFF, wait a couple of seconds, then turn it back to 2.4 GHz. '
                                    'Move it to wake it. Keep the receiver plugged in, then confirm below.',
            'awaiting-disconnect': 'Power-cycle readback matches. Now unplug this receiver. '
                                   'Wait here until the check reports that it has disappeared.',
            'awaiting-reconnect': 'Receiver disconnect observed. Reconnect it to the same USB port, '
                                  'then move the mouse to wake it and check its bindings.',
            'verified-readback': 'VERIFIED — Saved and active binding records match after the reported mouse power cycle '
                                 'and observed receiver replug. Physical button output still needs its separate test.',
        }.get(phase)
        if text:
            self.status.setText(text)
        self.action.setText('I power-cycled the mouse — check' if phase == 'awaiting-power-cycle'
                            else 'Receiver reconnected — check')
        self.action.setEnabled(phase == 'awaiting-power-cycle')
        if phase == 'verified-readback':
            self.timer.stop()
            self.time_left.clear()
            self.action.setVisible(False)
            self.close_button.setText('Close')

    def tick(self):
        if self.deadline is None:
            return
        remaining = self.deadline - time.monotonic()
        self.time_left.setText(f'Check time remaining: {max(0, int(remaining))} seconds')
        if remaining <= 0:
            self.close_check('timed-out')
            return
        if self.job is not None or self.retry:
            return
        try:
            phase = self.verification.phase
            present = self.verification.observe(discover())
            if phase != self.verification.phase:
                self.render()
            if self.verification.phase == 'awaiting-reconnect':
                self.action.setEnabled(present)
        except (OSError, ValueError) as error:
            self.failed(str(error))

    def failed(self, error):
        if self.pending_close:
            return
        self.timer.stop()
        try:
            self.verification.finish('failed', error)
        except OSError as receipt_error:
            error += '\nCould not update the receipt: ' + str(receipt_error)
        self.status.setText('Verification failed: ' + error + '\nNo assignments were changed by this check.')
        if self.verification.owned:
            self.receipt.setText('Verification receipt: ' + str(self.verification.path))
        self.action.setEnabled(False)
        self.close_button.setText('Close')

    def close_check(self, outcome):
        if self.job is not None:
            self.pending_close = outcome
            self.timer.stop()
            self.action.setEnabled(False)
            self.status.setText('Finishing the current read before closing. No further verification step will run.')
            return
        cancelled_read = self.pending_close is not None
        self.pending_close = None
        if cancelled_read or self.verification.phase not in ('new', 'verified-readback', 'failed', 'cancelled', 'timed-out'):
            try:
                self.verification.finish(outcome)
            except OSError as error:
                self.status.setText('Could not update verification receipt: ' + str(error))
        elif self.verification.phase == 'new' and self.verification.owned:
            try:
                self.verification.finish(outcome)
            except OSError as error:
                self.status.setText('Could not update verification receipt: ' + str(error))
        self.timer.stop()
        super().reject()

    def reject(self):
        self.close_check('cancelled')

    def closeEvent(self, event):
        if self.job is not None:
            self.close_check('cancelled')
            event.ignore()
        else:
            self.reject()
            event.accept()
