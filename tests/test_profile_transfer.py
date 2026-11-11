from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gillete import profile_transfer as transfer
from gillete.model import Action, ConfigurationError, Layers, MODELS, Profile, sequence
from gillete.profiles import Configuration, ProfileStore, Rule, Window


def library():
    config = Configuration()
    config.profiles['work'] = Profile('work', 'Work', Layers(
        normal={'side_1': Action('profile', target='work'),
                'side_2': sequence(('KEY_LEFTCTRL', 'KEY_K'), ('KEY_M',), press_ms=17, gap_ms=133)},
        shifted={'side_3': Action('profile', target='game')}),
        overrides={MODELS[1]: Layers(normal={'ring_finger': Action('profile', target='work')},
                                    shifted={'side_4': Action('profile', target='work')})},
        standalone={MODELS[0]: Layers(normal={'side_2': Action('keys', keys=('KEY_F24',))})})
    config.profiles['game'] = Profile('game', 'Game', Layers(normal={'side_1': Action('profile', target='work')}))
    config.profiles['unused'] = Profile('unused', 'Unused')
    config.rules = [Rule('work', app_class='code', title='*project*', executable='/usr/bin/code', priority=5),
                    Rule('game', app_class='wow', model=MODELS[1], enabled=False),
                    Rule('unused', app_class='other')]
    config.pinned[MODELS[1]] = 'game'
    config.startup_models = [MODELS[0]]
    config.emergency_shortcut = 'Super+F8'
    return config


def test_duplicate_rebases_all_self_switches_without_changing_other_profiles_or_actions():
    config = library()
    before = deepcopy(config.json())
    copied, identifier, rules = transfer.duplicate(config, 'work')
    profile = copied.profiles[identifier]
    assert identifier not in config.profiles and profile.name == 'Work copy'
    assert profile.common.normal['side_1'].target == identifier
    assert profile.common.shifted['side_3'].target == 'game'
    assert profile.overrides[MODELS[1]].normal['ring_finger'].target == identifier
    assert profile.overrides[MODELS[1]].shifted['side_4'].target == identifier
    assert profile.common.normal['side_2'] == config.profiles['work'].common.normal['side_2']
    assert profile.standalone == config.profiles['work'].standalone
    assert rules == [replace(config.rules[0], profile=identifier, enabled=False)]
    assert copied.rules == config.rules + rules
    assert copied.defaults == config.defaults and copied.pinned == config.pinned
    assert copied.startup_models == config.startup_models
    assert copied.emergency_shortcut == config.emergency_shortcut
    profile.standalone[MODELS[0]].normal.clear()
    copied.profiles['game'].name = 'A later edit'
    assert config.json() == before


def test_repeated_duplicate_keeps_names_distinct_and_bounded():
    config = Configuration()
    config.profiles['default'].name = 'x' * 256
    config, first, _ = transfer.duplicate(config, 'default')
    config, second, _ = transfer.duplicate(config, 'default')
    assert len(config.profiles[first].name) == len(config.profiles[second].name) == 256
    assert config.profiles[first].name.endswith(' copy')
    assert config.profiles[second].name.endswith(' copy 2')


def test_export_keeps_transitive_cycles_all_layers_and_only_related_rules():
    config = library()
    config.profiles['game'].overrides[MODELS[0]] = Layers(shifted={'side_12': Action('profile', target='default')})
    document = transfer.export_document(config, 'work')
    assert set(document) == {'version', 'root', 'profiles', 'rules'}
    assert document['version'] == 2 and document['root'] == 'work'
    assert [p['id'] for p in document['profiles']] == ['work', 'default', 'game']
    assert [r['profile'] for r in document['rules']] == ['work', 'game']
    assert document['rules'][0]['enabled'] is True and document['rules'][1]['enabled'] is False
    bundle = transfer.parse_bundle(document)
    assert bundle.profiles['work'].json() == config.profiles['work'].json()
    assert bundle.rules == tuple(config.rules[:2])


