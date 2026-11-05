import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from gillete import hardware
from gillete.compile_onboard import CONTROL_IDS
from gillete.device_action_support import issues, support
from gillete.device_controls import Controls
from gillete.device_session import DeviceSession
from gillete.devices import Device
from gillete.engine import Engine
from gillete.focus import ProfileCoordinator
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODEL_CONTROLS, MODELS, Profile
from gillete.onboard import Location
from gillete.profiles import Configuration, ProfileStore, Rule
from gillete.protocol import ProtocolError
from gillete.service import Daemon


def snapshot(model=MODELS[1]):
    product = 0xB4 if model == MODELS[0] else 0xE8
    records = {Location(1, c, layer): bytes((1, c, 0)) + bytes.fromhex('00010000000000')
               for c in CONTROL_IDS[model].values() for layer in (0, 1)}
    return hardware.Snapshot(product, model, 'test', 1, (1,), 1, set(CONTROL_IDS[model].values()), records,
                             {'dpi': '01070807080000', 'stages': '01010101032003200000' + '00' * 28},
                             {'wheel_mode': '0100'} if model == MODELS[1] else {})


def stored(model):
    return {(c, s): Action('disabled') for c in MODEL_CONTROLS[model] for s in (False, True)}


@pytest.mark.parametrize('target', ['wheel_mode_cycle', 'onboard_profile_cycle'])
def test_native_actions_are_v3_only_even_when_v2_has_a_single_slot(tmp_path, target):
    action = Action('device', target=target)
    state = support(action, MODELS[0], snapshot(MODELS[0]))
    assert state.available is False and 'Naga V3 Pro' in state.text
    with pytest.raises(ProtocolError, match='only on the V3'):
        Controls(SimpleNamespace(product=0xB4), snapshot(MODELS[0]), tmp_path).native(target)
    assert not list(tmp_path.iterdir())


def test_single_onboard_slot_is_no_effect_and_multiple_slots_are_unavailable(tmp_path):
    action = Action('device', target='onboard_profile_cycle')
    before = snapshot()
    assert support(action, MODELS[1]).available is None
    assert support(action, MODELS[1], before).available is True
    assert 'No effect' in support(action, MODELS[1], before).text
    # No query or setter adapter is needed for a genuine single-slot no-op.
    Controls(SimpleNamespace(product=0xE8), before, tmp_path).native(action.target)
    before.assigned = (1, 3)
    state = support(action, MODELS[1], before)
    assert state.available is False and 'Switch profile' in state.text
    with pytest.raises(ProtocolError, match='Multiple onboard-bank'):
        Controls(SimpleNamespace(product=0xE8), before, tmp_path).native(action.target)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('field,value', [('dpi', None), ('stages', None), ('dpi', '02070807080000'),
                                       ('dpi', 'not hex'), ('stages', '0100')])
def test_dpi_requires_valid_current_scalar_and_stage_table(field, value):
    before = snapshot(MODELS[0])
    action = Action('dpi', target='up')
    assert support(action, MODELS[0]).available is None
    # A valid custom scalar differs from the selected stage; do not reject it.
    assert support(action, MODELS[0], before).available is True
    if value is None:
        before.settings.pop(field)
    else:
        before.settings[field] = value
    assert support(action, MODELS[0], before).available is False


@pytest.mark.parametrize('value', [None, '0103', '0000', '01', 'invalid'])
def test_wheel_action_requires_recognized_readback_without_claiming_physical_acceptance(value):
    before = snapshot()
    action = Action('device', target='wheel_mode_cycle')
    assert support(action, MODELS[1], before).available is True
    assert 'validation is pending' in support(action, MODELS[1], before).text
    if value is None:
        before.metadata.clear()
    else:
        before.metadata['wheel_mode'] = value
    assert support(action, MODELS[1], before).available is False
    assert support(action, MODELS[1], snapshot(MODELS[0])).available is None


def test_effective_overrides_and_inherited_hypershift_mask_unavailable_native_actions():
    profile = Profile('p', 'P', Layers(normal={'side_1': Action('device', target='wheel_mode_cycle')},
                                     shifted={'side_2': Action('device', target='onboard_profile_cycle')}))
    profile.overrides[MODELS[0]] = Layers(normal={'side_1': Action('keys', keys=('KEY_A',))})
    memory = stored(MODELS[0])
    memory['side_2', False] = Action('hypershift', playback='held')
    assert not issues(profile, MODELS[0], memory, snapshot(MODELS[0]))
    del memory['side_2', False]
    problems = issues(profile, MODELS[0], memory, snapshot(MODELS[0]))
    assert len(problems) == 1 and problems[0].startswith('side_2 (HyperShift)')


