import asyncio
import json
from pathlib import Path

import pytest

from gillete import focus
from gillete.engine import Engine
from gillete.examples import example_profiles
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import MODELS
from gillete.model import Layers, Profile
from gillete.profiles import Configuration, Rule, Window


class Writer:
    def close(self): pass
    async def wait_closed(self): pass


class EventReader(asyncio.StreamReader):
    def __init__(self):
        super().__init__()
        self.consumed = asyncio.Queue()

    async def readline(self):
        line = await super().readline()
        self.consumed.put_nowait(line)
        return line

    async def consumed_events(self, count=1):
        for _ in range(count):
            await asyncio.wait_for(self.consumed.get(), 1)


@pytest.mark.parametrize('events', [1, 100])
def test_newer_focus_events_discard_inflight_results_and_coalesce_queries(monkeypatch, events):
    async def check():
        coordinator = focus.ProfileCoordinator(Configuration())
        reader = EventReader()
        watcher = focus.HyprlandWatcher(coordinator, signature='test')
        initial, second, third, finish_second, finish_third, settled = [asyncio.Event() for _ in range(6)]
        published = []
        original = coordinator.focus_changed
        async def publish(window, **kwargs):
            accepted = await original(window, **kwargs)
            if accepted:
                published.append(window.address)
                if window.address == '0x3': settled.set()
            return accepted
        monkeypatch.setattr(coordinator, 'focus_changed', publish)
        calls = 0
        async def query(_signature):
            nonlocal calls
            calls += 1
            if calls == 1:
                initial.set()
                return Window('0x1', 'first')
            if calls == 2:
                second.set()
                await finish_second.wait()
                return Window('0x2', 'stale')
            assert calls == 3, 'Refresh work should be coalesced, not queued per event'
            third.set()
            await finish_third.wait()
            return Window('0x3', 'latest')
        monkeypatch.setattr(focus, 'query_window', query)
        task = asyncio.create_task(watcher.monitor(reader))
        try:
            await asyncio.wait_for(initial.wait(), 1)
            reader.feed_data(b'activewindowv2>>2\n')
            await reader.consumed_events()
            await asyncio.wait_for(second.wait(), 1)
            reader.feed_data(b'activewindowv2>>3\n' * events)
            await reader.consumed_events(events)
            assert coordinator.focus_pending
            finish_second.set()
            await asyncio.wait_for(third.wait(), 1)
            assert published == ['0x1'] and coordinator.window.address == '0x1'
            assert coordinator.focus_pending
            finish_third.set()
            await asyncio.wait_for(settled.wait(), 1)
            assert published == ['0x1', '0x3'] and not coordinator.focus_pending
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(check())


