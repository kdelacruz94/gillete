import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import sys

from evdev import ecodes
import pytest

from gillete import guided_service as guided
from gillete.compile_onboard import CONTROL_IDS, encode_action
from gillete.engine import Engine
from gillete.focus import ProfileCoordinator
from gillete.hardware import Snapshot
from gillete.hypershift import resolve_action
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, MODEL_CONTROLS, MODELS, Profile, Step
from gillete.onboard import Location, durable_json
from gillete.profiles import ProfileStore, Window
from gillete.stored_actions import decode, from_snapshot, unresolved
from gillete.validation_plan import RETIRED_V2_MACROS, action_label, assert_unchanged, bind_window, build, controls


def snapshot(model):
    records = {Location(1, c, l): bytes((1, c, 0)) + encode_action(Action('keys', keys=('KEY_1',)), model)
               for c in CONTROL_IDS[model].values() for l in (0, 1)}
    def put(control, shifted, function):
        where = Location(1, CONTROL_IDS[model][control], int(shifted))
        records[where] = bytes((1, where.control, 1)) + function
    for shifted in (False, True):
        put('left_click', shifted, encode_action(Action('keys', keys=('BTN_LEFT',)), model))
        put(controls(model)[0], shifted, encode_action(Action('hypershift', playback='held'), model))
        put('dpi_down', shifted, encode_action(Action('dpi', target='down'), model))
    if model == MODELS[0]:
        for control in RETIRED_V2_MACROS:
            put(control, True, bytes.fromhex('05020000000000'))
        for control, shifted, value in (('wheel_tilt_left', False, '0d04004b008e00'),
                                       ('wheel_tilt_right', False, '0d04004e008e00'),
                                       ('left_click', True, '0e0301008e0000'),
                                       ('side_7', True, '0d04001c008e00')):
            put(control, shifted, bytes.fromhex(value))
    else:
        put('profile_button', False, encode_action(Action('device', target='onboard_profile_cycle'), model))
    return Snapshot(0xB4 if model == MODELS[0] else 0xE8, model, 'private-test-identity', 1, (1,), 1,
                    set(CONTROL_IDS[model].values()), records, {'dpi': '01', 'stages': '02', 'polling': '01'})


@pytest.mark.parametrize('model', MODELS)
def test_plan_preserves_known_actions_and_lists_every_effective_override(model):
    before = snapshot(model)
    original = deepcopy(before)
    config, rows = build(before)
    stored, unknown = from_snapshot(before)
    assert before == original
    changes = {(r['control'], r['shifted']): r for r in rows}
    for profile in config.profiles.values():
        assert not unresolved(profile, model, stored)
    for control in MODEL_CONTROLS[model]:
        for shifted in (False, True):
            old = resolve_action(Profile('stored', 'Stored'), model, control, shifted, stored)
            outside = resolve_action(config.profiles['default'], model, control, shifted, stored)
            inside = resolve_action(config.profiles['validation'], model, control, shifted, stored)
            assert inside.kind not in {'dpi', 'device'} and outside.kind not in {'dpi', 'device'}
            assert ((control, shifted) in changes) == (not old == outside == inside)
    # Native pointer passthrough is essential for dragging across a focus change.
    assert config.profiles['validation'].resolve(model, 'left_click').kind == 'passthrough'
    if model == MODELS[0]:
        assert len(unknown) == 8
        for control in RETIRED_V2_MACROS:
            assert 'retired by user' in changes[control, True]['reason']
        for key in unknown:
            assert changes[key]['inside']['kind'] == changes[key]['outside']['kind'] == 'disabled'
        # A masked normal tilt does not hide its still-known shifted binding.
        assert resolve_action(config.profiles['default'], model, 'wheel_tilt_left', True, stored).keys == ('KEY_1',)
        assert decode(bytes.fromhex('05020000000000'), model) is None
    assert not config.startup_models and not config.pinned and not config.rules


