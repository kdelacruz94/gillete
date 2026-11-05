import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from copy import deepcopy
import pytest
import shiboken6
from PySide6.QtWidgets import QApplication, QMessageBox

from gillete.gui import ActionDialog, MainWindow
from gillete.model import Action, MODEL_CONTROLS, MODELS, Profile, Step
from gillete.gui_controls import ControlSelector
from gillete.gui_applications import ApplicationPicker
from gillete.profiles import Window
from gillete.profiles import ProfileStore
from gillete.gui_settings import SettingsDialog, SettingsPreview
from gillete.gui_startup import StartupPanel
from gillete.startup import AutostartEntry
from gillete.applications import DesktopApplication
from gillete.gui_launch import InstalledApplicationPicker
from gillete.gui_recording import RecordingDialog
from gillete.settings import plan
from types import SimpleNamespace


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    application.closeAllWindows()
    application.processEvents()
    for window in application.topLevelWidgets():
        shiboken6.delete(window)
    shiboken6.delete(application)


def test_scroll_and_dpi_editors_preserve_assignments(app):
    for action in (Action('scroll', axis='REL_HWHEEL', value=-2), Action('dpi', target='down')):
        dialog = ActionDialog(action, {})
        dialog.save()
        assert dialog.result() == dialog.DialogCode.Accepted
        assert dialog.action.kind == action.kind
        assert dialog.action.target == action.target
        assert dialog.action.axis == action.axis and dialog.action.value == action.value
        dialog.close()
        shiboken6.delete(dialog)


def test_failed_save_restores_ui_and_does_not_query_hardware(app, tmp_path, monkeypatch):
    from gillete import hardware
    monkeypatch.setattr(hardware, 'transport', lambda _: (_ for _ in ()).throw(AssertionError('Implicit hardware access')))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    store = ProfileStore(tmp_path / 'profiles.json')
    window = MainWindow(store)
    original = deepcopy(window.config.json())
    window.config.pinned[MODELS[0]] = 'default'
    window.config.profiles['default'].name = 'Unsaved rename'
    def fail(*args, **kwargs): raise OSError('Disk full')
    monkeypatch.setattr(store, 'save', fail)
    assert window.save_config() is False
    assert window.config.json() == original
    assert window.profile.currentText() == 'Default'
    window.close()
    shiboken6.delete(window)


def settings_snapshot():
    return SimpleNamespace(product=0xB4, settings={
        'dpi': '01070807080000', 'polling': '01',
        'stages': '0101050104b004b000000203e803e800000304b004b000000406400640000005070807080000'})


def test_settings_dialog_preserves_existing_values_then_selects_a_stage(app, monkeypatch):
    snapshot = settings_snapshot()
    dialog = SettingsDialog(snapshot)
    assert dialog.current[0].value() == 1800 and dialog.rows[0][0].value() == 1200
    assert not dialog.review.isEnabled() and not plan(snapshot, dialog.collect()).changes
    dialog.active.setValue(2)
    assert tuple(b.value() for b in dialog.current) == (1000, 1000)
    dialog.rows[1][0].setValue(1100)
    assert tuple(b.value() for b in dialog.rows[1]) == (1100, 1100)
    assert tuple(b.value() for b in dialog.current) == (1100, 1100)
    dialog.polling.setCurrentIndex(dialog.polling.findData(500))
    seen = []
    def accept_preview(preview):
        seen.append(preview)
        return preview.DialogCode.Accepted
    monkeypatch.setattr(SettingsPreview, 'exec', accept_preview)
    dialog.review_changes()
    assert seen and dialog.result() == dialog.DialogCode.Accepted
    assert dialog.draft.dpi == (1100, 1100) and dialog.draft.active == 2 and dialog.draft.polling == 500
    shiboken6.delete(dialog)


def test_settings_dialog_shrinking_stages_keeps_selection_valid_and_allows_split_axes(app):
    dialog = SettingsDialog(settings_snapshot())
    dialog.active.setValue(5)
    dialog.count.setValue(2)
    assert dialog.active.value() == 2 and dialog.active.maximum() == 2
    assert dialog.table.isRowHidden(2)
    dialog.link_axes.setChecked(False)
    dialog.current[0].setValue(1350)
    assert dialog.collect().dpi == (1350, 1000)
    assert dialog.current[0].maximum() == 30000
    dialog.reject()
    assert dialog.draft is None
    shiboken6.delete(dialog)


