import json
import os
import sys

import pytest

from gillete.model import ConfigurationError, MODELS
from gillete.profiles import Configuration, ProfileStore
from gillete.startup import AutostartEntry, desktop_argument


def test_existing_profiles_default_to_disabled_and_startup_choices_roundtrip(tmp_path):
    data = Configuration().json()
    del data['startup_models']
    assert Configuration.parse(data).startup_models == []
    store = ProfileStore(tmp_path / 'profiles.json')
    config = store.read()
    config.startup_models = [MODELS[1]]
    store.save(config, expected_revision=0)
    assert store.read().startup_models == [MODELS[1]]
    for invalid in (True, 'v3', ['unknown'], [MODELS[0], MODELS[0]], [None], [{}]):
        data['startup_models'] = invalid
        with pytest.raises(ConfigurationError, match='startup'):
            Configuration.parse(data)


def test_desktop_startup_is_explicit_reversible_and_preserves_other_entries(tmp_path):
    path = tmp_path / 'autostart/gillete.desktop'
    entry = AutostartEntry(tmp_path / 'profiles.json', path=path)
    assert not entry.enabled() and not path.exists()
    entry.set_enabled(True)
    assert entry.enabled() and path.read_bytes() == entry.contents
    assert path.stat().st_mode & 0o777 == 0o600
    entry.set_enabled(True)
    entry.set_enabled(False)
    assert not path.exists() and not list(path.parent.glob('.gillete-*'))
    path.write_text('User-created entry\n')
    for enabled in (True, False):
        with pytest.raises(ValueError, match='existing startup'):
            entry.set_enabled(enabled)
        assert path.read_text() == 'User-created entry\n'
    path.unlink()
    target = tmp_path / 'original.desktop'
    target.write_bytes(entry.contents)
    path.symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        entry.set_enabled(False)
    assert path.is_symlink() and target.read_bytes() == entry.contents


def test_desktop_exec_quoting_through_real_gio_launcher(tmp_path):
    # GLib executes the generated Desktop Entry syntax, not a duplicate parser.
    gi = pytest.importorskip('gi')
    gi.require_version('GioUnix', '2.0')
    from gi.repository import GioUnix
    script = tmp_path / 'record args.py'
    output = tmp_path / 'args.json'
    script.write_text('import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n')
    args = ['space name', 'quote"here', 'back\\slash', '`id`', '$(id)', '%f', 'one;two', "single'quote"]
    path = tmp_path / 'test.desktop'
    path.write_text('[Desktop Entry]\nType=Application\nName=Arg test\nExec=' +
                    ' '.join(desktop_argument(s) for s in [sys.executable, str(script), str(output), *args]) + '\n')
    app = GioUnix.DesktopAppInfo.new_from_filename(str(path))
    assert app is not None
    pids = []
    # DO_NOT_REAP_CHILD gives this test a deterministic process handle to wait on.
    from gi.repository import GLib
    assert app.launch_uris_as_manager([], None, GLib.SpawnFlags.DO_NOT_REAP_CHILD,
                                     None, None, lambda _app, pid: pids.append(pid))
    assert len(pids) == 1
    _, status = os.waitpid(pids[0], 0)
    assert status == 0
    assert json.loads(output.read_text()) == args


@pytest.mark.parametrize('value', ['', 'line\nname', 'tab\tname', 'nul\0name'])
def test_desktop_argument_rejects_invalid_paths(value):
    with pytest.raises(ValueError):
        desktop_argument(value)
