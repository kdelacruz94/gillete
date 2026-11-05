"""Validate staged Arch/wheel artifacts without installing on the host."""

import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import zipfile


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / 'dist/gillete-0.1.0-1-any.pkg.tar.zst'
    wheel = root / 'dist/gillete-0.1.0-py3-none-any.whl'
    source = root / 'dist/gillete-0.1.0.tar.gz'
    with tarfile.open(source) as archive:
        names = archive.getnames()
        assert 'gillete-0.1.0/tests/fixtures/naga_v3_descriptors.json' in names
        assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in names)
        assert not any('/evidence/' in name or '.local' in name for name in names)
    with zipfile.ZipFile(wheel) as archive:
        assert not any('evidence/' in name or '.local' in name for name in archive.namelist())
        for module in ('settings', 'gui_settings', 'gui_controls', 'gui_applications', 'keyboard_map',
                       'startup', 'gui_startup', 'gui_instance'):
            assert f'gillete/{module}.py' in archive.namelist()
        for module in ('applications', 'gui_launch', 'gui_standalone', 'macro_reads', 'firmware_probe',
                       'validation_plan', 'guided_service', 'validation_pad', 'mapping_view', 'dpi_probe',
                       'descriptors', 'wired_probe', 'diagnostics', 'gui_diagnostics',
                       'profile_transfer', 'gui_profile_transfer', 'profile_activation',
                       'persistence', 'gui_persistence'):
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
        runtime = stage / 'runtime'
        runtime.mkdir(mode=0o700)
        environment = {**os.environ, 'PYTHONPATH': str(sites[0]), 'QT_QPA_PLATFORM': 'offscreen',
                       'XDG_RUNTIME_DIR': str(runtime),
                       'XDG_CONFIG_HOME': str(stage / 'config'), 'XDG_STATE_HOME': str(stage / 'state')}
        run(['bsdtar', '-xf', str(source), '-C', str(stage)])
        source_root = stage / 'gillete-0.1.0'
        # Exercise the public byte fixtures from the shipped source, with its
        # own imports, rather than accidentally relying on checkout-only data.
        run([sys.executable, '-I', '-c',
             'import sys; from pathlib import Path; sys.path.insert(0, str(Path("src").resolve())); '
             'import gillete; assert Path(gillete.__file__).is_relative_to(Path.cwd()); '
             'import pytest; raise SystemExit(pytest.main(["-q", "tests/test_wired_probe.py", "tests/test_persistence.py"]))'],
            cwd=source_root, env=environment)
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
from gillete.gui_persistence import PersistenceDialog
from gillete.profiles import ProfileStore
from gillete.applications import desktop_api
desktop_api()
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
        run([str(interpreter), '-I', '-m', 'gillete.firmware_probe', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.guided_service', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.dpi_probe', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.wired_probe', '--help'],
            env=environment, stdout=subprocess.PIPE)
    print('PASS: source fixtures/tests, Arch paths/launcher, isolated native GUI, wheel install and CLI; no host installation or remapping.')


if __name__ == '__main__':
    main()