def test_collision_import_rewrites_cross_links_and_keeps_existing_configuration():
    config = library()
    before = deepcopy(config.json())
    bundle = transfer.parse_bundle(transfer.export_document(config, 'work'))
    plan = transfer.plan_import(config, bundle)
    result = plan.configuration()
    imported_work = result.profiles[plan.root]
    imported_game = result.profiles[imported_work.common.shifted['side_3'].target]
    assert plan.root != 'work' and imported_game.id != 'game'
    assert imported_work.common.normal['side_1'].target == plan.root
    assert imported_game.common.normal['side_1'].target == plan.root
    assert imported_work.overrides[MODELS[1]].normal['ring_finger'].target == plan.root
    assert imported_work.name == 'Work imported' and imported_game.name == 'Game imported'
    assert result.rules[-2:] == [replace(config.rules[0], profile=plan.root, enabled=False),
                                 replace(config.rules[1], profile=imported_game.id)]
    assert result.defaults == config.defaults and result.pinned == config.pinned
    assert result.startup_models == config.startup_models and result.revision == config.revision
    assert result.emergency_shortcut == config.emergency_shortcut
    assert all(result.profiles[key].json() == value.json() for key, value in config.profiles.items())
    assert config.json() == before
    assert bundle.profiles['work'].common.normal['side_1'].target == 'work'
    result.profiles[plan.root].name = 'Edited import'
    assert plan.configuration().profiles[plan.root].name == 'Work imported'


def test_new_ids_cannot_collide_with_another_incoming_profile(monkeypatch):
    source = library()
    destination = Configuration()
    destination.profiles['work'] = Profile('work', 'Local Work')
    identifiers = iter(['game', 'work', 'default', 'new-work'])
    monkeypatch.setattr(transfer, 'uuid4', lambda: SimpleNamespace(hex=next(identifiers)))
    result = transfer.plan_import(destination, transfer.parse_bundle(transfer.export_document(source, 'work'))).configuration()
    assert result.profiles['new-work'].common.shifted['side_3'].target == 'game'
    assert result.profiles['game'].common.normal['side_1'].target == 'new-work'
    assert result.profiles['work'].name == 'Local Work'


def test_import_rule_activation_is_optional_and_preserves_source_disabled_state_and_ties():
    source = library()
    destination = Configuration()
    destination.rules = [Rule('default', app_class='code', priority=5)]
    plan = transfer.plan_import(destination, transfer.parse_bundle(transfer.export_document(source, 'work')))
    window = Window('a', 'code', 'my project', '/usr/bin/code')
    disabled = plan.configuration()
    assert len(disabled.rules) == 3 and not any(r.enabled for r in disabled.rules[1:])
    assert disabled.select(MODELS[0], window).id == 'default'
    enabled = plan.configuration(activate_rules=True)
    assert enabled.rules[1].enabled and not enabled.rules[2].enabled
    assert enabled.select(MODELS[0], window).id == 'default'  # Existing equal-priority rule wins.
    enabled.rules.pop(0)
    assert enabled.select(MODELS[0], window).id == 'work'
    assert enabled.select(MODELS[1], Window('b', 'wow')).id == 'default'


def test_disabled_rule_roundtrip_legacy_default_and_model_pin_behavior(tmp_path):
    config = library()
    config.rules[0] = replace(config.rules[0], enabled=False)
    store = ProfileStore(tmp_path / 'profiles.json')
    store.save(config, expected_revision=0)
    reloaded = store.read()
    window = Window('a', 'code', 'my project', '/usr/bin/code')
    assert reloaded.select(MODELS[0], window).id == 'default'
    assert reloaded.select(MODELS[1], window).id == 'game'  # Pin remains effective.
    data = reloaded.json()
    del data['rules'][0]['enabled']
    legacy = Configuration.parse(data)
    assert legacy.rules[0].enabled and legacy.select(MODELS[0], window).id == 'work'
    assert not legacy.rules[1].enabled