def test_title_refresh_does_not_cancel_turbo_when_profile_and_focus_stay_the_same(monkeypatch):
    async def check():
        config = Configuration()
        wow = example_profiles()[3]
        config.profiles[wow.id] = wow
        config.pinned[MODELS[0]] = wow.id
        coordinator = focus.ProfileCoordinator(config)
        engine = Engine(MODELS[0], wow, KeyLedger(RecordingOutput()))
        await coordinator.attach('v2', engine)
        await coordinator.focus_changed(Window('0x1', 'wow', 'First title'))
        await engine.press('side_1')
        await engine.release('side_1')
        reader = EventReader()
        watcher = focus.HyprlandWatcher(coordinator, signature='test')
        calls = 0
        initial, title, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def query(_signature):
            nonlocal calls
            calls += 1
            if calls == 1:
                initial.set()
                return coordinator.window
            title.set()
            await finish.wait()
            return Window('0x1', 'wow', 'Updated title')
        monkeypatch.setattr(focus, 'query_window', query)
        task = asyncio.create_task(watcher.monitor(reader))
        try:
            await asyncio.wait_for(initial.wait(), 1)
            generation = engine.generation
            reader.feed_data(b'windowtitlev2>>1,Updated title\n')
            await asyncio.wait_for(title.wait(), 1)
            assert engine.macros.jobs and not coordinator.focus_pending
            finish.set()
            for _ in range(20):
                if coordinator.window.title == 'Updated title': break
                await asyncio.sleep(0)
            assert coordinator.window.title == 'Updated title'
            assert engine.macros.jobs and engine.generation == generation
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await coordinator.unavailable()
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['disconnect', 'query'])
def test_monitor_failure_cancels_its_sibling_and_marks_focus_unavailable(monkeypatch, failure):
    async def check():
        coordinator = focus.ProfileCoordinator(Configuration())
        await coordinator.focus_changed(Window('0x1', 'old'))
        reader = asyncio.StreamReader()
        started, finish, query_cancelled, unavailable = [asyncio.Event() for _ in range(4)]
        async def query(_signature):
            started.set()
            try:
                await finish.wait()
                raise ValueError('Invalid active-window response')
            except asyncio.CancelledError:
                query_cancelled.set()
                raise
        async def connect(*args, **kwargs): return reader, Writer()
        original = coordinator.unavailable
        async def lost():
            await original()
            unavailable.set()
        monkeypatch.setattr(focus, 'query_window', query)
        monkeypatch.setattr(focus.asyncio, 'open_unix_connection', connect)
        monkeypatch.setattr(coordinator, 'unavailable', lost)
        watcher = focus.HyprlandWatcher(coordinator, signature='test')
        monkeypatch.setattr(watcher, 'socket_path', lambda: Path('/unused'))
        task = asyncio.create_task(watcher.run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            if failure == 'disconnect': reader.feed_eof()
            else: finish.set()
            await asyncio.wait_for(unavailable.wait(), 1)
            assert not coordinator.available and coordinator.focus_pending
            assert not coordinator.window.address and watcher.last_error
            assert query_cancelled.is_set() == (failure == 'disconnect')
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(check())


def test_result_invalidated_while_waiting_for_coordinator_lock_is_never_published():
    async def check():
        coordinator = focus.ProfileCoordinator(Configuration())
        await coordinator.focus_changed(Window('0x1', 'old'))
        revision = coordinator.focus_revision
        await coordinator.lock.acquire()
        publication = asyncio.create_task(coordinator.focus_changed(Window('0x2', 'stale'), revision=revision))
        invalidation = asyncio.create_task(coordinator.focus_event(moved=True))
        try:
            await asyncio.sleep(0)
            assert coordinator.focus_pending and coordinator.focus_revision != revision
        finally:
            coordinator.lock.release()
        assert await publication is False
        await invalidation
        assert coordinator.window.address == '0x1' and coordinator.focus_pending
        assert await coordinator.focus_changed(Window('0x3', 'current'), revision=coordinator.focus_revision)
        assert not coordinator.focus_pending
    asyncio.run(check())


def test_new_event_during_engine_release_keeps_focus_pending_and_discards_publication(monkeypatch):
    async def check():
        coordinator = focus.ProfileCoordinator(Configuration())
        engine = Engine(MODELS[0], coordinator.config.profiles['default'], KeyLedger(RecordingOutput()))
        await coordinator.attach('mouse', engine)
        await coordinator.focus_changed(Window('0x1', 'old'))
        await coordinator.focus_event(moved=True)
        releasing, finish = asyncio.Event(), asyncio.Event()
        original = engine.cancel
        async def cancel(**kwargs):
            releasing.set()
            await finish.wait()
            await original(**kwargs)
        monkeypatch.setattr(engine, 'cancel', cancel)
        publication = asyncio.create_task(coordinator.focus_changed(Window('0x2', 'stale'), revision=coordinator.focus_revision))
        await asyncio.wait_for(releasing.wait(), 1)
        invalidation = asyncio.create_task(coordinator.focus_event(moved=True))
        await asyncio.sleep(0)
        finish.set()
        assert await publication is False
        await invalidation
        assert coordinator.focus_pending and coordinator.window.address == '0x1'
        assert await coordinator.focus_changed(Window('0x3', 'latest'), revision=coordinator.focus_revision)
        assert not coordinator.focus_pending
        await coordinator.detach('mouse')
    asyncio.run(check())


@pytest.mark.parametrize('data', [None, [], 'window', {'address': None}, {'class': 42}, {'title': []}])
def test_invalid_active_window_response_fails_instead_of_creating_a_string_identity(monkeypatch, data):
    class Process:
        returncode = 0
        async def communicate(self): return json.dumps(data).encode(), b''
    async def launch(*args, **kwargs): return Process()
    monkeypatch.setattr(focus.asyncio, 'create_subprocess_exec', launch)
    with pytest.raises(ValueError, match='active-window response'):
        asyncio.run(focus.query_window('test'))


def test_cancelling_a_query_kills_and_reaps_its_subprocess(monkeypatch):
    async def check():
        started = asyncio.Event()
        class Process:
            returncode = None
            killed = reaped = False
            async def communicate(self):
                started.set()
                await asyncio.Event().wait()
            def kill(self): self.killed = True
            async def wait(self): self.reaped = True
        process = Process()
        async def launch(*args, **kwargs): return process
        monkeypatch.setattr(focus.asyncio, 'create_subprocess_exec', launch)
        task = asyncio.create_task(focus.query_window('test'))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert process.killed and process.reaped
    asyncio.run(check())


def test_new_title_event_during_profile_change_blocks_input_until_current_result(monkeypatch):
    async def check():
        config = Configuration()
        config.profiles['next'] = Profile('next', 'Next', Layers())
        config.rules = [Rule('next', title='New title')]
        coordinator = focus.ProfileCoordinator(config)
        engine = Engine(MODELS[0], config.profiles['default'], KeyLedger(RecordingOutput()))
        await coordinator.attach('mouse', engine)
        await coordinator.focus_changed(Window('0x1', 'app', 'Old title'))
        releasing, finish = asyncio.Event(), asyncio.Event()
        original = engine.cancel
        async def cancel(**kwargs):
            releasing.set()
            await finish.wait()
            await original(**kwargs)
        monkeypatch.setattr(engine, 'cancel', cancel)
        publication = asyncio.create_task(coordinator.focus_changed(
            Window('0x1', 'app', 'New title'), revision=coordinator.focus_revision))
        await asyncio.wait_for(releasing.wait(), 1)
        assert coordinator.focus_pending
        invalidation = asyncio.create_task(coordinator.focus_event(moved=False))
        await asyncio.sleep(0)
        finish.set()
        assert await publication is False
        await invalidation
        assert coordinator.focus_pending and coordinator.window.title == 'Old title'
        assert await coordinator.focus_changed(Window('0x1', 'app', 'Latest title'), revision=coordinator.focus_revision)
        assert engine.profile.id == 'default' and not coordinator.focus_pending
        await coordinator.detach('mouse')
    asyncio.run(check())


def test_reset_error_while_closing_old_socket_does_not_prevent_reconnection(monkeypatch):
    async def check():
        coordinator = focus.ProfileCoordinator(Configuration())
        watcher = focus.HyprlandWatcher(coordinator, signature='test')
        monkeypatch.setattr(watcher, 'socket_path', lambda: Path('/unused'))
        connected = 0
        settled = asyncio.Event()
        class ResetWriter(Writer):
            async def wait_closed(self): raise ConnectionResetError('Old compositor socket reset')
        async def connect(*args, **kwargs):
            nonlocal connected
            connected += 1
            assert connected <= 2
            reader = asyncio.StreamReader()
            if connected == 1:
                reader.feed_eof()
                return reader, ResetWriter()
            return reader, Writer()
        async def query(_signature):
            if connected == 2:
                settled.set()
            return Window(f'0x{connected}', 'app')
        original_sleep = asyncio.sleep
        async def sleep(delay):
            if delay != 1:
                await original_sleep(delay)
        monkeypatch.setattr(focus.asyncio, 'open_unix_connection', connect)
        monkeypatch.setattr(focus.asyncio, 'sleep', sleep)
        monkeypatch.setattr(focus, 'query_window', query)
        task = asyncio.create_task(watcher.run())
        try:
            await asyncio.wait_for(settled.wait(), 1)
            assert connected == 2 and coordinator.available and not coordinator.focus_pending
            assert coordinator.window.address == '0x2' and not watcher.last_error
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(check())


def test_focus_event_cancels_turbo_before_a_delayed_window_query_returns(monkeypatch):
    async def check():
        config = Configuration()
        wow = example_profiles()[3]
        config.profiles[wow.id] = wow
        config.pinned[MODELS[0]] = wow.id
        coordinator = focus.ProfileCoordinator(config)
        output = RecordingOutput()
        engine = Engine(MODELS[0], wow, KeyLedger(output))
        await coordinator.attach('v2', engine)
        reader = asyncio.StreamReader()
        queried, finish_query, initial = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0
        async def query(_signature):
            nonlocal calls
            calls += 1
            if calls == 1:
                initial.set()
                return Window('0x1', 'wow')
            queried.set()
            await finish_query.wait()
            return Window('0x2', 'code')
        async def connect(*args, **kwargs): return reader, Writer()
        monkeypatch.setattr(focus, 'query_window', query)
        monkeypatch.setattr(focus.asyncio, 'open_unix_connection', connect)
        watcher = focus.HyprlandWatcher(coordinator, signature='test')
        monkeypatch.setattr(watcher, 'socket_path', lambda: Path('/unused'))
        task = asyncio.create_task(watcher.run())
        try:
            await asyncio.wait_for(initial.wait(), 1)
            await engine.press('side_1')
            await engine.release('side_1')
            await asyncio.sleep(0)
            assert engine.macros.jobs and engine.ledger.holders
            reader.feed_data(b'activewindowv2>>2\n')
            await asyncio.wait_for(queried.wait(), 1)
            assert not engine.macros.jobs, 'Focus loss must cancel before the query returns'
            assert not engine.ledger.holders
        finally:
            finish_query.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(check())
