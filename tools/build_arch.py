"""Build local wheels and an Arch package without modifying system packages.

Requires uv and makepkg. Python build dependencies live in uv's isolated cache;
the resulting package retains its normal pacman runtime dependencies. Nothing
is installed or enabled. makepkg operates outside the project's src directory.
"""

import hashlib
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / 'dist'
    destination.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='gillete-arch-build-') as temporary:
        stage = Path(temporary)
        subprocess.run(['uv', 'build', '--sdist', '--wheel', '--python', '/usr/bin/python',
                        '--out-dir', str(stage)], cwd=root, check=True)
        archives = list(stage.glob('gillete-*.tar.gz'))
        if len(archives) != 1:
            raise RuntimeError('Expected one generated source archive')
        digest = hashlib.sha256(archives[0].read_bytes()).hexdigest()
        recipe = (root / 'PKGBUILD').read_text()
        marker = "sha256sums=('SKIP')"
        if recipe.count(marker) != 1:
            raise RuntimeError('Cannot pin the generated source checksum in the build recipe')
        (stage / 'PKGBUILD').write_text(recipe.replace(marker, f"sha256sums=('{digest}')"))
        subprocess.run(['uv', 'run', '--isolated', '--no-project', '--python', '/usr/bin/python',
                        '--with', 'build', '--with', 'installer', '--with', 'setuptools', '--with', 'wheel',
                        'makepkg', '--nodeps'], cwd=stage, check=True)
        packages = list(stage.glob('gillete-*.pkg.tar.*'))
        if not packages:
            raise RuntimeError('makepkg did not produce a package')
        for artifact in [*archives, *stage.glob('gillete-*.whl'), *packages]:
            target = destination / artifact.name
            shutil.copy2(artifact, target)
            print(target, flush=True)


if __name__ == '__main__':
    main()
