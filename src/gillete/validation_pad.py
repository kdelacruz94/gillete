"""Foreground-only input test window. Does not open hardware or activate mappings."""

import argparse
from pathlib import Path
import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .onboard import durable_json


class Pad(QWidget):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.events = []
        self.setWindowTitle('Gillete input test')
        self.resize(780, 540)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        instructions = QLabel('Wait for READY in chat before testing.\n\n'
                             '1. Tap side 12: F24. Hold the ring-finger button and tap side 12: F23.\n'
                             '2. Tap side 11: Ctrl+K, then M.\n'
                             '3. Rear button behind the wheel: toggle repeated 1 on, then off.\n'
                             '4. Start repeating 1 again, then click another window: repetition must stop.\n\n'
                             'Emergency stop: Ctrl+Alt+Pause. Close this test window when finished.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        finish = QPushButton('Finish test and restore normal mouse mode')
        finish.clicked.connect(self.close)
        layout.addWidget(finish)
        QApplication.instance().installEventFilter(self)
        self.save()

    def save(self):
        durable_json(self.path, {'version': 1, 'foreground_only': True, 'events': self.events})

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and self.isActiveWindow():
            key = event.key()
            names = {Qt.Key.Key_F24: 'F24', Qt.Key.Key_F23: 'F23', Qt.Key.Key_Control: 'Ctrl',
                     Qt.Key.Key_K: 'K', Qt.Key.Key_M: 'M', Qt.Key.Key_1: '1'}
            try:
                fallback = Qt.Key(key).name.removeprefix('Key_')
            except ValueError:
                fallback = f'Qt key {int(key)}'
            name = names.get(key, fallback)
            direction = 'down' if event.type() == QEvent.Type.KeyPress else 'up'
            self.events.append({'t': time.monotonic(), 'key': name, 'direction': direction, 'repeat': event.isAutoRepeat(),
                                'qt_key': int(key), 'scan': event.nativeScanCode(), 'keysym': event.nativeVirtualKey()})
            self.events = self.events[-5000:]
            self.log.append(f'{name} {direction}')
            self.save()
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.save()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    QApplication.setDesktopFileName('org.gillete.InputTest')
    app = QApplication([])
    pad = Pad(args.output)
    pad.show()
    QTimer.singleShot(args.seconds * 1000, pad.close)
    try:
        return app.exec()
    finally:
        import shiboken6
        shiboken6.delete(pad)


if __name__ == '__main__':
    raise SystemExit(main())
