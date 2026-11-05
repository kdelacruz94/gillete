"""Foreground-only input test window. Does not open hardware or activate mappings."""

import argparse
from pathlib import Path
import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .hardware import read_journal
from .model import MODELS
from .onboard import durable_json
from .validation_plan import instructions


class Pad(QWidget):
    def __init__(self, path, *, model=MODELS[1], title='Gillete input test', seconds=300, ready=None):
        super().__init__()
        self.path = path
        self.events = []
        self.model, self.seconds, self.ready_path = model, seconds, ready
        self.setWindowTitle(title)
        self.resize(780, 540)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        self.status = QLabel('Preparing software control. Wait for READY before testing.')
        self.instructions = QLabel(instructions(model))
        self.instructions.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(self.instructions)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        finish = QPushButton('Finish test and restore normal mouse mode')
        finish.clicked.connect(self.close)
        layout.addWidget(finish)
        QApplication.instance().installEventFilter(self)
        self.save()
        self.duration = QTimer(self)
        self.duration.setSingleShot(True)
        self.duration.timeout.connect(self.close)
        self.preparation = QTimer(self)
        self.preparation.setSingleShot(True)
        self.preparation.timeout.connect(self.close)
        self.readiness = QTimer(self)
        self.readiness.timeout.connect(self.check_ready)
        if ready is not None:
            self.preparation.start(90_000)
            self.readiness.start(100)
        else:
            self.status.setText('Input observation only; no software-control readiness signal.')
            self.duration.start(seconds * 1000)

    def check_ready(self):
        try:
            document = read_journal(self.ready_path)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self.close()
            return
        if (document.get('model') != self.model or document.get('title') != self.windowTitle()
                or document.get('seconds') != self.seconds):
            self.close()
            return
        self.readiness.stop()
        self.preparation.stop()
        self.status.setText(f'READY — software test active. Up to {self.seconds} seconds remain.')
        self.duration.start(self.seconds * 1000)

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
        self.readiness.stop()
        self.preparation.stop()
        self.duration.stop()
        self.save()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--model', choices=MODELS, default=MODELS[1])
    parser.add_argument('--title', default='Gillete input test')
    parser.add_argument('--ready', type=Path)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 600:
        parser.error('Duration must be 30..600 seconds')
    QApplication.setDesktopFileName('org.gillete.InputTest')
    app = QApplication([])
    pad = Pad(args.output, model=args.model, title=args.title, seconds=args.seconds, ready=args.ready)
    pad.show()
    try:
        return app.exec()
    finally:
        import shiboken6
        shiboken6.delete(pad)


if __name__ == '__main__':
    raise SystemExit(main())
