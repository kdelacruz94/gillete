import asyncio

from gillete.engine import Engine
from gillete.examples import example_profiles
from gillete.focus import ProfileCoordinator
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import MODELS
from gillete.profiles import Configuration, Rule, Window


def test_pinned_turbo_stops_on_focus_loss_even_when_profile_stays_pinned():
    async def check():
        config = Configuration()
        wow = example_profiles()[3]
        config.profiles[wow.id] = wow
        config.pinned[MODELS[0]] = wow.id
        coordinator = ProfileCoordinator(config)
        output = RecordingOutput()
        engine = Engine(MODELS[0], wow, KeyLedger(output))
        await coordinator.attach("v2", engine)
        await coordinator.focus_changed(Window("0x1", "wow"))
        await engine.press("side_1")
        await engine.release("side_1")
        await asyncio.sleep(0.01)
        assert engine.macros.jobs
        await coordinator.focus_changed(Window("0x2", "code"))
        count = len(output.events)
        await asyncio.sleep(0.12)
        assert len(output.events) == count and not engine.macros.jobs
        assert engine.profile.id == wow.id
    asyncio.run(check())


def test_devices_select_independently_and_disconnect_cancels():
    async def check():
        config = Configuration()
        config.profiles.update({p.id: p for p in example_profiles()})
        config.rules = [Rule("vscode-example", app_class="code")]
        config.pinned[MODELS[1]] = "herdr-example"
        coordinator = ProfileCoordinator(config)
        engines = [Engine(m, config.profiles["default"], KeyLedger(RecordingOutput())) for m in MODELS]
        for model, engine in zip(MODELS, engines):
            await coordinator.attach(model, engine)
        await coordinator.focus_changed(Window("0x1", "code"))
        assert [e.profile.id for e in engines] == ["vscode-example", "herdr-example"]
        await engines[0].press("side_1")
        await asyncio.sleep(0.01)
        await coordinator.unavailable()
        assert not engines[0].macros.jobs and not engines[0].ledger.holders
        assert engines[0].profile.id == "default"
        assert engines[1].profile.id == "herdr-example"
    asyncio.run(check())
