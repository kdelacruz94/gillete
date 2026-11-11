"""Dedicated foreground key observation window; no hardware access/injection."""

import argparse
from pathlib import Path
import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .onboard import durable_json


class Pad(QWidget):
    def __init__(self, output, ready):
        super().__init__()
        self.output, self.ready_path = output, ready
        self.events, self.closed, self.started = [], False, False
        self.unexpected_keys = False
        self.last_active = None
        self.setWindowTitle('Gillete native keyboard sequence test')
        self.resize(820, 530)
        layout = QVBoxLayout(self)
        self.status = QLabel('Preparing native test. Keep the mouse awake and wait for READY.')
        layout.addWidget(self.status)
        instructions = QLabel('After READY: switch the V3 off, wait two seconds, switch it back to 2.4 GHz, then click this window.\n'
                              '1. Tap side 12: Ctrl+K, release Ctrl, then M.\n'
                              '2. Hold ring, tap side 12, release ring: F24 three times.\n'
                              '3. Tap side 11: F24 once.\n'
                              '4. Hold ring, tap side 11, release ring: F24 once.\n'
                              'Wait one second between combinations. Keep this window focused.\n'
                              'Then confirm completing the off/on cycle and all four combinations in chat.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        cancel = QPushButton('Cancel and restore original mappings')
        cancel.clicked.connect(self.close)
        layout.addWidget(cancel)
        QApplication.instance().installEventFilter(self)
        self.duration = QTimer(self)
        self.duration.setSingleShot(True)
        self.duration.timeout.connect(self.close)
        self.duration.start(240000)
        self.watch = QTimer(self)
        self.watch.timeout.connect(self.tick)
        self.watch.start(100)
        self.save()

    def save(self):
        active = self.isActiveWindow()
        self.last_active = active
        durable_json(self.output, {'version': 1, 'active': active, 'closed': self.closed,
                                  'ready': self.started, 'events': self.events, 'unexpected_keys': self.unexpected_keys})

    def tick(self):
        if not self.started and self.ready_path.exists():
            self.started = True
            self.events.clear()
            self.unexpected_keys = False
            self.status.setText('READY — click this window before pressing side buttons. Three minutes remain.')
            self.duration.start(180000)
            self.save()
        elif self.last_active != self.isActiveWindow(): self.save()

    def eventFilter(self, watched, event):
        if self.isActiveWindow() and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            names = {Qt.Key.Key_Control: 'Ctrl', Qt.Key.Key_K: 'K', Qt.Key.Key_M: 'M', Qt.Key.Key_F24: 'F24'}
            if self.started and event.key() in names:
                self.events.append({'key': names[event.key()], 'down': event.type() == QEvent.Type.KeyPress,
                                    'modifiers': event.modifiers().value, 'repeat': event.isAutoRepeat(),
                                    't': time.monotonic()})
                self.events = self.events[-100:]
                self.log.append(f'{names[event.key()]} {"down" if event.type() == QEvent.Type.KeyPress else "up"}')
                self.save()
            elif self.started:
                self.unexpected_keys = True
                self.save()
            return True  # Do not execute editing shortcuts in the test widget.
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.closed = True
        self.watch.stop()
        self.duration.stop()
        self.save()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ready', type=Path, required=True)
    args = parser.parse_args()
    QApplication.setDesktopFileName('org.gillete.NativeSequenceTest')
    app = QApplication([])
    pad = Pad(args.output, args.ready)
    pad.show()
    try: return app.exec()
    finally:
        import shiboken6
        shiboken6.delete(pad)


if __name__ == '__main__':
    raise SystemExit(main())
