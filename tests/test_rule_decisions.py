from copy import deepcopy

import pytest

from gillete.model import ConfigurationError, MODELS, Profile
from gillete.profiles import Configuration, ProfileStore, Rule, Window, literal_pattern


def configuration():
    config = Configuration()
    config.profiles.update({name: Profile(name, name.title()) for name in ('work', 'game', 'other')})
    config.defaults[MODELS[1]] = 'other'
    config.rules = [Rule('work', app_class='*', priority=10),
                    Rule('game', app_class='steam_app_123', title='Game*', priority=20, model=MODELS[0]),
                    Rule('other', app_class='steam_app_123', priority=20),
                    Rule('work', app_class='steam_app_123', priority=100, enabled=False)]
    return config


def test_explanation_matches_actual_service_selection_priorities_ties_and_per_mouse_rules():
    config = configuration()
    window = Window('0x1', 'steam_app_123', 'Game — character select', '/usr/bin/wine-preloader')
    v2, v3 = (config.decision(model, window) for model in MODELS)
    assert (v2.profile_id, v2.source, v2.rule_index) == ('game', 'rule', 1)
    assert (v3.profile_id, v3.source, v3.rule_index) == ('other', 'rule', 2)
    for model in MODELS:
        assert config.select(model, window) is config.profiles[config.decision(model, window).profile_id]
    # Equal priority keeps the first matching row, including after reordering.
    config.rules[1], config.rules[2] = config.rules[2], config.rules[1]
    assert config.decision(MODELS[0], window).profile_id == 'other'


def test_pinned_and_automatic_predictions_are_distinct_and_do_not_change_persistent_preferences(tmp_path):
    store = ProfileStore(tmp_path/'profiles.json')
    config = configuration()
    config.pinned[MODELS[0]] = 'work'
    store.save(config, expected_revision=0)
    before = store.path.read_bytes()
    config = store.read()
    window = Window('0x1', 'steam_app_123', 'Game')
    actual = config.decision(MODELS[0], window)
    automatic = config.decision(MODELS[0], window, automatic=True)
    assert (actual.profile_id, actual.source, actual.rule_index) == ('work', 'pinned', None)
    assert (automatic.profile_id, automatic.source, automatic.rule_index) == ('game', 'rule', 1)
    assert store.path.read_bytes() == before and config.pinned == {MODELS[0]:'work'}
    assert config.decision(MODELS[1], window).profile_id == 'other'


@pytest.mark.parametrize('focused',[True,False])
def test_default_and_no_window_selection_are_explained_without_a_matching_rule(focused):
    config = configuration()
    config.rules = [Rule('game', executable='/games/Wow.exe')]
    window = Window('preview' if focused else '', 'code', 'Work', '/usr/bin/code')
    for model in MODELS:
        decision = config.decision(model, window)
        assert decision.profile_id == config.defaults[model] and decision.source == 'default'
        assert decision.rule_index is None
    config.rules = [Rule('game', app_class='*')]
    assert config.decision(MODELS[0], Window()).source == 'default'


def test_literal_app_ids_titles_and_executable_conditions_use_the_existing_matcher():
    config = configuration()
    window = Window('preview', 'game[12]*', 'Game? [Work]', '/games/a[b]/Wow.exe')
    config.rules = [Rule('game', **{name: literal_pattern(getattr(window, name))
                                  for name in ('app_class', 'title', 'executable')})]
    before = deepcopy(config.json())
    assert config.decision(MODELS[0], window).profile_id == 'game'
    assert config.decision(MODELS[0], Window('preview','game1x',window.title,window.executable)).source == 'default'
    assert config.decision(MODELS[0], Window('preview',window.app_class,window.title,'/usr/bin/wine')).source == 'default'
    assert config.json() == before


def test_unknown_mouse_is_rejected_by_both_selection_entry_points():
    config = configuration()
    for method in (config.select, config.decision):
        with pytest.raises(ConfigurationError, match='Unknown model'):
            method('unknown', Window('preview'))
