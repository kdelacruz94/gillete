"""Explicit, reversible XDG desktop autostart configuration."""

import os
from pathlib import Path
import sys
import tempfile


def desktop_argument(value):
    """Quote one argv item under both Desktop Entry string and Exec rules."""
    if not value or any(c in value for c in '\0\r\n\t'):
        raise ValueError('Startup paths cannot be empty or contain control characters')
    escaped = ''.join('\\' + c if c in '\\"`$' else c for c in value)
    return '"' + escaped.replace('\\', '\\\\').replace('%', '%%') + '"'


class AutostartEntry:
    def __init__(self, config_path, path=None, executable=None):
        root = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        self.path = path or root / 'autostart/org.gillete.Gillete.desktop'
        executable = executable or sys.executable
        if '=' in executable:
            raise ValueError('The desktop launcher cannot use an executable path containing =')
        argv = [executable, '-m', 'gillete.cli', '--config', str(config_path.resolve()),
                'gui', '--background', '--start-service']
        self.contents = ('[Desktop Entry]\nType=Application\nName=Gillete\n'
                         'Comment=Mouse profiles and background service\nIcon=input-mouse\n'
                         'Terminal=false\nOnlyShowIn=Hyprland;\n'
                         'Exec=' + ' '.join(desktop_argument(v) for v in argv) + '\n').encode()

    def enabled(self):
        try:
            if self.path.is_symlink():
                raise ValueError(f'Startup entry is a symlink; review {self.path} before changing it')
            contents = self.path.read_bytes()
        except FileNotFoundError:
            return False
        if contents != self.contents:
            raise ValueError(f'An existing startup entry differs from this installation; review {self.path} before changing it')
        return True

    def set_enabled(self, enabled):
        before = self.enabled()
        if enabled == before:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not enabled:
            self.path.unlink()
        else:
            # Link a complete temporary file without overwriting a competing entry.
            fd, temporary = tempfile.mkstemp(prefix='.gillete-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'wb') as file:
                    file.write(self.contents)
                    file.flush()
                    os.fsync(file.fileno())
                os.link(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
