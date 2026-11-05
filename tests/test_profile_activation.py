import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gillete.compile_onboard import CONTROL_IDS
from gillete.device_session import DeviceSession
from gillete.devices import Device
from gillete.engine import Engine
from gillete.focus import ProfileCoordinator
from gillete.hardware import Snapshot
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODEL_CONTROLS, MODELS, Profile
from gillete.onboard import Location
from gillete.profile_activation import reachable_profiles
from gillete.profile_transfer import export_document, parse_bundle, plan_import
from gillete.profiles import Configuration, ProfileStore, Rule, Window
from gillete.protocol import ProtocolError
from gillete.service import Daemon


def stored_actions(model):
    return {(control, shifted): Action('disabled')
            for control in MODEL_CONTROLS[model] for shifted in (False, True)}


def unfinished(identifier='draft'):
    return Profile(identifier, 'Unfinished ' + identifier,
                   Layers(shifted={'side_1': Action('keys', keys=('KEY_F23',))}))


def session_for(coordinator, model, tmp_path, pin=None):
    device = Device(model, 'Test mouse', '2.4 GHz', 0xB4 if model == MODELS[0] else 0xE8, '/test', 'test')
    session = DeviceSession(device, coordinator, tmp_path, pin)
    session.engine = Engine(model, coordinator.config.select(model, coordinator.window),
                            KeyLedger(RecordingOutput()), stored=stored_actions(model),
                            select_profile=lambda target: session.enqueue('profile', target))
    return session


def test_graph_uses_effective_model_layers_controls_rules_and_inherited_triggers():
    config = Configuration()
    names = ('common', 'v2', 'v3', 'shifted', 'masked', 'stored-masked', 'both-rule', 'v3-rule', 'disabled-rule')
    config.profiles.update({name: Profile(name, name) for name in names})
    root = config.profiles['default']
    root.common = Layers(normal={'side_1': Action('profile', target='common'),
                                 'dpi_up': Action('hypershift', playback='held'),
                                 'ring_finger': Action('profile', target='v3')},
                         shifted={'side_2': Action('profile', target='shifted'),
                                  'dpi_up': Action('profile', target='masked'),
                                  'wheel_click': Action('profile', target='stored-masked')})
    root.overrides[MODELS[0]] = Layers(normal={'side_1': Action('profile', target='v2')})
    config.profiles['v2'].common.normal['side_3'] = Action('profile', target='default')
    config.rules = [Rule('both-rule', app_class='a future window'),
                    Rule('v3-rule', app_class='another window', model=MODELS[1]),
                    Rule('disabled-rule', app_class='code', enabled=False)]
    for model in MODELS:
        stored = stored_actions(model)
        stored['wheel_click', False] = Action('hypershift', playback='held')
        expected = {'default', 'shifted', 'both-rule'} | ({'v2'} if model == MODELS[0] else {'common', 'v3', 'v3-rule'})
        assert {p.id for p in reachable_profiles(config, model, stored)} == expected


def test_pin_selects_only_its_graph_until_automatic_is_chosen():
    config = Configuration()
    config.profiles.update({key: Profile(key, key) for key in ('pinned', 'linked', 'automatic')})
    config.profiles['pinned'].common.shifted['side_1'] = Action('profile', target='linked')
    config.profiles['linked'].common.normal['side_2'] = Action('profile', target='pinned')
    config.rules = [Rule('automatic', app_class='code')]
    config.pinned[MODELS[0]] = 'pinned'
    assert {p.id for p in reachable_profiles(config, MODELS[0], stored_actions(MODELS[0]))} == {'pinned', 'linked'}
    assert {p.id for p in reachable_profiles(config, MODELS[1], stored_actions(MODELS[1]))} == {'default', 'automatic'}
    config.pinned.clear()
    assert {p.id for p in reachable_profiles(config, MODELS[0], stored_actions(MODELS[0]))} == {'default', 'automatic'}


