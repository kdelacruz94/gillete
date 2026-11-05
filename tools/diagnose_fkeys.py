"""Isolated real Wayland/uinput F23/F24 reproduction; no physical mouse access."""

import argparse
import asyncio
import json

from evdev import ecodes
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel

from gillete.engine import Engine
from gillete.macros import KeyLedger
from gillete.model import Action, Layers, MODELS, Profile
from gillete.runtime import UInputOutput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', action='store_true', help='Remove the engine and send the same Linux key codes directly')
    parser.add_argument('--uncorrected', action='store_true', help='Reproduce the original desktop keymap failure')
    parser.add_argument('--all-function-keys', action='store_true', help='Also check F13–F24 through ordinary bindings')
    args = parser.parse_args()
    if args.uncorrected and args.all_function_keys:
        parser.error('Only the corrected map may replay all function keys')
    QApplication.setDesktopFileName('org.gillete.KeymapDiagnostic')
    app = QApplication([])
    output = UInputOutput('diagnostic')
    events = []
    result = {'error': 'Probe did not finish'}

    class Pad(QLabel):
        def eventFilter(self, watched, event):
            if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.nativeScanCode() in range(ecodes.KEY_F13 + 8, ecodes.KEY_F24 + 9):
                events.append({'key': int(event.key()), 'name': Qt.Key(event.key()).name,
                               'scan': event.nativeScanCode(), 'keysym': event.nativeVirtualKey(),
                               'down': event.type() == QEvent.Type.KeyPress})
                return True
            return super().eventFilter(watched, event)
    pad = Pad('Checking F23 and F24 through the real desktop keymap…\nThis window closes automatically. No mouse settings change.')
    pad.setWindowTitle('Gillete keymap diagnostic')
    pad.resize(620, 150)
    pad.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    app.installEventFilter(pad)
    pad.show()
    profile = Profile('probe', 'Probe', Layers(normal={'side_12': Action('keys', keys=('KEY_F24',)),
                                                     'ring_finger': Action('hypershift', playback='held')},
                                               shifted={'side_12': Action('keys', keys=('KEY_F23',))}))
    engine = Engine(MODELS[1], profile, KeyLedger(output))
    if args.all_function_keys:
        for number in range(13, 25):
            profile.common.normal[f'side_{number - 12}'] = Action('keys', keys=(f'KEY_F{number}',))

    def finish():
        expected = {(int(Qt.Key.Key_F24), True), (int(Qt.Key.Key_F24), False),
                    (int(Qt.Key.Key_F23), True), (int(Qt.Key.Key_F23), False)}
        actual = {(e['key'], e['down']) for e in events}
        if args.all_function_keys:
            expected |= {(int(Qt.Key.Key_F13) + offset, down) for offset in range(12) for down in (True, False)}
        result.clear()
        result.update({'path': 'raw uinput' if args.raw else 'engine → uinput', 'events': events,
                       'expected_f23': int(Qt.Key.Key_F23), 'pass': expected <= actual})
        app.quit()

    def inject():
        if not pad.isActiveWindow():
            result['error'] = 'Probe window is not focused; no keys emitted'
            app.quit()
            return
        if args.raw:
            for key in (range(ecodes.KEY_F13, ecodes.KEY_F24 + 1) if args.all_function_keys else (ecodes.KEY_F24, ecodes.KEY_F23)):
                output.key(key, 1)
                output.key(key, 0)
        else:
            async def presses():
                await engine.press('side_12')
                await engine.release('side_12')
                await engine.press('ring_finger')
                await engine.press('side_12')
                await engine.release('side_12')
                await engine.release('ring_finger')
                if args.all_function_keys:
                    for number in range(1, 13):
                        await engine.press(f'side_{number}')
                        await engine.release(f'side_{number}')
            asyncio.run(presses())
        QTimer.singleShot(400, finish)
    QTimer.singleShot(700, inject)
    QTimer.singleShot(2500, app.quit)
    try:
        if not args.uncorrected:
            asyncio.run(output.prepare_keyboard())
        app.exec()
    finally:
        asyncio.run(engine.disconnect())
        try:
            asyncio.run(output.restore_keyboard())
        finally:
            output.close()
            import shiboken6
            shiboken6.delete(pad)
    print(json.dumps(result, indent=2))
    return 0 if result.get('pass') else 1


if __name__ == '__main__':
    raise SystemExit(main())
