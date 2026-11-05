import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from gillete.applications import launch_command
from gillete.compile_onboard import SoftwareOnly, encode_action
from gillete.device_session import DeviceSession
from gillete.engine import Engine
from gillete.focus import ProfileCoordinator
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, ConfigurationError, Layers, MODELS, Profile
from gillete.profiles import Configuration
from gillete.startup import desktop_argument


def test_desktop_action_roundtrip_and_software_only_status():
    action = Action('launch', desktop_id='org.example.Editor.desktop')
    assert Action.parse(action.json()) == action
    with pytest.raises(SoftwareOnly, match='service'):
        encode_action(action, MODELS[0])
    for identifier in ('/tmp/app.desktop', '../app.desktop', 'missing-suffix', 'bad\0.desktop', 123):
        with pytest.raises(ConfigurationError):
            Action('launch', desktop_id=identifier)
    with pytest.raises(ConfigurationError):
        Action('launch', desktop_id='app.desktop', argv=('/usr/bin/true',))
    for identifier in ('app.desktop', 123):
        with pytest.raises(ConfigurationError):
            Action('disabled', desktop_id=identifier)


def test_command_launch_from_both_layers_delivers_literal_argv_and_reports_failure(tmp_path):
    async def check():
        script = tmp_path / 'record.py'
        script.write_text('import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n')
        output = tmp_path / 'argv.json'
        args = ('$(touch ignored)', 'one;two', 'space name', '`id`', '%f')
        action = Action('launch', argv=(sys.executable, str(script), str(output), *args))
        assert launch_command(action) == action.argv
        session = DeviceSession(SimpleNamespace(), ProfileCoordinator(Configuration()), tmp_path, None)
        profile = Profile('launch', 'Launch', Layers({'side_1': action, 'dpi_up': Action('hypershift', playback='held')},
                                                   {'side_1': action}))
        engine = Engine(MODELS[0], profile, KeyLedger(RecordingOutput()), launch=session.launch)
        for shifted in (False, True):
            if shifted:
                await engine.press('dpi_up')
            await engine.press('side_1')
            await engine.press('side_1')  # A held report never launches twice.
            assert len(session.launch_waiters) == 1
            await engine.release('side_1')
            await asyncio.gather(*session.launch_waiters)
            assert json.loads(output.read_text()) == list(args) and not session.action_error
            output.unlink()
        await engine.release('dpi_up')
        await session.launch(Action('launch', argv=(str(tmp_path / 'missing-program'),)))
        assert 'Cannot launch' in session.action_error and not session.error
        await session.launch(Action('launch', argv=(sys.executable, '-c', 'raise SystemExit(7)')))
        await asyncio.gather(*session.launch_waiters)
        assert 'status 7' in session.action_error and not session.error
    asyncio.run(check())


def test_system_desktop_registry_precedence_and_real_launch(tmp_path):
    user, system = tmp_path / 'user', tmp_path / 'system'
    for root in (user, system):
        (root / 'applications').mkdir(parents=True)
    output = tmp_path / 'result.json'
    script = tmp_path / 'record arguments.py'
    script.write_text('import json,os,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps({"args":sys.argv[2:],"cwd":os.getcwd()}))\n')
    workdir = tmp_path / 'working'
    workdir.mkdir()
    args = ['space argument', '$(id)', 'semi;colon', '%f']
    desktop = ('[Desktop Entry]\nType=Application\nName=Example editor\nName[fr]=Éditeur\n'
               'Comment=Edit files\nPath=' + str(workdir) + '\nExec=' +
               ' '.join(desktop_argument(v) for v in [sys.executable, str(script), str(output), *args]) + ' %U\n')
    (system / 'applications/example.desktop').write_text(desktop.replace('Example editor', 'System version'))
    (user / 'applications/example.desktop').write_text(desktop)
    (system / 'applications/hidden.desktop').write_text(desktop)
    (user / 'applications/hidden.desktop').write_text('[Desktop Entry]\nHidden=true\n')
    (user / 'applications/nomenu.desktop').write_text(desktop + 'NoDisplay=true\n')
    (user / 'applications/other-desktop.desktop').write_text(desktop + 'OnlyShowIn=KDE;\n')
    (user / 'applications/uninstalled.desktop').write_text(desktop + 'TryExec=/no/such/program\n')
    program = '''
import asyncio,json,sys,time
from pathlib import Path
from types import SimpleNamespace
from gillete.applications import installed_applications, launch_command
from gillete.device_session import DeviceSession
from gillete.focus import ProfileCoordinator
from gillete.model import Action
from gillete.profiles import Configuration
async def main():
    root=Path(sys.argv[1])
    apps=installed_applications()
    assert [(a.identifier,a.name) for a in apps] == [('example.desktop','Example editor')], apps
    action=Action('launch', desktop_id='example.desktop')
    assert launch_command(action)[2] == str(root/'user/applications/example.desktop')
    session=DeviceSession(SimpleNamespace(),ProfileCoordinator(Configuration()),root,None)
    await session.launch(action)
    await asyncio.gather(*session.launch_waiters)
    assert not session.action_error, session.action_error
    for _ in range(100):
        if (root/'result.json').exists():
            break
        await asyncio.sleep(.01)
    assert (root/'result.json').exists()
    await session.launch(Action('launch',desktop_id='missing.desktop'))
    assert 'no longer installed' in session.action_error and not session.error
asyncio.run(main())
'''
    env = {**os.environ, 'XDG_DATA_HOME': str(user), 'XDG_DATA_DIRS': str(system),
           'XDG_CURRENT_DESKTOP': 'Hyprland', 'LC_ALL': 'C', 'LANGUAGE': 'C'}
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)], env=env, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(output.read_text()) == {'args': args, 'cwd': str(workdir)}


