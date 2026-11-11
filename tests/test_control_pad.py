import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from copy import deepcopy
import json

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
import pytest
import shiboken6

from gillete import control_pad
from gillete.control_validation import validate_results
from gillete.model import MODELS
from gillete.onboard import durable_json
from test_control_validation import Clock, NONCE, complete_report


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    application.closeAllWindows()
    application.processEvents()
    for window in application.topLevelWidgets(): shiboken6.delete(window)
    shiboken6.delete(application)


def create(tmp_path, monkeypatch, model=MODELS[0]):
    clock = Clock()
    monkeypatch.setattr(control_pad, 'time', type('Time', (), {'monotonic': staticmethod(clock)})())
    result_path, state_path, ready_path = [tmp_path / name for name in ('coverage.json', 'state.json', 'ready.json')]
    durable_json(ready_path, {'version': 1, 'model': model, 'title': 'Controls', 'seconds': 600, 'nonce': NONCE})
    pad = control_pad.ControlPad(result_path, state_path, ready_path,
                                model=model, title='Controls', seconds=600, nonce=NONCE)
    pad.timer.stop()
    monkeypatch.setattr(pad, 'isActiveWindow', lambda: True)
    return pad, clock


def initial_for(result):
    initial = deepcopy(result['final_packet'])
    initial['t'] = result['armed_at']
    initial['trace']['t'] = result['armed_at']
    initial['trace'].update(sequence=result['after_seq'], entries=[])
    return initial


def deliver(pad, clock, event):
    keys = {'Shift': Qt.Key.Key_Shift, 'Ctrl': Qt.Key.Key_Control, 'Alt': Qt.Key.Key_Alt,
            **{f'F{i}': getattr(Qt.Key, f'Key_F{i}') for i in range(13, 25)}}
    flags = Qt.KeyboardModifier.NoModifier
    for name, flag in (('Shift', Qt.KeyboardModifier.ShiftModifier), ('Ctrl', Qt.KeyboardModifier.ControlModifier),
                        ('Alt', Qt.KeyboardModifier.AltModifier)):
        if name in event['modifiers']: flags |= flag
    clock.t = event['t']
    incoming = QKeyEvent(QEvent.Type.KeyPress if event['direction'] == 'down' else QEvent.Type.KeyRelease,
                         keys[event['key']], flags, autorep=event.get('repeat', False))
    assert pad.eventFilter(pad, incoming)


@pytest.mark.parametrize('model', MODELS)
def test_guided_window_observes_every_pair_and_rotates_trigger_profile_without_activating_any_service(app, tmp_path, monkeypatch, model):
    pad, clock = create(tmp_path, monkeypatch, model)
    original = complete_report(model)
    try:
        for index, result in enumerate(original['passed']):
            clock.t = result['armed_at']
            durable_json(pad.state_path, initial_for(result))
            pad.refresh()
            assert pad.trial is not None and pad.index == index
            assert 'READY' in pad.status.text()
            assert result['step']['control'].replace('_', ' ').split()[0] in pad.prompt.text().lower() or result['step']['control'] in ('dpi_up', 'dpi_down', 'top_front', 'top_rear', 'profile_button')
            for event in result['qt']: deliver(pad, clock, event)
            final = deepcopy(result['final_packet'])
            final['trace']['entries'] = result['physical']
            clock.t = final['t']
            durable_json(pad.state_path, final)
            pad.refresh()
            assert pad.index == index + 1
        document = json.loads(pad.path.read_text())
        assert validate_results(document, model, NONCE)
        assert 'alternate trigger' in pad.windowTitle()
        assert not document['failed_attempts'] and not pad.timer.isActive()
    finally:
        pad.close()
        shiboken6.delete(pad)


