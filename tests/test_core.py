import asyncio
from dataclasses import replace

from evdev import ecodes as E
import pytest

from gillete.engine import Engine
from gillete.examples import example_profiles
from gillete.macros import KeyLedger, MacroRunner, RecordingOutput
from gillete.model import Action, ConfigurationError, Layers, MODELS, Profile, Step, sequence
from gillete.profiles import Configuration, ConflictError, ProfileStore, Rule, Window
from gillete.recorder import Recorder


def run(coro):
    return asyncio.run(coro)


async def settle(runner):
    if runner.jobs:
        await asyncio.wait_for(asyncio.gather(*list(runner.jobs.values())), timeout=1)


@pytest.mark.parametrize("index,expected", [
    (0, [(E.KEY_LEFTALT, 1), (E.KEY_H, 1), (E.KEY_H, 0), (E.KEY_LEFTALT, 0),
         (E.KEY_O, 1), (E.KEY_O, 0), (E.KEY_A, 1), (E.KEY_A, 0)]),
    (1, [(E.KEY_LEFTCTRL, 1), (E.KEY_K, 1), (E.KEY_K, 0), (E.KEY_LEFTCTRL, 0),
         (E.KEY_M, 1), (E.KEY_M, 0)]),
    (2, [(E.KEY_LEFTCTRL, 1), (E.KEY_B, 1), (E.KEY_B, 0), (E.KEY_LEFTCTRL, 0),
         (E.KEY_LEFTALT, 1), (E.KEY_S, 1), (E.KEY_S, 0), (E.KEY_LEFTALT, 0)]),
])
def test_user_sequences_release_modifiers_between_chords(index, expected):
    async def check():
        output = RecordingOutput()
        runner = MacroRunner(KeyLedger(output))
        action = example_profiles()[index].common.normal["side_1"]
        await runner.start("test", action)
        await settle(runner)
        assert [(c, v) for _, c, v in output.events] == expected
        assert not runner.ledger.owners
    run(check())


def test_cancel_during_long_delay_releases_chord_without_executing_tail():
    async def check():
        output = RecordingOutput()
        runner = MacroRunner(KeyLedger(output))
        action = Action("macro", steps=(Step("down", key="KEY_LEFTCTRL"),
                        Step("wait", milliseconds=60000), Step("up", key="KEY_LEFTCTRL"),
                        Step("down", key="KEY_A"), Step("up", key="KEY_A")))
        await runner.start("job", action)
        await asyncio.sleep(0.01)
        await asyncio.wait_for(runner.cancel_all(), 0.1)
        assert output.events == [("key", E.KEY_LEFTCTRL, 1), ("key", E.KEY_LEFTCTRL, 0)]
        assert not runner.jobs and not runner.ledger.owners
    run(check())


def test_cancel_one_macro_does_not_release_another_actions_modifier():
    async def check():
        output = RecordingOutput()
        ledger = KeyLedger(output)
        ledger.down("held", E.KEY_LEFTCTRL)
        runner = MacroRunner(ledger)
        await runner.start("macro", sequence(("KEY_LEFTCTRL", "KEY_K"), press_ms=500))
        await asyncio.sleep(0.01)
        await runner.cancel("macro")
        assert ("key", E.KEY_LEFTCTRL, 0) not in output.events
        assert ("key", E.KEY_K, 0) in output.events
        ledger.release("held")
        assert output.events[-1] == ("key", E.KEY_LEFTCTRL, 0)
    run(check())


def test_wow_toggle_runs_after_release_and_second_press_stops():
    async def check():
        output = RecordingOutput()
        engine = Engine(MODELS[0], example_profiles()[3], KeyLedger(output))
        await engine.press("side_1")
        await engine.release("side_1")
        await asyncio.sleep(0.24)
        assert sum(v == 1 for _, _, v in output.events) >= 2
        await engine.press("side_1")
        count = len(output.events)
        await asyncio.sleep(0.15)
        assert len(output.events) == count
        assert not engine.macros.jobs and not engine.ledger.holders
    run(check())


def test_cancel_disarms_held_turbo_until_release_and_fresh_press():
    async def check():
        output = RecordingOutput()
        profile = example_profiles()[3]
        profile.common.normal["side_1"] = replace(profile.common.normal["side_1"], playback="held")
        engine = Engine(MODELS[0], profile, KeyLedger(output))
        await engine.press("side_1")
        await asyncio.sleep(0.01)
        await engine.cancel()
        count = len(output.events)
        await engine.press("side_1")
        await asyncio.sleep(0.01)
        assert len(output.events) == count
        await engine.release("side_1")
        await engine.press("side_1")
        await asyncio.sleep(0.01)
        assert len(output.events) > count
        await engine.disconnect()
        assert not engine.ledger.holders
    run(check())


def test_hypershift_preserves_pressed_mapping_through_shift_release():
    async def check():
        output = RecordingOutput()
        p = Profile("p", "Test", Layers(
            {"dpi_up": Action("hypershift", playback="held"), "side_1": Action("keys", keys=("KEY_1",))},
            {"side_1": Action("keys", keys=("KEY_LEFTCTRL", "KEY_K"))}))
        engine = Engine(MODELS[0], p, KeyLedger(output))
        await engine.press("dpi_up")
        await engine.press("side_1")
        await engine.release("dpi_up")
        assert not engine.shifted
        await engine.release("side_1")
        assert output.events == [("key", E.KEY_LEFTCTRL, 1), ("key", E.KEY_K, 1),
                                 ("key", E.KEY_K, 0), ("key", E.KEY_LEFTCTRL, 0)]
    run(check())


