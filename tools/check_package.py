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
        assert 'gillete-0.1.0/tests/fixtures/naga_v3_wired_controls.json' in names
        assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in names)
        assert not any('/evidence/' in name or '.local' in name for name in names)
    with zipfile.ZipFile(wheel) as archive:
        assert not any('evidence/' in name or '.local' in name for name in archive.namelist())
        for module in ('settings', 'gui_settings', 'gui_controls', 'gui_applications', 'keyboard_map',
                       'startup', 'gui_startup', 'gui_instance', 'function_keymap', 'stop_shortcut'):
            assert f'gillete/{module}.py' in archive.namelist()
        for module in ('applications', 'gui_launch', 'gui_standalone', 'macro_reads', 'macro_inspection', 'firmware_probe', 'polling_reads',
                       'validation_plan', 'guided_service', 'validation_pad', 'mapping_view', 'dpi_probe', 'dpi_sensor_probe',
                       'dpi_replug_probe', 'dpi_driver_probe', 'native_macro', 'macro_memory',
                       'native_macro_probe', 'native_macro_observer', 'native_macro_plan', 'native_profile_transaction',
                       'native_profile_probe',
                       'native_profile_review', 'gui_native_profile',
                       'native_profile_support',
                       'native_macro_library',
                       'native_sequence_probe', 'native_sequence_pad',
                       'native_profile_undo', 'stored_native', 'memory_access',
                       'native_history', 'native_cleanup', 'gui_native_library',
                       'descriptors', 'wired_probe', 'wired_capture', 'wired_acceptance', 'wired_transport', 'wired_backend', 'wired_binding_probe', 'wired_binding_replug', 'diagnostics', 'gui_diagnostics',
                       'profile_transfer', 'gui_profile_transfer', 'profile_activation', 'profile_selection',
                       'profile_from_mouse', 'gui_profile_from_mouse',
                       'control_trace', 'control_validation', 'control_pad',
                       'persistence', 'gui_persistence', 'device_action_support'):
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
             'import pytest; raise SystemExit(pytest.main(["-q", "tests/test_wired_probe.py", "tests/test_wired_capture.py", "tests/test_wired_acceptance.py", "tests/test_wired_backend.py", "tests/test_wired_binding_probe.py", "tests/test_wired_binding_replug.py", "tests/test_service.py", "tests/test_guided_service.py", "tests/test_reports.py", "tests/test_persistence.py", '
             '"tests/test_device_action_support.py", "tests/test_macro_inspection.py", '
             '"tests/test_macro_reads.py", "tests/test_firmware_probe.py", "tests/test_polling_reads.py", "tests/test_dpi_probe.py", '
             '"tests/test_native_macro.py", "tests/test_native_macro_probe.py", "tests/test_native_macro_observer.py", '
             '"tests/test_native_macro_plan.py", "tests/test_native_profile_transaction.py", '
             '"tests/test_native_profile_probe.py", "tests/test_native_profile_review.py", "tests/test_hid_replies.py", '
             '"tests/test_native_profile_support.py", "tests/test_hardware.py", "tests/test_native_macro_reuse.py", '
             '"tests/test_native_sequence_probe.py", "tests/test_native_profile_undo.py", "tests/test_stored_native.py", "tests/test_stored_native_sequences.py", '
             '"tests/test_function_keymap.py", "tests/test_keyboard_map.py", "tests/test_memory_access.py", '
             '"tests/test_native_cleanup.py", "tests/test_native_cleanup_review.py", '
             '"tests/test_profile_selection.py", "tests/test_profile_from_mouse.py", "tests/test_stop_shortcut.py", '
             '"tests/test_gui.py::test_emergency_shortcut_preferences_are_local_and_preserve_unrelated_edits", '
             '"tests/test_gui.py::test_software_control_displays_active_and_pending_emergency_shortcuts", '
             '"tests/test_gui.py::test_mouse_profile_review_keeps_unknowns_until_rows_are_explicitly_disabled", '
             '"tests/test_gui.py::test_mouse_profile_review_explains_unavailable_device_actions_and_keeps_trigger_layers_consistent", '
             '"tests/test_gui.py::test_create_profile_from_mouse_is_local_only_and_preserves_selection_rules_and_originals", '
             '"tests/test_gui.py::test_copied_native_count_keeps_its_zero_extra_gap_in_the_editor", '
             '"tests/test_gui.py::test_wired_mouse_read_exposes_copy_and_backup_but_keeps_onboard_writes_disabled", '
             '"tests/test_control_validation.py", "tests/test_control_trace.py", '
             '"tests/test_control_pad.py", "tests/test_control_runner.py", '
             '"tests/test_focus.py", "tests/test_focus_watcher.py", "tests/test_input_cancellation.py", '
             '"tests/test_service.py::test_pending_focus_blocks_enable_and_saved_startup_until_details_settle", '
             '"tests/test_diagnostics.py::test_connected_monitor_with_pending_focus_is_not_reported_ready", '
             '"tests/test_gui.py::test_tray_profile_selection_is_per_mouse_durable_and_preserves_external_edits", '
             '"tests/test_gui.py::test_missing_cached_service_status_still_routes_pin_through_worker", '
             '"tests/test_gui.py::test_native_library_review_requires_explicit_unused_selection_and_undo_acknowledgement", '
             '"tests/test_gui.py::test_native_storage_write_waits_for_reader_and_passes_exact_selection", '
             '"tests/test_gui.py::test_discarding_native_storage_dialog_never_schedules_deletion", '
             '"tests/test_gui.py::test_native_storage_acknowledgement_is_reset_when_selection_changes", '
             '"tests/test_gui.py::test_native_macro_review_has_mapping_rows_but_no_save_action_or_writes", '
             '"tests/test_gui.py::test_explicit_native_save_preview_checks_firmware_and_preserves_cancelled_plan", '
             '"tests/test_gui.py::test_native_save_waits_for_read_worker_then_runs_once", '
             '"tests/test_gui.py::test_closing_pending_native_save_panel_cancels_deferred_write", '
             '"tests/test_gui.py::test_native_sequence_pad_records_desktop_modifiers_and_only_after_ready"]))'],
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
        run([str(interpreter), '-I', '-m', 'gillete.control_pad', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.dpi_probe', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.wired_probe', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.wired_capture', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.wired_acceptance', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.wired_binding_probe', '--help'],
            env=environment, stdout=subprocess.PIPE)
        run([str(interpreter), '-I', '-m', 'gillete.wired_binding_replug', '--help'],
            env=environment, stdout=subprocess.PIPE)
    print('PASS: source fixtures/tests, Arch paths/launcher, isolated native GUI, wheel install and CLI; no host installation or remapping.')


if __name__ == '__main__':
    main()