def test_wrong_key_retains_failed_attempt_and_retry_does_not_reuse_old_input(app, tmp_path, monkeypatch):
    pad, clock = create(tmp_path, monkeypatch)
    sample = complete_report()['passed'][0]
    try:
        durable_json(pad.state_path, initial_for(sample))
        pad.refresh()
        for event in sample['qt']:
            wrong = dict(event, key='F24')
            deliver(pad, clock, wrong)
        clock.advance(.3)
        current = initial_for(sample)
        current['t'] = clock()
        current['trace']['t'] = clock()
        durable_json(pad.state_path, current)
        pad.refresh()
        assert pad.trial.error and 'retry' in pad.status.text().lower()
        assert len(pad.document['failed_attempts']) == 1 and pad.index == 0
        retry = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier)
        pad.eventFilter(pad, retry)
        assert pad.trial is None
        pad.refresh()
        assert pad.trial is not None and not pad.trial.qt and not pad.trial.physical
        assert pad.trial.armed_at == clock() and len(pad.document['failed_attempts']) == 1
    finally:
        pad.close()
        assert json.loads(pad.path.read_text())['status'] == 'incomplete'
        shiboken6.delete(pad)


@pytest.mark.parametrize('problem', ['ready-nonce', 'state-nonce', 'stale', 'wrong-profile', 'held-control', 'focus', 'keyboard-modifier'])
def test_unready_or_stale_evidence_never_arms_a_tap(app, tmp_path, monkeypatch, problem):
    pad, clock = create(tmp_path, monkeypatch)
    sample = complete_report()['passed'][0]
    state = initial_for(sample)
    if problem == 'ready-nonce': durable_json(pad.ready_path, {'nonce': 'wrong'})
    elif problem == 'state-nonce': state['nonce'] = 'wrong'
    elif problem == 'stale': clock.advance(3)
    elif problem == 'wrong-profile': state['trace']['profile'] = 'default'
    elif problem == 'held-control': state['trace']['held'] = ['side_1']
    elif problem == 'keyboard-modifier': monkeypatch.setattr(QApplication, 'keyboardModifiers', lambda: Qt.KeyboardModifier.ShiftModifier)
    else: state['focused'] = False
    durable_json(pad.state_path, state)
    try:
        pad.poll()
        assert pad.trial is None and not pad.document['passed']
        if problem.endswith('nonce'): assert pad.document['status'] == 'error'
    finally:
        pad.close()
        shiboken6.delete(pad)


def test_closing_or_escape_keeps_incomplete_evidence_and_never_claims_completion(app, tmp_path, monkeypatch):
    pad, clock = create(tmp_path, monkeypatch)
    sample = complete_report()['passed'][0]
    durable_json(pad.state_path, initial_for(sample))
    pad.refresh()
    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    pad.eventFilter(pad, escape)
    saved = json.loads(pad.path.read_text())
    assert saved['status'] == 'incomplete' and not saved['passed'] and 'unfinished' in saved
    assert not pad.timer.isActive()
    shiboken6.delete(pad)


def test_failed_completion_write_cannot_leave_a_verified_report(app, tmp_path, monkeypatch):
    pad, clock = create(tmp_path, monkeypatch)
    pad.document = complete_report()
    original = control_pad.durable_json
    def failed(path, document):
        if document['status'] == 'complete': raise OSError('Disk full')
        original(path, document)
    monkeypatch.setattr(control_pad, 'durable_json', failed)
    monkeypatch.setattr(pad, 'refresh', pad.persist)
    pad.poll()
    saved = json.loads(pad.path.read_text())
    assert saved['status'] == 'error' and 'Disk full' in saved['error']
    with pytest.raises(ValueError): validate_results(saved, MODELS[0], NONCE)
    shiboken6.delete(pad)


def test_oversized_evidence_preserves_the_last_partial_file_and_still_closes(app, tmp_path, monkeypatch):
    pad, clock = create(tmp_path, monkeypatch)
    before = pad.path.read_bytes()
    pad.document['failed_attempts'].append({'large': 'x' * (768 * 1024)})
    with pytest.raises(ValueError, match='size limit'): pad.persist()
    pad.close()
    assert pad.path.read_bytes() == before and not pad.timer.isActive()
    shiboken6.delete(pad)
