import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def env(tmp_path):
    # Unix socket paths have a 108-byte limit, independent of config path length.
    with TemporaryDirectory(prefix='gillete-test-runtime-') as runtime:
        yield {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'XDG_RUNTIME_DIR': runtime,
               'XDG_CONFIG_HOME': str(tmp_path / 'config'), 'XDG_STATE_HOME': str(tmp_path / 'state'),
               'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}


def test_second_real_editor_launch_reopens_hidden_window_and_exits(tmp_path, env):
    primary = '''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from gillete.gui import MainWindow, start
from gillete.profiles import ProfileStore
root = Path(sys.argv[1])
app = QApplication([])
timer = QTimer()
def check():
    window = next((w for w in app.topLevelWidgets() if isinstance(w, MainWindow)), None)
    if window is None:
        return
    window.service.timer.stop()
    if not (root / 'ready').exists():
        window.hide()
        (root / 'ready').touch()
    elif window.isVisible():
        (root / 'shown').touch()
        app.quit()
timer.timeout.connect(check)
timer.start(25)
QTimer.singleShot(8000, lambda: app.exit(2))
raise SystemExit(start(ProfileStore(root / 'profiles.json')))
'''
    process = subprocess.Popen([sys.executable, '-c', primary, str(tmp_path)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / 'ready').exists()
        second = subprocess.run([sys.executable, '-m', 'gillete.cli', '--config', str(tmp_path / 'profiles.json'), 'gui'],
                                env=env, capture_output=True, timeout=8)
        assert second.returncode == 0, second.stderr.decode()
        out, error = process.communicate(timeout=5)
        assert process.returncode == 0, error.decode()
        assert (tmp_path / 'shown').exists()
        assert not list((Path(env['XDG_RUNTIME_DIR']) / 'gillete').glob('*.sock'))
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def test_editor_reclaims_stale_socket_after_process_crash(tmp_path, env):
    script = '''
import os,sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from gillete.gui_instance import EditorInstance
app = QCoreApplication([])
instance = EditorInstance(Path(sys.argv[1]))
assert instance.claim(show=True, start_service=False)
if sys.argv[2] == 'crash':
    os._exit(0)
instance.close()
'''
    for mode in ('crash', 'clean'):
        result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'profiles.json'), mode],
                                env=env, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr.decode()
    assert not list((Path(env['XDG_RUNTIME_DIR']) / 'gillete').glob('*.sock'))
