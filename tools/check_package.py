"""Validate staged Arch/wheel artifacts without installing on the host."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / 'dist/gillete-0.1.0-1-any.pkg.tar.zst'
    wheel = root / 'dist/gillete-0.1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as archive:
        assert not any('evidence/' in name or '.local' in name for name in archive.namelist())
        for module in ('settings', 'gui_settings', 'gui_controls', 'gui_applications', 'keyboard_map'):
            assert f'gillete/{module}.py' in archive.namelist()
    with TemporaryDirectory(prefix='gillete-package-check-') as temporary:
        stage = Path(temporary)
        names = run(['bsdtar', '-tf', str(package)], stdout=subprocess.PIPE).stdout.splitlines()
        assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in names)
        assert not any('evidence/' in name or name.startswith('etc/') for name in names)
        run(['bsdtar', '-xf', str(package), '-C', str(stage)])
        executable = stage / 'usr/bin/gillete'
        assert executable.read_text().splitlines()[0] == '#!/usr/bin/python'
        assert os.access(executable, os.X_OK)
        for filename in ('usr/lib/systemd/user/gillete.service',
                         'usr/lib/udev/rules.d/70-gillete.rules',
                         'usr/share/applications/org.gillete.Gillete.desktop'):
            assert (stage / filename).is_file()
        sites = list(stage.glob('usr/lib/python*/site-packages'))
        assert len(sites) == 1
        environment = {**os.environ, 'PYTHONPATH': str(sites[0]), 'QT_QPA_PLATFORM': 'offscreen',
                       'XDG_CONFIG_HOME': str(stage / 'config'), 'XDG_STATE_HOME': str(stage / 'state')}
        run([str(executable), '--config', str(stage / 'profiles.json'), 'validate'], env=environment)
        gui_smoke = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import gillete
assert Path(gillete.__file__).is_relative_to(Path(sys.argv[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from gillete.gui import start
from gillete.profiles import ProfileStore
app = QApplication([])
QTimer.singleShot(400, app.quit)
raise SystemExit(start(ProfileStore(Path(sys.argv[2]))))
'''
        run(['/usr/bin/python', '-I', '-c', gui_smoke, str(sites[0]), str(stage / 'profiles.json')], env=environment)
        venv = stage / 'wheel-env'
        run(['uv', 'venv', '--python', '/usr/bin/python', '--system-site-packages', str(venv)])
        interpreter = venv / 'bin/python'
        run(['uv', 'pip', 'install', '--python', str(interpreter), '--no-deps', str(wheel)])
        run([str(interpreter), '-I', '-c',
             'import gillete,sys; from pathlib import Path; assert Path(gillete.__file__).is_relative_to(Path(sys.prefix)); '
             'from gillete.cli import main; raise SystemExit(main(["--config", sys.argv[1], "validate"]))',
             str(stage / 'wheel-profiles.json')], env=environment)
    print('PASS: Arch paths/launcher, isolated native GUI, wheel install and CLI; no host installation or remapping.')


if __name__ == '__main__':
    main()