@pytest.mark.parametrize('value', [0, 1, 'false', None, []])
def test_rule_enabled_is_strictly_boolean(value):
    with pytest.raises(ConfigurationError, match='enabled'):
        Rule('default', app_class='code', enabled=value)


def test_legacy_self_reference_rebases_and_external_local_link_is_reviewed():
    config = library()
    bundle = transfer.parse_bundle({'version': 1, 'profile': config.profiles['work'].json()})
    plan = transfer.plan_import(config, bundle)
    assert plan.existing_links == ('Game',) and not plan.rules
    profile = plan.configuration().profiles[plan.root]
    assert profile.common.normal['side_1'].target == plan.root
    assert profile.common.shifted['side_3'].target == 'game'
    with pytest.raises(ConfigurationError, match='linked profiles'):
        transfer.plan_import(Configuration(), bundle)


@pytest.mark.parametrize('change', [
    lambda d: d.update(version=True),
    lambda d: d.update(version=3),
    lambda d: d.update(defaults={}),
    lambda d: d.update(root='missing'),
    lambda d: d.update(profiles=[]),
    lambda d: d['profiles'].append(d['profiles'][0]),
    lambda d: d['profiles'].pop(),  # A v2 graph cannot borrow a local profile.
    lambda d: d['rules'].append({'profile': 'absent', 'app_class': 'test'}),
    lambda d: d['rules'].append({'app_class': 'test'}),
    lambda d: d['rules'][0].update(enabled='false'),
    lambda d: d['rules'][0].update(unrecognized=True),
])
def test_malformed_bundle_is_rejected(change):
    document = transfer.export_document(library(), 'work')
    change(document)
    with pytest.raises(ConfigurationError):
        transfer.parse_bundle(document)


def test_import_rejects_total_rule_limit_before_saving_or_changing_source():
    destination = Configuration(rules=[Rule('default', app_class='existing')] * 999)
    before = deepcopy(destination.json())
    with pytest.raises(ConfigurationError, match='count'):
        transfer.plan_import(destination, transfer.parse_bundle(transfer.export_document(library(), 'work')))
    assert destination.json() == before


def test_bundle_and_import_profile_limits():
    profiles = [Profile(str(i), str(i)).json() for i in range(1001)]
    with pytest.raises(ConfigurationError, match='count'):
        transfer.parse_bundle({'version': 2, 'root': '0', 'profiles': profiles})
    bundle = transfer.parse_bundle({'version': 2, 'root': '0', 'profiles': profiles[:1000]})
    with pytest.raises(ConfigurationError, match='profile limit'):
        transfer.plan_import(Configuration(), bundle)


def test_atomic_export_size_limit_private_permissions_and_interrupted_replacement(tmp_path, monkeypatch):
    path = tmp_path / 'backup' / 'work.json'
    document = transfer.export_document(library(), 'work')
    transfer.write_export(path, document)
    before = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert transfer.read_bundle(path).root == 'work'
    monkeypatch.setattr(ProfileStore, 'MAX_BYTES', 50)
    with pytest.raises(ConfigurationError, match='size limit'):
        transfer.write_export(path, document)
    with pytest.raises(ConfigurationError, match='too large'):
        transfer.read_bundle(path)
    assert path.read_bytes() == before
    monkeypatch.undo()
    from gillete import onboard
    def fail_replace(*args):
        raise OSError('Simulated disk error')
    monkeypatch.setattr(onboard.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='disk'):
        transfer.write_export(path, {'version': 2})
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_excessively_nested_file_reports_a_configuration_error(tmp_path):
    path = tmp_path / 'nested.json'
    path.write_text('[' * 10000 + ']' * 10000)
    with pytest.raises(ConfigurationError):
        transfer.read_bundle(path)