def test_large_cyclic_graph_does_not_recurse_or_drop_profiles():
    config = Configuration(profiles={str(i): Profile(str(i), str(i), Layers(normal={
        'side_1': Action('profile', target=str((i + 1) % 1000))})) for i in range(1000)},
        defaults={model: '0' for model in MODELS})
    assert len(reachable_profiles(config, MODELS[0], stored_actions(MODELS[0]))) == 1000


@pytest.mark.parametrize('model', MODELS)
def test_unused_draft_and_disabled_rule_do_not_block_preflight_but_enabled_rule_does(tmp_path, model):
    config = Configuration()
    config.profiles['draft'] = unfinished()
    config.rules = [Rule('draft', app_class='not-currently-focused', model=model, enabled=False)]
    session = session_for(ProfileCoordinator(config), model, tmp_path)
    session.validate_profiles(config)
    config.rules[0] = replace(config.rules[0], enabled=True)
    with pytest.raises(ProtocolError, match='Unfinished draft.*Assign HyperShift'):
        session.validate_profiles(config)


@pytest.mark.parametrize('shifted', [False, True])
def test_unknown_stored_action_is_rejected_in_button_destination_even_with_disabled_rule(tmp_path, shifted):
    config = Configuration()
    config.profiles['linked'] = Profile('linked', 'Linked profile')
    config.rules = [Rule('linked', app_class='code', enabled=False)]
    root = config.profiles['default']
    root.common.normal = {'side_12': Action('disabled'), 'dpi_up': Action('hypershift', playback='held')}
    (root.common.shifted if shifted else root.common.normal)['side_1'] = Action('profile', target='linked')
    session = session_for(ProfileCoordinator(config), MODELS[0], tmp_path)
    del session.engine.stored['side_12', False]
    with pytest.raises(ProtocolError, match='Linked profile: side_12.*normal'):
        session.validate_profiles(config)
    config.profiles['linked'].common.normal['side_12'] = Action('disabled')
    session.validate_profiles(config)


def test_model_specific_rule_does_not_require_other_mouses_trigger(tmp_path):
    config = Configuration()
    config.profiles['draft'] = unfinished()
    config.profiles['draft'].overrides[MODELS[1]] = Layers(normal={'ring_finger': Action('hypershift', playback='held')})
    config.rules = [Rule('draft', app_class='game', model=MODELS[1])]
    for model in MODELS:
        session_for(ProfileCoordinator(config), model, tmp_path).validate_profiles(config)
    config.rules[0] = replace(config.rules[0], model='')
    with pytest.raises(ProtocolError, match='Assign HyperShift'):
        session_for(ProfileCoordinator(config), MODELS[0], tmp_path).validate_profiles(config)


@pytest.mark.parametrize('model,product', tuple(zip(MODELS, (0xB4, 0xE8))))
def test_startup_allows_unused_draft_before_output_setup_without_mouse_ownership(tmp_path, monkeypatch, model, product):
    import gillete.device_session as sessions
    snapshot = Snapshot(product, model, 'test', 1, (1,), 1, set(CONTROL_IDS[model].values()),
                        {Location(1, c, l): bytes((1, c, 0)) + bytes.fromhex('00010000000000')
                         for c in CONTROL_IDS[model].values() for l in (0, 1)}, {})
    monkeypatch.setattr(sessions, 'inspect', lambda _: snapshot)
    def forbidden(*args):
        raise AssertionError('Stopped startup must not claim input or change mouse mode')
    monkeypatch.setattr(sessions, 'transport', forbidden)
    async def check():
        config = Configuration()
        config.profiles['draft'] = unfinished()
        coordinator = ProfileCoordinator(config)
        coordinator.available = True
        session = DeviceSession(SimpleNamespace(model=model, product_id=product), coordinator, tmp_path, None)
        observed = []
        class Output:
            def __init__(self, suffix): observed.append('created')
            async def prepare_keyboard(self):
                observed.append('prepared')
                session.stop_requested.set()
            async def restore_keyboard(self): observed.append('restored')
            def close(self): observed.append('closed')
        monkeypatch.setattr(sessions, 'UInputOutput', Output)
        monkeypatch.setattr(session, 'open_inputs', forbidden)
        await session.run()
        assert observed == ['created', 'prepared', 'restored', 'closed']
        assert not session.error and not session.ready and not list(tmp_path.iterdir())
    asyncio.run(check())