@pytest.mark.parametrize('model', MODELS)
def test_plan_executes_both_layers_shortcut_and_focus_cancellation(model):
    async def check():
        before = snapshot(model)
        config, _ = build(before)
        bind_window(config, model, 'test[?]*', 'input[12]?*')
        window = Window('0x1', 'test[?]*', 'input[12]?*')
        assert config.select(model, window).id == 'validation'
        assert config.select(model, Window('0x2', 'testX', 'input1X')).id == 'default'
        other = next(m for m in MODELS if m != model)
        assert config.select(other, window).id == 'default'
        coordinator = ProfileCoordinator(config)
        output = RecordingOutput()
        stored, _ = from_snapshot(before)
        engine = Engine(model, config.profiles['default'], KeyLedger(output), stored=stored)
        await coordinator.attach(model, engine)
        await coordinator.focus_changed(window)
        trigger, turbo = controls(model)
        await engine.press('side_12')
        await engine.release('side_12')
        await engine.press(trigger)
        await engine.press('side_12')
        await engine.release('side_12')
        await engine.release(trigger)
        assert output.events == [('key', key, down) for key in (ecodes.KEY_F24, ecodes.KEY_F23) for down in (1, 0)]
        output.events.clear()
        await engine.press('side_11')
        await engine.release('side_11')
        await asyncio.gather(*engine.macros.jobs.values())
        assert output.events == [('key', ecodes.KEY_LEFTCTRL, 1), ('key', ecodes.KEY_K, 1),
                                 ('key', ecodes.KEY_K, 0), ('key', ecodes.KEY_LEFTCTRL, 0),
                                 ('key', ecodes.KEY_M, 1), ('key', ecodes.KEY_M, 0)]
        await engine.press(turbo)
        await engine.release(turbo)
        await asyncio.sleep(.01)
        assert engine.macros.jobs
        # Cancel while a synthetic 1 is still down; preserve a native pointer drag.
        await engine.press('left_click')
        await coordinator.focus_changed(Window('0x2', 'elsewhere'))
        assert not engine.macros.jobs and set(engine.ledger.holders) == {ecodes.BTN_LEFT}
        await engine.release('left_click')
        count = len(output.events)
        await coordinator.focus_changed(window)
        await asyncio.sleep(.01)
        assert not engine.ledger.holders and len(output.events) == count
        await coordinator.detach(model)
    asyncio.run(check())


@pytest.mark.parametrize('field', ['serial', 'records', 'settings', 'active', 'assigned', 'controls'])
def test_snapshot_comparison_detects_external_changes(field):
    before = snapshot(MODELS[0])
    after = deepcopy(before)
    values = {'serial': 'another', 'records': {}, 'settings': {}, 'active': 2, 'assigned': (1, 2), 'controls': set()}
    setattr(after, field, values[field])
    with pytest.raises(RuntimeError, match=field):
        assert_unchanged(before, after)
    after = deepcopy(before)
    after.metadata['battery'] = 'changed normally'
    assert_unchanged(before, after)


@pytest.mark.parametrize('field', ['firmware', 'wheel_mode'])
def test_known_firmware_and_wheel_state_are_preserved_but_battery_changes_are_not_failures(field):
    before = snapshot(MODELS[1])
    before.metadata[field] = '0100'
    after = deepcopy(before)
    after.metadata['battery'] = 'changed normally'
    assert_unchanged(before, after)
    after.metadata.pop(field)
    with pytest.raises(RuntimeError, match=field): assert_unchanged(before, after)
    after.metadata[field] = '0101'
    with pytest.raises(RuntimeError, match=field): assert_unchanged(before, after)


def test_macro_review_describes_actual_keys_and_timing_instead_of_assuming_the_shortcut_example():
    action = Action('macro', steps=(Step('down', key='KEY_F24'), Step('wait', milliseconds=80), Step('up', key='KEY_F24')))
    label = action_label(action.json())
    assert 'F24' in label and '80 ms' in label and 'Ctrl' not in label


def prepare_fake(tmp_path, monkeypatch, model=MODELS[0]):
    before = snapshot(model)
    monkeypatch.setattr(guided, 'socket_path', lambda: tmp_path / 'socket')
    monkeypatch.setattr(guided, 'connected', lambda product: SimpleNamespace(product_id=product))
    monkeypatch.setattr(guided, 'inspect', lambda *args: deepcopy(before))
    directory = tmp_path / 'acceptance'
    guided.prepare(before.product, directory)
    return directory, before


def test_prepare_is_read_only_private_and_run_rejects_stale_settings(tmp_path, monkeypatch, capsys):
    async def forbidden(*args, **kwargs): raise AssertionError('No subprocess during preparation/preflight')
    monkeypatch.setattr(guided.asyncio, 'create_subprocess_exec', forbidden)
    directory, before = prepare_fake(tmp_path, monkeypatch)
    assert 'private-test-identity' not in capsys.readouterr().out
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'prepared.json').stat().st_mode & 0o777 == 0o600
    before.settings['polling'] = '02'
    with pytest.raises(RuntimeError, match='settings'):
        asyncio.run(guided.run(directory, 30))
    assert not (directory / 'run').exists()


class Child:
    def __init__(self, pid):
        self.pid, self.returncode = pid, None
        self.terminated = False
    async def wait(self):
        if self.returncode is None:
            raise AssertionError('Mock child should already have stopped')
        return self.returncode
    def terminate(self):
        self.terminated, self.returncode = True, 0