def test_unread_dpi_is_not_replaced_with_displayed_defaults_when_editing_polling(app):
    snapshot = settings_snapshot()
    del snapshot.settings['stages']
    dialog = SettingsDialog(snapshot)
    assert not dialog.dpi_available and dialog.polling_available
    dialog.polling.setCurrentIndex(dialog.polling.findData(125))
    draft = dialog.collect()
    assert draft.dpi is None and draft.stages is None and draft.active is None
    assert set(plan(snapshot, draft).changes) == {'polling'}
    shiboken6.delete(dialog)


def test_tray_profile_selection_is_per_mouse_durable_and_preserves_external_edits(app, tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    config = store.read()
    config.profiles['work'] = Profile('work', 'Work')
    store.save(config, expected_revision=0)
    window = MainWindow(store)
    window.service.timer.stop()
    changed_elsewhere = store.read()
    changed_elsewhere.profiles['work'].name = 'Work renamed elsewhere'
    store.save(changed_elsewhere, expected_revision=changed_elsewhere.revision)
    window.populate_tray_menu()
    submenu = next(a.menu() for a in window.tray_menu.actions() if a.menu() and a.text().startswith('Naga V2'))
    next(a for a in submenu.actions() if a.data() == 'work').trigger()
    saved = store.read()
    assert saved.pinned == {MODELS[0]: 'work'}
    assert saved.profiles['work'].name == 'Work renamed elsewhere'
    window.populate_tray_menu()
    submenu = next(a.menu() for a in window.tray_menu.actions() if a.menu() and a.text().startswith('Naga V2'))
    assert next(a for a in submenu.actions() if a.data() == 'work').isChecked()
    next(a for a in submenu.actions() if a.data() == 'automatic').trigger()
    assert store.read().pinned == {}
    window.close()
    shiboken6.delete(window)


def test_live_profile_selection_waits_for_the_service_and_close_hides_to_tray(app, tmp_path, monkeypatch):
    store = ProfileStore(tmp_path / 'profiles.json')
    window = MainWindow(store)
    window.service.timer.stop()
    window.service.last = {'running': True}
    calls = []
    monkeypatch.setattr(window.service, 'send', lambda *args, **kwargs: calls.append((args, kwargs)))
    window.select_pin(MODELS[1], 'default')
    assert calls == [(('pin', MODELS[1]), {'profile': 'default'})]
    assert not store.read().pinned
    window.tray = SimpleNamespace(isVisible=lambda: True)
    window.show()
    window.close()
    assert not window.isVisible()
    window.tray = None
    shiboken6.delete(window)


def test_visual_selector_exposes_every_control_for_each_mouse_and_both_layers(app):
    selector = ControlSelector()
    emitted = []
    selector.edit_requested.connect(lambda control, shifted: emitted.append((control, shifted)))
    for model in MODELS:
        selector.refresh(model, Profile('p', 'P'))
        assert {c for c, b in selector.buttons.items() if not b.isHidden()} == set(MODEL_CONTROLS[model])
        for shifted in (False, True):
            selector.layer.setCurrentIndex(int(shifted))
            for control in MODEL_CONTROLS[model]:
                selector.buttons[control].click()
                assert emitted[-1] == (control, shifted)
    shiboken6.delete(selector)


def test_application_picker_matches_literal_app_ids_and_optional_titles(app):
    selected = Window('a', '[Wine]*game?', 'Game [1]*?', '/usr/bin/wine')
    picker = ApplicationPicker([selected])
    rule = picker.rule('default')
    assert rule.matches(MODELS[0], selected)
    assert rule.matches(MODELS[0], Window('b', selected.app_class, 'Different document', selected.executable))
    assert not rule.matches(MODELS[0], Window('c', 'WgameX', selected.title, selected.executable))
    picker.match_title.setChecked(True)
    rule = picker.rule('default')
    assert rule.matches(MODELS[1], selected)
    assert not rule.matches(MODELS[1], Window('b', selected.app_class, 'Game 1hello', selected.executable))
    shiboken6.delete(picker)


def test_startup_preferences_preserve_external_profile_edits_and_do_not_activate(app, tmp_path, monkeypatch):
    from gillete import service
    async def forbidden(*args, **kwargs): raise AssertionError('Preferences must not send service commands')
    monkeypatch.setattr(service, 'request', forbidden)
    store = ProfileStore(tmp_path / 'profiles.json')
    entry = AutostartEntry(store.path, path=tmp_path / 'autostart/gillete.desktop')
    panel = StartupPanel(store, entry=entry)
    changed = store.read()
    changed.profiles['default'].name = 'Changed elsewhere'
    store.save(changed, expected_revision=0)
    panel.mice[MODELS[1]].setChecked(True)
    panel.save_mice()
    assert store.read().startup_models == [MODELS[1]]
    assert store.read().profiles['default'].name == 'Changed elsewhere'
    assert not entry.path.exists()
    panel.desktop.setChecked(True)
    assert entry.enabled()
    panel.desktop.setChecked(False)
    assert not entry.enabled()
    before = store.path.read_bytes()
    def fail(*args, **kwargs): raise OSError('Disk full')
    monkeypatch.setattr(store, 'save', fail)
    panel.mice[MODELS[0]].setChecked(True)
    panel.save_mice()
    assert 'Not saved' in panel.result.text() and store.path.read_bytes() == before
    shiboken6.delete(panel)


def test_installed_app_picker_filters_and_saves_only_the_selected_target(app, monkeypatch):
    from PySide6.QtWidgets import QDialogButtonBox
    apps = [DesktopApplication('editor.desktop', 'Editor', 'Edit source files'),
            DesktopApplication('game.desktop', 'Game', 'Play a game')]
    picker = InstalledApplicationPicker(applications=apps, selected='editor.desktop')
    assert picker.selected() == apps[0]
    picker.search.setText('game')
    assert picker.selected() is None
    assert not picker.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    picker.apps.setCurrentRow(1)
    assert picker.selected() == apps[1]
    shiboken6.delete(picker)
    dialog = ActionDialog(Action('launch', argv=('/usr/bin/old', 'argument')), {})
    dialog.launch_type.setCurrentIndex(1)
    dialog.save()
    assert 'Choose an installed' in dialog.error.text()
    dialog.desktop_id = 'editor.desktop'
    dialog.desktop_name.setText('Editor')
    dialog.save()
    assert dialog.action.desktop_id == 'editor.desktop' and dialog.action.argv == ()
    shiboken6.delete(dialog)


def test_macro_builder_timing_and_bulk_retime_preserve_shortcut_order(app, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    dialog = ActionDialog(Action(), {})
    dialog.sequence_text.setText('Alt+H, O, A')
    dialog.sequence_hold.setValue(65)
    dialog.sequence_gap.setValue(175)
    dialog.build()
    steps = dialog.read_steps()
    assert [s.milliseconds for s in steps if s.kind == 'wait'] == [65, 175, 65, 175, 65]
    monkeypatch.setattr(QInputDialog, 'getInt', lambda *_args: (80, True))
    dialog.retime()
    assert [s for s in dialog.read_steps() if s.kind != 'wait'] == [s for s in steps if s.kind != 'wait']
    assert [s.milliseconds for s in dialog.read_steps() if s.kind == 'wait'] == [80] * 5
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted
    shiboken6.delete(dialog)


class RecordingSource:
    def __init__(self, path, events=(), held=(), caps=None, fail_active=False):
        self.path, self.events, self.held = path, list(events), held
        self.fd, self.writer = os.pipe()
        self.closed = False
        self.caps, self.fail_active = caps, fail_active

    def capabilities(self):
        from evdev import ecodes as E
        return self.caps or {E.EV_KEY: [E.KEY_A]}

    def active_keys(self):
        if self.fail_active:
            raise OSError('Device disconnected during setup')
        return self.held

    def read(self):
        events, self.events = self.events, []
        return iter(events)

    def close(self):
        if not self.closed:
            os.close(self.fd)
            os.close(self.writer)
            self.closed = True

    def grab(self):
        raise AssertionError('Recording must never grab input')


def recording_event(timestamp, kind, code, value):
    from evdev import InputEvent
    seconds = int(timestamp)
    return InputEvent(seconds, round((timestamp - seconds) * 1_000_000), kind, code, value)


def setup_recording(monkeypatch, sources, *, virtual=()):
    from gillete import gui_recording as recording
    monkeypatch.setattr(recording, 'list_devices', lambda: [*sources, *virtual])
    monkeypatch.setattr(recording, 'virtual_source', lambda path: path in virtual)
    opened = []
    def open_source(path):
        opened.append(path)
        return sources[path]
    monkeypatch.setattr(recording, 'InputDevice', open_source)
    monkeypatch.setattr(recording.fcntl, 'ioctl', lambda *_args: 0)
    return opened


def test_recording_merges_interfaces_sorts_timestamps_and_excludes_synthetic_and_stop_key(app, monkeypatch):
    from evdev import ecodes as E
    a = RecordingSource('keyboard-a', [recording_event(10, E.EV_KEY, E.KEY_LEFTALT, 1),
                                      recording_event(10.05, E.EV_KEY, E.KEY_LEFTSHIFT, 0),
                                      recording_event(10.21, E.EV_KEY, E.KEY_LEFTALT, 0),
                                      recording_event(10.8, E.EV_KEY, E.KEY_F12, 1)], held=(E.KEY_LEFTSHIFT,))
    b = RecordingSource('keyboard-b', [recording_event(10.02, E.EV_KEY, E.KEY_LEFTALT, 1),
                                      recording_event(10.1, E.EV_KEY, E.KEY_H, 1),
                                      recording_event(10.2, E.EV_KEY, E.KEY_H, 0),
                                      recording_event(10.3, E.EV_KEY, E.KEY_LEFTALT, 0)])
    mouse = RecordingSource('mouse', [recording_event(10.5, E.EV_KEY, E.BTN_LEFT, 1),
                                      recording_event(10.6, E.EV_KEY, E.BTN_LEFT, 0),
                                      recording_event(10.65, E.EV_REL, E.REL_X, 5),
                                      recording_event(10.7, E.EV_REL, E.REL_WHEEL, -1)],
                            caps={E.EV_KEY: [E.BTN_LEFT], E.EV_REL: [E.REL_X, E.REL_WHEEL]})
    sources = {s.path: s for s in (a, b, mouse)}
    opened = setup_recording(monkeypatch, sources, virtual=('Gillete virtual input',))
    dialog = RecordingDialog()
    assert not opened
    dialog.begin()
    assert set(opened) == set(sources)
    # Dispatch the later events first; finishing drains the other interfaces.
    dialog.drain(b)
    dialog.drain(a)
    assert dialog.result() == dialog.DialogCode.Accepted
    steps = dialog.action.steps
    keys = [(s.kind, s.key) for s in steps if s.kind in ('down', 'up')]
    assert keys[:4] == [('down', 'KEY_LEFTALT'), ('down', 'KEY_H'), ('up', 'KEY_H'), ('up', 'KEY_LEFTALT')]
    assert len(keys) == 6 and all('F12' not in key and 'SHIFT' not in key for _, key in keys)
    assert [(s.axis, s.value) for s in steps if s.kind == 'relative'] == [('REL_WHEEL', -1)]
    assert [s.milliseconds for s in steps if s.kind == 'wait'][:3] == [100, 100, 100]
    assert all(s.closed for s in sources.values()) and not dialog.events and not dialog.sources
    shiboken6.delete(dialog)


def test_failed_recording_setup_and_dropped_events_can_restart_without_stale_keys(app, monkeypatch):
    from evdev import ecodes as E
    bad = RecordingSource('keyboard', fail_active=True)
    sources = {'keyboard': bad}
    setup_recording(monkeypatch, sources)
    dialog = RecordingDialog()
    dialog.begin()
    assert bad.closed and not dialog.sources and dialog.start_button.isEnabled()
    dropped = RecordingSource('keyboard', [recording_event(10, E.EV_KEY, E.KEY_A, 1),
                                           recording_event(10.1, E.EV_SYN, E.SYN_DROPPED, 0)])
    sources['keyboard'] = dropped
    dialog.begin()
    dialog.drain(dropped)
    assert dialog.action is None and dropped.closed and not dialog.events and not dialog.held
    assert dialog.start_button.isEnabled() and not dialog.stop_button.isEnabled()
    good = RecordingSource('keyboard', [recording_event(12, E.EV_KEY, E.KEY_B, 1),
                                       recording_event(15, E.EV_KEY, E.KEY_B, 0),
                                       recording_event(15.2, E.EV_KEY, E.KEY_F12, 1)])
    sources['keyboard'] = good
    dialog.timing.setCurrentIndex(1)
    dialog.fixed_delay.setValue(45)
    dialog.begin()
    # A signal queued before cleanup must not discard the fresh recording.
    dialog.drain(dropped)
    assert dialog.sources == [good]
    dialog.drain(good)
    assert dialog.action.steps == (Step('down', key='KEY_B'), Step('wait', milliseconds=45),
                                   Step('up', key='KEY_B'))
    assert good.closed
    shiboken6.delete(dialog)


def test_recording_stop_preserves_a_held_key_until_f12_and_accepts_media_interface(app, monkeypatch):
    from evdev import ecodes as E
    media = RecordingSource('media', [recording_event(10, E.EV_KEY, E.KEY_VOLUMEUP, 1),
                                      recording_event(10.4, E.EV_KEY, E.KEY_F12, 1)],
                            caps={E.EV_KEY: [E.KEY_VOLUMEUP]})
    setup_recording(monkeypatch, {'media': media})
    dialog = RecordingDialog()
    dialog.begin()
    dialog.drain(media)
    assert dialog.action.steps == (Step('down', key='KEY_VOLUMEUP'), Step('wait', milliseconds=400),
                                   Step('up', key='KEY_VOLUMEUP'))
    assert media.closed
    shiboken6.delete(dialog)


def test_editor_updates_hypershift_feedback_from_active_snapshot_without_reading_implicitly(app, tmp_path, monkeypatch):
    from gillete import hardware
    from gillete.compile_onboard import CONTROL_IDS
    from gillete.model import Layers
    from gillete.onboard import Location
    monkeypatch.setattr(hardware, 'inspect', lambda *_: (_ for _ in ()).throw(AssertionError('Implicit mouse read')))
    window = MainWindow(ProfileStore(tmp_path / 'profiles.json'))
    window.model.setCurrentIndex(1)
    profile = window.current()
    profile.common.shifted['side_1'] = Action('keys', keys=('KEY_F23',))
    profile.common.shifted['ring_finger'] = Action('keys', keys=('KEY_X',))
    window.refresh()
    assert 'unverified' in window.shift_status.text()
    records = {Location(1, c, layer): bytes((1, c, 0)) + bytes.fromhex('0202001e000000')
               for c in CONTROL_IDS[MODELS[1]].values() for layer in (0, 1)}
    records[Location(1, 0x39, 0)] = bytes((1, 0x39, 0)) + bytes.fromhex('0c013900000000')
    snapshot = hardware.Snapshot(0xE8, MODELS[1], 'test', 1, (1,), 1,
                                 set(CONTROL_IDS[MODELS[1]].values()), records, {})
    window.hardware.loaded(snapshot)
    assert 'Ring Finger (hold, stored at last read)' in window.shift_status.text()
    row = MODEL_CONTROLS[MODELS[1]].index('ring_finger')
    assert window.mapping.item(row, 2).text() == 'Stored HyperShift trigger (hold)'
    window.control_selector.select('ring_finger')
    window.control_selector.layer.setCurrentIndex(1)
    assert 'Stored HyperShift trigger' in window.control_selector.assignment.text()
    assert 'Stored HyperShift trigger' in window.control_selector.buttons['ring_finger'].toolTip()
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[2]))
    window.edit_mapping(row, 2)
    assert 'Normal assignment' in messages[-1]
    assert profile.common.shifted['ring_finger'].keys == ('KEY_X',)
    profile.overrides[MODELS[1]] = Layers(normal={'ring_finger': Action('disabled')})
    window.refresh()
    assert 'unreachable' in window.shift_status.text()
    window.hardware.invalidate()
    assert 'unverified' in window.shift_status.text()
    window.model.setCurrentIndex(0)
    assert 'Ring Finger (hold' not in window.shift_status.text()
    assert profile.common.shifted['ring_finger'].keys == ('KEY_X',)
    shiboken6.delete(window)