def test_desktop_launch_uses_dbus_activation_in_a_private_session_bus(tmp_path):
    data = tmp_path / 'data'
    (data / 'applications').mkdir(parents=True)
    (data / 'applications/org.gillete.LaunchTest.desktop').write_text(
        '[Desktop Entry]\nType=Application\nName=Activation test\nDBusActivatable=true\nExec=/usr/bin/false\n')
    helper = tmp_path / 'application.py'
    helper.write_text('''
import sys
from pathlib import Path
import gi
gi.require_version('Gio','2.0')
from gi.repository import Gio, GLib
root = Path(sys.argv[1])
loop = GLib.MainLoop()
info = Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.freedesktop.Application"><method name="Activate"><arg type="a{sv}" direction="in"/></method></interface></node>')
def method(connection, sender, path, interface, name, parameters, invocation):
    assert name == 'Activate'
    (root/'activated').touch()
    invocation.return_value(None)
    GLib.timeout_add(100, loop.quit)
def bus_acquired(connection, name):
    connection.register_object('/org/gillete/LaunchTest', info.interfaces[0], method, None, None)
def name_acquired(connection, name):
    (root/'ready').touch()
owner = Gio.bus_own_name(Gio.BusType.SESSION, 'org.gillete.LaunchTest', Gio.BusNameOwnerFlags.NONE,
                        bus_acquired, name_acquired, None)
GLib.timeout_add(5000, loop.quit)
loop.run()
Gio.bus_unown_name(owner)
''')
    program = '''
import asyncio,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from gillete.device_session import DeviceSession
from gillete.focus import ProfileCoordinator
from gillete.model import Action
from gillete.profiles import Configuration
async def main():
    root=Path(sys.argv[1])
    app=subprocess.Popen([sys.executable,str(root/'application.py'),str(root)])
    try:
        for _ in range(200):
            if (root/'ready').exists(): break
            await asyncio.sleep(.01)
        assert (root/'ready').exists()
        session=DeviceSession(SimpleNamespace(),ProfileCoordinator(Configuration()),root,None)
        await session.launch(Action('launch',desktop_id='org.gillete.LaunchTest.desktop'))
        await asyncio.gather(*session.launch_waiters)
        assert not session.action_error, session.action_error
        for _ in range(100):
            if (root/'activated').exists(): break
            await asyncio.sleep(.01)
        assert (root/'activated').exists()
        assert app.wait(timeout=2) == 0
    finally:
        if app.poll() is None:
            app.terminate()
        app.wait(timeout=2)
asyncio.run(main())
'''
    env = {**os.environ, 'XDG_DATA_HOME': str(data), 'XDG_DATA_DIRS': str(tmp_path / 'empty')}
    result = subprocess.run(['dbus-run-session', '--', sys.executable, '-c', program, str(tmp_path)],
                            env=env, capture_output=True, timeout=8)
    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / 'activated').exists()
