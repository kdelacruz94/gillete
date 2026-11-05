"""Installed desktop applications, resolved by ID using the system registry."""

from dataclasses import dataclass
from pathlib import Path

from .model import Action, ConfigurationError


@dataclass(frozen=True)
class DesktopApplication:
    identifier: str
    name: str
    description: str = ''


def desktop_api():
    try:
        import gi
        gi.require_version('Gio', '2.0')
        gi.require_version('GioUnix', '2.0')
        from gi.repository import Gio, GioUnix
        return Gio, GioUnix
    except (ImportError, ValueError) as error:
        raise RuntimeError('Desktop application support needs the python-gobject and glib2 packages') from error


def installed_applications():
    Gio, _ = desktop_api()
    apps = [DesktopApplication(app.get_id(), app.get_display_name(), app.get_description() or '')
            for app in Gio.AppInfo.get_all() if app.get_id() and app.should_show()]
    return sorted(apps, key=lambda app: (app.name.casefold(), app.identifier))


def desktop_application(identifier):
    # Validate IDs even for callers outside the profile importer.
    Action('launch', desktop_id=identifier)
    _, GioUnix = desktop_api()
    try:
        app = GioUnix.DesktopAppInfo.new(identifier)
    except TypeError:
        # PyGObject raises for a constructor's documented nullable return.
        app = None
    if app is None or app.get_is_hidden():
        raise ConfigurationError(f'Desktop application is no longer installed: {identifier}')
    return app


def launch_command(action):
    if action.kind != 'launch':
        raise ConfigurationError('Expected a program-launch action')
    if not action.desktop_id:
        return action.argv
    app = desktop_application(action.desktop_id)
    filename = app.get_filename()
    if not filename or not Path(filename).is_absolute():
        raise ConfigurationError('The installed application has no desktop file')
    # GIO owns desktop Exec expansion, D-Bus activation, terminal launching and
    # working-directory handling. We never parse an Exec line as a shell command.
    return ('/usr/bin/gio', 'launch', filename)
