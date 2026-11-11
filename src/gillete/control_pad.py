"""Guided control/layer observations; opens no input device or service socket."""

import argparse
import json
from pathlib import Path
import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .control_validation import ALTERNATE, LABELS, Trial, recipe, title_for, validate_packet
from .hardware import read_journal
from .model import MODELS
from .onboard import durable_json


def key_name(key):
    for qt_key, label in ((Qt.Key.Key_Shift, 'Shift'), (Qt.Key.Key_Control, 'Ctrl'), (Qt.Key.Key_Alt, 'Alt')):
        if key == qt_key:
            return label
    if Qt.Key.Key_F13 <= key <= Qt.Key.Key_F24:
        return f'F{13 + key - Qt.Key.Key_F13}'
    return f'Qt key {int(key)}'


class ControlPad(QWidget):
    def __init__(self, path, state_path, ready_path, *, model, title, seconds, nonce):
        super().__init__()
        if path.exists():
            raise ValueError('Choose a new control-coverage report')
        self.path, self.state_path, self.ready_path = path, state_path, ready_path
        self.model, self.base_title, self.seconds, self.nonce = model, title, seconds, nonce
        self.steps = recipe(model)['steps']
        self.index, self.trial, self.epoch = 0, None, None
        self.keys_held = set()
        self.started_at = None
        self.preparing_since = time.monotonic()
        self.document = {'version': 1, 'model': model, 'nonce': nonce,
                         'status': 'preparing', 'passed': [], 'failed_attempts': []}
        self.failure_recorded = False
        self.setWindowTitle(title)
        self.resize(820, 560)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        self.status = QLabel('Preparing. Wait for READY before pressing mouse controls.')
        self.status.setWordWrap(True)
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.help = QLabel('Tap and release only the requested control. Keep this window focused.\n'
                          'R retries a failed attempt; Escape finishes and restores normal mode.\n'
                          'Left/right click are test keys here. Use the keyboard to stop.')
        self.help.setWordWrap(True)
        for widget in (self.status, self.prompt, self.help): layout.addWidget(widget)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        finish = QPushButton('Finish and restore (Escape)')
        finish.clicked.connect(self.close)
        layout.addWidget(finish)
        self.persist()
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def persist(self):
        if len(json.dumps(self.document).encode()) > 768 * 1024:
            raise ValueError('Control evidence size limit reached; retain the last partial report')
        durable_json(self.path, self.document)

    def ready(self):
        try:
            ready = read_journal(self.ready_path)
        except FileNotFoundError:
            return False
        if any(ready.get(name) != value for name, value in (
                ('model', self.model), ('title', self.base_title), ('seconds', self.seconds), ('nonce', self.nonce))):
            raise ValueError('Readiness belongs to another test')
        return True

    def poll(self):
        try:
            self.refresh()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.document.update(status='error', error=str(error))
            self.close()

    def refresh(self):
        now = time.monotonic()
        if self.document['status'] == 'complete':
            return
        if self.started_at is None:
            if now - self.preparing_since > 90:
                raise ValueError('Software-control preparation timed out')
            if not self.ready():
                return
            self.started_at = now
            self.document['status'] = 'running'
        if now - self.started_at > self.seconds:
            raise ValueError('Control-coverage time limit reached')
        try:
            packet = read_journal(self.state_path)
        except FileNotFoundError:
            self.status.setText('Waiting for current service evidence…')
            return
        if packet.get('model') != self.model or packet.get('nonce') != self.nonce:
            raise ValueError('Service evidence belongs to another test')
        validate_packet(packet)
        trace = packet['trace']
        if self.epoch is not None and trace['epoch'] != self.epoch:
            raise ValueError('The mouse session restarted; retain this incomplete test and prepare a new one')
        step = self.steps[self.index]
        desired_title = title_for(self.base_title, step['profile'])
        if self.windowTitle() != desired_title:
            self.setWindowTitle(desired_title)
        self.prompt.setText(f'{self.index + 1} / {len(self.steps)} — '
                            + (f'Hold {LABELS[step["trigger"]]}, then ' if step['shifted'] else '')
                            + f'tap and release {LABELS[step["control"]]}.'
                            + (' Then release the HyperShift trigger.' if step['release_trigger'] else ''))
        if self.trial is None:
            if (not self.isActiveWindow() or not packet['focused'] or not packet['active']
                    or packet['focus_pending'] or trace['profile'] != step['profile'] or not 0 <= now - packet['t'] <= 2):
                self.status.setText('Waiting for this window and its current profile. No tap is armed.')
                return
            if self.keys_held or QApplication.keyboardModifiers() or set(trace['held']) - {step['trigger']}:
                self.status.setText('Release the previous control and all keyboard keys before continuing.')
                return
            self.epoch = trace['epoch']
            self.trial = Trial(step, packet, now=now)
            self.failure_recorded = False
            self.status.setText('READY — perform the requested tap.')
            return
        outcome = self.trial.update(packet, now=now)
        if outcome == 'failed':
            self.status.setText(self.trial.error + ' — release keys/buttons, then press R to retry.')
            if not self.failure_recorded:
                self.document['failed_attempts'].append(self.trial.receipt())
                self.failure_recorded = True
                if len(self.document['failed_attempts']) > 100:
                    raise ValueError('Too many failed attempts')
                self.persist()
        elif outcome == 'release-buttons':
            self.status.setText('Key pair observed. Release the HyperShift trigger and remaining buttons.')
        elif outcome == 'passed':
            self.document['passed'].append(self.trial.receipt())
            self.log.append(f'PASS: {LABELS[step["control"]]} — {"HyperShift" if step["shifted"] else "normal"}')
            self.trial = None
            self.status.setText('Preparing the next control…')
            self.index += 1
            if self.index == len(self.steps):
                self.document['status'] = 'complete'
                self.status.setText('All control/layer pairs observed. Waiting for normal-mode restoration.')
                self.prompt.setText('Leave all mouse buttons released.')
                self.timer.stop()
            self.persist()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowDeactivate and watched is self:
            self.keys_held.clear()
            if self.trial is not None:
                self.trial.error = 'The test window lost focus'
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and self.isActiveWindow():
            down = event.type() == QEvent.Type.KeyPress
            if event.key() == Qt.Key.Key_Escape:
                if down and not event.isAutoRepeat(): self.close()
                return True
            if event.key() == Qt.Key.Key_R:
                if down and not event.isAutoRepeat() and self.trial is not None and self.trial.error and not self.keys_held:
                    self.trial = None
                return True
            name = key_name(event.key())
            if not event.isAutoRepeat():
                if down: self.keys_held.add(name)
                else: self.keys_held.discard(name)
            if self.trial is not None:
                modifiers = [label for flag, label in ((Qt.KeyboardModifier.ShiftModifier, 'Shift'),
                    (Qt.KeyboardModifier.ControlModifier, 'Ctrl'), (Qt.KeyboardModifier.AltModifier, 'Alt'),
                    (Qt.KeyboardModifier.MetaModifier, 'Meta'), (Qt.KeyboardModifier.GroupSwitchModifier, 'GroupSwitch'),
                    (Qt.KeyboardModifier.KeypadModifier, 'Keypad')) if event.modifiers() & flag]
                self.trial.key({'t': time.monotonic(), 'key': name, 'direction': 'down' if down else 'up',
                    'modifiers': modifiers, 'repeat': event.isAutoRepeat(), 'qt_key': int(event.key()),
                    'scan': event.nativeScanCode(), 'keysym': event.nativeVirtualKey()})
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.timer.stop()
        if self.document['status'] not in ('complete', 'error'):
            self.document['status'] = 'incomplete'
        if self.trial is not None and not self.failure_recorded:
            self.document['unfinished'] = self.trial.receipt()
        try:
            self.persist()
        except (OSError, ValueError):
            pass  # The controller cannot mistake an older partial file for completion.
        super().closeEvent(event)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--ready', type=Path, required=True)
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--seconds', type=int, default=600)
    args = parser.parse_args(argv)
    if not 30 <= args.seconds <= 600:
        parser.error('Duration must be 30..600 seconds')
    QApplication.setDesktopFileName('org.gillete.ControlTest')
    app = QApplication([])
    pad = ControlPad(args.output, args.state, args.ready, model=args.model, title=args.title,
                     seconds=args.seconds, nonce=args.nonce)
    pad.show()
    try:
        return app.exec()
    finally:
        import shiboken6
        shiboken6.delete(pad)


if __name__ == '__main__':
    raise SystemExit(main())