@pytest.mark.parametrize('model,action,mutation', [
    (MODELS[0], Action('device', target='wheel_mode_cycle'), lambda s: None),
    (MODELS[1], Action('device', target='onboard_profile_cycle'), lambda s: setattr(s, 'assigned', (1, 2))),
    (MODELS[0], Action('dpi', target='up'), lambda s: s.settings.clear()),
    (MODELS[1], Action('device', target='wheel_mode_cycle'), lambda s: s.metadata.clear()),
])
def test_invalid_device_actions_reject_startup_before_output_or_input_ownership(tmp_path, monkeypatch, model, action, mutation):
    import gillete.device_session as sessions
    before = snapshot(model)
    mutation(before)
    monkeypatch.setattr(sessions, 'inspect', lambda device: before)
    def forbidden(*args):
        raise AssertionError('Preflight must precede input ownership or device settings')
    monkeypatch.setattr(sessions, 'UInputOutput', forbidden)
    monkeypatch.setattr(sessions, 'transport', forbidden)
    async def check():
        config = Configuration(profiles={'default': Profile('default', 'Default', Layers(normal={'side_12': action}))})
        coordinator = ProfileCoordinator(config)
        coordinator.available = True
        session = DeviceSession(Device(model, 'Test', '2.4 GHz', before.product, '/test', 'test'), coordinator, tmp_path, None)
        monkeypatch.setattr(session, 'open_inputs', forbidden)
        await session.run()
        assert 'Device-action configuration needs attention' in session.error
        assert 'side_12' in session.error and not session.ready and not list(tmp_path.iterdir())
    asyncio.run(check())


def test_inactive_invalid_action_can_be_saved_but_pin_and_enabled_rule_reject_it(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = Configuration()
        config.profiles['draft'] = Profile('draft', 'Draft', Layers(normal={
            'side_12': Action('device', target='wheel_mode_cycle')}))
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        device = Device(MODELS[0], 'Test', '2.4 GHz', 0xB4, '/test', 'test')
        session = DeviceSession(device, daemon.coordinator, tmp_path, daemon.pin)
        session.snapshot = snapshot(MODELS[0])
        session.engine = Engine(MODELS[0], config.profiles['default'], KeyLedger(RecordingOutput()), stored=stored(MODELS[0]))
        daemon.sessions[MODELS[0]] = session
        daemon.requested.add(MODELS[0])
        session.validate_profiles(config)
        original = store.path.read_bytes()
        with pytest.raises(ProtocolError, match='Naga V3 Pro'):
            await daemon.command({'command': 'pin', 'model': MODELS[0], 'profile': 'draft'})
        assert store.path.read_bytes() == original and not session.stop_requested.is_set()
        config = store.read()
        config.rules = [Rule('draft', app_class='future game')]
        store.save(config, expected_revision=config.revision)
        await daemon.reload_config()
        assert 'Device-action configuration' in daemon.config_error and session.stop_requested.is_set()
        assert not daemon.requested and session.engine.profile.id == 'default'
    asyncio.run(check())


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('unavailable', [False, True])
def test_inspection_queries_wheel_only_on_v3_and_retains_optional_failure(tmp_path, monkeypatch, model, unavailable):
    before = snapshot(model)
    queries = []
    class IO:
        product = before.product
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def require_normal_mode(self): pass
        def device_serial(self): return 'test'
        def execute(self, command):
            queries.append((command.category, command.operation, command.payload))
            if (command.category, command.operation) == (2, 0xB0):
                assert command.payload == b'\1\0'
                if unavailable:
                    raise ProtocolError('Wheel query unavailable')
                return b'\1\2'
            return bytes(len(command.payload))
    monkeypatch.setattr(hardware, 'transport', lambda device: IO())
    monkeypatch.setattr(hardware, 'profile_slots', lambda io: ((1,), 1))
    monkeypatch.setattr(hardware, 'inventory', lambda io: before.controls)
    monkeypatch.setattr(hardware, 'read_records', lambda *args: deepcopy(before.records))
    result = hardware.inspect(Device(model, 'Test', '2.4 GHz', before.product, '/test', 'test'))
    if model == MODELS[0]:
        assert not any(pair[:2] == (2, 0xB0) for pair in queries)
        assert 'wheel_mode' not in result.metadata and 'wheel_mode_error' not in result.metadata
    elif unavailable:
        assert result.metadata['wheel_mode_error'] == 'Wheel query unavailable'
    else:
        assert result.metadata['wheel_mode'] == '0102'
    assert result.records == before.records


def test_runtime_rechecks_wheel_mode_before_any_write(tmp_path):
    before = snapshot()
    class IO:
        product = 0xE8
        def execute(self, command): return b'\1\5'
        def _exchange(self, command): raise AssertionError('Invalid wheel readback must not be written')
    with pytest.raises(ProtocolError, match='Unrecognized wheel-mode'):
        Controls(IO(), before, tmp_path).native('wheel_mode_cycle')
    assert not list(tmp_path.iterdir())