def test_device_overrides_do_not_relocate_ring_finger():
    profile = example_profiles()[0]
    assert profile.resolve(MODELS[1], "ring_finger").kind == "hypershift"
    assert profile.resolve(MODELS[0], "dpi_up").kind == "hypershift"
    with pytest.raises(ConfigurationError):
        profile.resolve(MODELS[0], "ring_finger")
    assert profile.resolve(MODELS[0], "side_1", shifted=True) == profile.common.normal["side_1"]


def test_profile_switch_cancels_toggle_and_releases_outputs():
    async def check():
        output = RecordingOutput()
        engine = Engine(MODELS[0], example_profiles()[3], KeyLedger(output))
        await engine.press("side_1")
        await engine.release("side_1")
        await asyncio.sleep(0.01)
        await engine.change_profile(Profile("new", "New"))
        count = len(output.events)
        await asyncio.sleep(0.12)
        assert len(output.events) == count and not engine.ledger.holders
    run(check())


def test_finite_repeat_and_held_cancel_before_first_scheduled_step():
    async def check():
        output = RecordingOutput()
        runner = MacroRunner(KeyLedger(output))
        action = replace(sequence(("KEY_A",), press_ms=1), playback="count", count=3, interval_ms=1)
        await runner.start("finite", action)
        await settle(runner)
        assert output.events == [("key", E.KEY_A, v) for _ in range(3) for v in (1, 0)]
        before = list(output.events)
        await runner.start("never", action)
        await runner.cancel("never")
        assert output.events == before and not runner.ledger.owners
    run(check())


def test_profile_rules_pins_and_default_roundtrip(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    config = store.read()
    config.profiles.update({p.id: p for p in example_profiles()})
    config.rules = [Rule("vscode-example", app_class="code"),
                    Rule("herdr-example", app_class="code", title="*Herdr*", priority=10)]
    assert config.select(MODELS[0], Window("0x1", "code", "Herdr project")).id == "herdr-example"
    assert config.select(MODELS[0], Window("0x2", "unknown")).id == "default"
    config.pinned[MODELS[0]] = "excel-example"
    store.save(config, expected_revision=0)
    reloaded = store.read()
    assert reloaded.select(MODELS[0], Window("0x1", "code")).id == "excel-example"
    assert reloaded.select(MODELS[1], Window("0x1", "code")).id == "vscode-example"
    assert store.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ConflictError):
        store.save(config, expected_revision=0)


def test_corrupt_configuration_is_not_replaced_with_defaults(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    store.path.write_text('{"profiles": invalid}')
    with pytest.raises(ConfigurationError):
        store.read()
    with pytest.raises(ConfigurationError):
        store.save(Configuration(), expected_revision=0)
    assert store.path.read_text() == '{"profiles": invalid}'


def test_import_validates_macro_balance_profile_references_and_unknown_versions():
    with pytest.raises(ConfigurationError):
        Action("macro", steps=(Step("down", key="KEY_A"),))
    with pytest.raises(ConfigurationError):
        Action("macro", steps=(Step("up", key="KEY_A"),))
    config = Configuration().json()
    config["version"] = 2
    with pytest.raises(ConfigurationError):
        Configuration.parse(config)
    config["version"] = 1
    config["pinned"][MODELS[0]] = "missing"
    with pytest.raises(ConfigurationError):
        Configuration.parse(config)


def test_recorder_timing_and_ignore_preexisting_keys_and_pointer_motion():
    recorder = Recorder()
    recorder.feed(E.EV_KEY, E.KEY_LEFTCTRL, 0, 0)  # Already held before recording.
    recorder.feed(E.EV_KEY, E.KEY_LEFTALT, 1, 1)
    recorder.feed(E.EV_REL, E.REL_X, 20, 1.01)
    recorder.feed(E.EV_KEY, E.KEY_H, 1, 1.05)
    recorder.feed(E.EV_KEY, E.KEY_H, 2, 1.06)  # OS repeat does not duplicate downs.
    recorder.feed(E.EV_KEY, E.KEY_H, 0, 1.10)
    action = recorder.finish()  # Auto-balance Ctrl/etc when stopping during a hold.
    assert [s.key for s in action.steps if s.kind == "down"] == ["KEY_LEFTALT", "KEY_H"]
    assert [s.milliseconds for s in action.steps if s.kind == "wait"] == [50, 50]
    assert action.steps[-1] == Step("up", key="KEY_LEFTALT")
    assert all(s.kind != "relative" for s in action.steps)


def test_launch_uses_argument_vector_not_shell_or_window_strings():
    async def check():
        seen = []
        async def launch(action):
            seen.append(action.argv)
        action = Action("launch", argv=("/usr/bin/echo", "$(touch /tmp/never-execute)"))
        engine = Engine(MODELS[0], Profile("p", "P", Layers({"side_1": action})),
                        KeyLedger(RecordingOutput()), launch=launch)
        await engine.press("side_1")
        assert seen == [action.argv]
    run(check())