def turbo_profile(identifier):
    return Profile(identifier, identifier, Layers(normal={'side_1': Action(
        'turbo', keys=('KEY_1',), playback='toggle', press_ms=500, interval_ms=1000)}))


async def attach(daemon, tmp_path):
    session = session_for(daemon.coordinator, MODELS[0], tmp_path, daemon.pin)
    daemon.sessions[MODELS[0]] = session
    daemon.requested.add(MODELS[0])
    await daemon.coordinator.attach(MODELS[0], session.engine)
    session.ready = True
    return session


async def start_turbo(engine):
    await engine.press('side_1')
    await engine.release('side_1')
    await asyncio.sleep(0)
    assert engine.macros.jobs and engine.ledger.holders


def test_importing_inactive_draft_keeps_current_profile_and_running_action(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = Configuration(profiles={'default': turbo_profile('default')})
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        await daemon.coordinator.focus_changed(Window('a', 'code'))
        session = await attach(daemon, tmp_path)
        try:
            await start_turbo(session.engine)
            jobs, generation = dict(session.engine.macros.jobs), session.engine.generation
            source = Configuration()
            source.profiles['draft'] = unfinished()
            source.rules = [Rule('draft', app_class='code')]
            bundle = parse_bundle(export_document(source, 'draft'))
            imported = plan_import(store.read(), bundle).configuration()
            store.save(imported, expected_revision=imported.revision)
            await daemon.reload_config()
            assert not daemon.config_error and not session.stop_requested.is_set()
            assert daemon.coordinator.config.profiles['draft'].json() == source.profiles['draft'].json()
            assert session.engine.profile.id == 'default' and session.engine.generation == generation
            assert session.engine.macros.jobs == jobs and session.engine.ledger.holders
        finally:
            await daemon.coordinator.detach(MODELS[0])
    asyncio.run(check())


def test_disabling_active_rule_releases_turbo_and_reenabling_requires_new_press(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = Configuration()
        config.profiles['game'] = turbo_profile('game')
        config.rules = [Rule('game', app_class='game')]
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        await daemon.coordinator.focus_changed(Window('a', 'game'))
        session = await attach(daemon, tmp_path)
        try:
            await start_turbo(session.engine)
            changed = store.read()
            changed.rules[0] = replace(changed.rules[0], enabled=False)
            store.save(changed, expected_revision=changed.revision)
            await daemon.reload_config()
            assert not daemon.config_error and not session.stop_requested.is_set()
            assert session.engine.profile.id == 'default'
            assert not session.engine.macros.jobs and not session.engine.ledger.holders
            assert [value for _, _, value in session.engine.ledger.output.events] == [1, 0]
            changed.rules[0] = replace(changed.rules[0], enabled=True)
            store.save(changed, expected_revision=changed.revision)
            await daemon.reload_config()
            assert session.engine.profile.id == 'game' and not session.engine.macros.jobs
            assert [value for _, _, value in session.engine.ledger.output.events] == [1, 0]
            await start_turbo(session.engine)
        finally:
            await daemon.coordinator.detach(MODELS[0])
    asyncio.run(check())


def test_manual_pin_cannot_activate_draft_and_automatic_rechecks_its_roots(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = Configuration()
        config.profiles['draft'] = unfinished()
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        session = await attach(daemon, tmp_path)
        try:
            before = store.path.read_bytes()
            with pytest.raises(ProtocolError, match='Assign HyperShift'):
                await daemon.command({'command': 'pin', 'model': MODELS[0], 'profile': 'draft'})
            assert store.path.read_bytes() == before and session.engine.profile.id == 'default'
            assert not session.stop_requested.is_set() and not daemon.coordinator.config.pinned
            # Pin a working profile, then edit the unused automatic default.
            config = store.read()
            config.profiles['working'] = Profile('working', 'Working')
            store.save(config, expected_revision=config.revision)
            await daemon.command({'command': 'pin', 'model': MODELS[0], 'profile': 'working'})
            config = store.read()
            config.profiles['default'] = unfinished('default')
            store.save(config, expected_revision=config.revision)
            await daemon.reload_config()
            assert not daemon.config_error and session.engine.profile.id == 'working'
            before = store.path.read_bytes()
            with pytest.raises(ProtocolError, match='Unfinished default'):
                await daemon.command({'command': 'pin', 'model': MODELS[0], 'profile': 'automatic'})
            assert store.path.read_bytes() == before and session.engine.profile.id == 'working'
            assert store.read().pinned == {MODELS[0]: 'working'}
        finally:
            await daemon.coordinator.detach(MODELS[0])
    asyncio.run(check())


def test_profile_button_activates_valid_link_and_held_press_does_not_run_new_binding(tmp_path):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = Configuration()
        config.profiles['default'].common.normal['side_4'] = Action('profile', target='linked')
        config.profiles['linked'] = Profile('linked', 'Linked', Layers(normal={
            'side_4': Action('keys', keys=('KEY_2',))}))
        config.profiles['draft'] = unfinished()
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        await daemon.coordinator.focus_changed(Window('a', 'code'))
        session = await attach(daemon, tmp_path)
        completed = asyncio.Event()
        async def pin(model, identifier):
            await daemon.pin(model, identifier)
            completed.set()
        session.pin_profile = pin
        worker = asyncio.create_task(session.process_controls(None))
        try:
            session.validate_profiles(daemon.coordinator.config)
            await session.engine.press('side_4')
            await asyncio.wait_for(completed.wait(), 1)
            assert session.engine.profile.id == 'linked' and store.read().pinned == {MODELS[0]: 'linked'}
            assert 'side_4' in session.engine.disarmed
            await session.engine.press('side_4')
            assert not session.engine.ledger.output.events
            await session.engine.release('side_4')
            await session.engine.press('side_4')
            await session.engine.release('side_4')
            assert [value for _, _, value in session.engine.ledger.output.events] == [1, 0]
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await daemon.coordinator.detach(MODELS[0])
    asyncio.run(check())


@pytest.mark.parametrize('activation', ['rule', 'default', 'button', 'pin'])
def test_reload_rejects_newly_reachable_draft_before_engine_selection(tmp_path, activation):
    async def check():
        store = ProfileStore(tmp_path / 'profiles.json')
        config = Configuration()
        config.profiles['draft'] = unfinished()
        store.save(config, expected_revision=0)
        daemon = Daemon(store)
        session = await attach(daemon, tmp_path)
        before = deepcopy(daemon.coordinator.config.json())
        try:
            changed = store.read()
            if activation == 'rule':
                changed.rules = [Rule('draft', app_class='a future program')]
            elif activation == 'default':
                changed.defaults[MODELS[0]] = 'draft'
            elif activation == 'button':
                changed.profiles['default'].common.normal['side_4'] = Action('profile', target='draft')
            else:
                changed.pinned[MODELS[0]] = 'draft'
            store.save(changed, expected_revision=changed.revision)
            await daemon.reload_config()
            assert 'Unfinished draft' in daemon.config_error
            assert session.engine.profile.id == 'default'
            assert daemon.coordinator.config.json() == before
            assert session.stop_requested.is_set() and not daemon.requested
        finally:
            await daemon.coordinator.detach(MODELS[0])
    asyncio.run(check())
