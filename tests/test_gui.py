import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from copy import deepcopy
import pytest
import shiboken6
from PySide6.QtWidgets import QApplication, QMessageBox

from gillete.gui import ActionDialog, MainWindow
from gillete.model import Action, MODEL_CONTROLS, MODELS, Profile
from gillete.gui_controls import ControlSelector
from gillete.gui_applications import ApplicationPicker
from gillete.profiles import Window
from gillete.profiles import ProfileStore
from gillete.gui_settings import SettingsDialog, SettingsPreview
from gillete.gui_startup import StartupPanel
from gillete.startup import AutostartEntry
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