@pytest.mark.parametrize('failure', ['none', 'window_closed', 'wrong_service', 'readiness_disk_full'])
def test_controller_binds_commands_waits_for_profile_and_cleans_up(tmp_path, monkeypatch, failure):
    directory, before = prepare_fake(tmp_path, monkeypatch)
    pad, daemon = Child(101), Child(102)
    config_path = directory / 'run/profiles.json'
    calls, focus_checks = [], []
    state = {}
    original_write = durable_json
    def write(path, doc):
        if path.name == 'ready.json':
            assert state['active'] and state['profile'] == 'validation'
            if failure == 'readiness_disk_full': raise OSError('Disk full')
        original_write(path, doc)
    monkeypatch.setattr(guided, 'durable_json', write)
    async def spawn(*args, **kwargs):
        if 'gillete.validation_pad' in args:
            pad.title = args[args.index('--title') + 1]
            if failure == 'window_closed': pad.returncode = 0
            return pad
        assert kwargs['env']['XDG_STATE_HOME'] == str(directory / 'run/state')
        assert str(config_path) in args
        return daemon
    async def clients():
        return [{'pid': pad.pid, 'class': 'test[*]', 'title': pad.title, 'address': '0x1'}]
    async def request(name, **kwargs):
        assert kwargs['config_path'] == config_path
        calls.append(name)
        if name == 'shutdown':
            daemon.returncode = 0
            return {}
        if failure == 'wrong_service':
            daemon.returncode = 1  # Its lock failed; another config owns the socket.
            raise RuntimeError('A different profile file is already running')
        if name == 'enable':
            assert kwargs['model'] == before.model
            state.update(active=True, profile='default')
            return {}
        if state.get('active'):
            focus_checks.append(state['profile'])
            if len(focus_checks) == 2:
                state['profile'] = 'validation'
            elif len(focus_checks) == 3:
                assert (directory / 'run/ready.json').exists()
                pad.returncode = 0
        return {'focus_available': True, 'suspend_monitor': True, 'suspended': False,
                'focus': {'address': '0x1'}, 'devices': {before.model: {
                    'active': state.get('active', False), 'profile': state.get('profile'),
                    'requested': True, 'active_macros': 0, 'error': ''}}}
    monkeypatch.setattr(guided.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(guided, 'clients', clients)
    monkeypatch.setattr(guided, 'request', request)
    if failure in {'none', 'window_closed'}:
        asyncio.run(guided.run(directory, 30))
    else:
        with pytest.raises((RuntimeError, OSError), match='different profile|Disk full'):
            asyncio.run(guided.run(directory, 30))
    assert pad.returncode is not None
    assert json.loads((directory / 'run/restoration.json').read_text())['stored_state_unchanged']
    if failure == 'window_closed': assert not calls
    if failure == 'wrong_service': assert calls == ['status']  # No shutdown to a replacement service.
    if failure == 'none':
        assert focus_checks == ['default', 'default', 'validation']
        config = ProfileStore(config_path).read()
        assert config.select(before.model, Window('0x1', 'test[*]', pad.title)).id == 'validation'
    with pytest.raises(FileExistsError):
        asyncio.run(guided.run(directory, 30))


def test_mode_recovery_precedes_log_failure_and_uses_only_test_journals(tmp_path, monkeypatch):
    before = snapshot(MODELS[0])
    path = tmp_path / 'state/gillete/onboard/mode-test.json'
    durable_json(path, {'version': 1, 'kind': 'driver-mode', 'product': before.product,
                       'serial': before.serial, 'before': '0000', 'status': 'driver-mode-active'})
    class IO:
        product, mode = before.product, b'\3\0'
        writes = []
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def device_serial(self): return before.serial
        def execute(self, command): return self.mode
        def _exchange(self, command):
            self.writes.append(command)
            self.mode = command.payload
    io = IO()
    monkeypatch.setattr(guided, 'transport', lambda _: io)
    def inspect(*args):
        assert io.mode == b'\0\0'
        return before
    monkeypatch.setattr(guided, 'inspect', inspect)
    def fail_log(*args): raise OSError('Disk full')
    monkeypatch.setattr(guided, 'durable_json', fail_log)
    with pytest.raises(RuntimeError, match='Disk full'):
        asyncio.run(guided.cleanup(tmp_path, None, None, tmp_path / 'profiles.json', None, before, []))
    assert len(io.writes) == 1 and io.mode == b'\0\0'
    assert json.loads(path.read_text())['status'] == 'normal-mode-restored'


def test_failed_restoration_never_claims_success(tmp_path, monkeypatch, capsys):
    before = snapshot(MODELS[0])
    def unavailable(*args): raise OSError('Mouse disconnected')
    monkeypatch.setattr(guided, 'inspect', unavailable)
    with pytest.raises(RuntimeError, match='Mouse disconnected'):
        asyncio.run(guided.cleanup(tmp_path, None, None, tmp_path / 'profiles.json', None, before, []))
    assert 'RESTORED' not in capsys.readouterr().out
    assert not json.loads((tmp_path / 'restoration.json').read_text())['normal_mode_verified']


def test_cancelled_window_query_reaps_its_child_without_querying_the_desktop(monkeypatch):
    async def check():
        spawn = asyncio.create_subprocess_exec
        child = None
        started = asyncio.Event()
        async def harmless_child(*args, **kwargs):
            nonlocal child
            child = await spawn(sys.executable, '-c', 'import time; time.sleep(60)', **kwargs)
            started.set()
            return child
        monkeypatch.setattr(guided.asyncio, 'create_subprocess_exec', harmless_child)
        task = asyncio.create_task(guided.clients())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert child.returncode is not None
    asyncio.run(check())
