"""Focused key-check window for physical acceptance tests; logs JSON lines.

Usage: .venv/bin/python tools/keycheck_window.py LOG.jsonl "Window title"

Records key down/up (with modifiers, autorepeat and scan code), mouse buttons,
wheel deltas and focus changes with monotonic timestamps, so a test checks the
desktop's actual result instead of a description. The title matters: a title of
"World of Warcraft" matches that profile's rule. Its app ID is gillete-keycheck.
Opens no mouse or input device. Close the window to finish.
"""

import json
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

MODS = [(Qt.KeyboardModifier.ShiftModifier, 'Shift'), (Qt.KeyboardModifier.ControlModifier, 'Ctrl'),
        (Qt.KeyboardModifier.AltModifier, 'Alt'), (Qt.KeyboardModifier.MetaModifier, 'Super')]


def mods(event):
    return [name for flag, name in MODS if event.modifiers() & flag]


class Logger(QWidget):
    def __init__(self, path, title):
        super().__init__()
        self.file = open(path, 'a', buffering=1)
        self.setWindowTitle(title)
        self.lines = []
        self.label = QLabel('Focus this window and press the buttons I ask for.')
        self.label.setFont(QFont('monospace', 14))
        self.label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout = QVBoxLayout(self)
        header = QLabel(f'Gillete key check — "{title}" — close the window to finish')
        header.setFont(QFont('sans', 16, QFont.Weight.Bold))
        layout.addWidget(header)
        layout.addWidget(self.label, 1)
        self.resize(900, 600)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def log(self, **record):
        record['t'] = round(time.monotonic(), 3)
        self.file.write(json.dumps(record) + '\n')
        text = ' '.join(f'{k}={v}' for k, v in record.items() if k != 't')
        self.lines = (self.lines + [text])[-22:]
        self.label.setText('\n'.join(self.lines))

    def key(self, kind, event):
        name = QKeySequence(event.key()).toString() or str(event.key())
        self.log(ev=kind, key=name, mods=mods(event), repeat=event.isAutoRepeat(), scan=event.nativeScanCode())

    def keyPressEvent(self, event):
        self.key('down', event)

    def keyReleaseEvent(self, event):
        self.key('up', event)

    def mousePressEvent(self, event):
        self.log(ev='press', button=event.button().name, mods=mods(event))

    def mouseReleaseEvent(self, event):
        self.log(ev='release', button=event.button().name, mods=mods(event))

    def wheelEvent(self, event):
        delta = event.angleDelta()
        self.log(ev='wheel', x=delta.x(), y=delta.y(), mods=mods(event))

    def focusInEvent(self, event):
        self.log(ev='focus-in')

    def focusOutEvent(self, event):
        self.log(ev='focus-out')

    def event(self, event):
        # Deliver Tab/Backtab as ordinary keys instead of focus navigation.
        if event.type() == event.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(event)
            return True
        if event.type() == event.Type.KeyRelease and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyReleaseEvent(event)
            return True
        return super().event(event)


if __name__ == '__main__':
    app = QApplication(sys.argv[:1])
    app.setDesktopFileName('gillete-keycheck')
    window = Logger(sys.argv[1], sys.argv[2])
    window.show()
    app.exec()
