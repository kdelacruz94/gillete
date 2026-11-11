"""Hyprland focus integration and per-mouse profile/cancellation coordination."""

import asyncio
import json
import os
from pathlib import Path

from .engine import Engine
from .profiles import Configuration, Window


class ProfileCoordinator:
    def __init__(self, config: Configuration):
        config.validate()
        self.config = config
        self.window = Window()
        self.engines: dict[str, Engine] = {}
        self.available = False
        self.focus_pending = False
        self.focus_revision = 0
        self.lock = asyncio.Lock()

    async def attach(self, identity: str, engine: Engine):
        async with self.lock:
            if identity in self.engines:
                raise ValueError("A mouse with this identity is already attached")
            await engine.change_profile(self.config.select(engine.model, self.window))
            self.engines[identity] = engine

    async def detach(self, identity: str):
        async with self.lock:
            engine = self.engines.pop(identity, None)
            if engine:
                await engine.disconnect()

    async def focus_event(self, *, moved):
        # Invalidate an outstanding query before waiting for an input/config
        # handler's lock. New button commands are blocked immediately; the
        # event reader keeps consuming changes while hyprctl is outstanding.
        self.focus_revision += 1
        if moved:
            self.focus_pending = True
        async with self.lock:
            if moved:
                for engine in self.engines.values():
                    await engine.cancel()

    async def focus_changed(self, window: Window, *, revision=None):
        async with self.lock:
            if revision is not None and revision != self.focus_revision:
                return False
            moved = self.window.address != window.address or self.window.app_class != window.app_class
            boundary = moved or self.focus_pending
            if boundary:
                self.focus_pending = True
            for engine in self.engines.values():
                desired = self.config.select(engine.model, window)
                if desired.json() != engine.profile.json():
                    self.focus_pending = True
                    await engine.change_profile(desired)
                elif boundary:
                    # A pin controls selection, not permission to keep a game
                    # turbo running after the user leaves its window.
                    await engine.cancel()
            # Cancellation yields. A newer event may have invalidated this
            # result while another engine was releasing its outputs.
            if revision is not None and revision != self.focus_revision:
                return False
            self.window = window
            self.available = True
            self.focus_pending = False
            return True

    async def unavailable(self):
        self.focus_revision += 1
        self.available = False
        self.focus_pending = True
        async with self.lock:
            self.window = Window()
            for engine in self.engines.values():
                await engine.change_profile(self.config.select(engine.model, self.window))

    async def reload(self, config: Configuration):
        config.validate()
        async with self.lock:
            self.config = config
            for engine in self.engines.values():
                desired = config.select(engine.model, self.window)
                if desired.json() != engine.profile.json():
                    await engine.change_profile(desired)


async def query_window(signature: str) -> Window:
    process = await asyncio.create_subprocess_exec("hyprctl", "-i", signature, "-j", "activewindow",
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=2)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode or len(output) > 1024 * 1024:
        raise RuntimeError("Hyprland focus query failed")
    data = json.loads(output)
    if not isinstance(data, dict) or any(not isinstance(data.get(name, ''), str) for name in ('address', 'class', 'title')):
        raise ValueError('Invalid Hyprland active-window response')
    executable = ""
    pid = data.get("pid")
    if type(pid) is int and pid > 0:
        try:
            executable = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            pass
    return Window(str(data.get("address", "")), str(data.get("class", "")),
                  str(data.get("title", "")), executable)


async def query_windows() -> list[Window]:
    watcher = HyprlandWatcher(None)
    watcher.socket_path()  # Require an unambiguous current desktop session.
    process = await asyncio.create_subprocess_exec('hyprctl', '-i', watcher.signature, '-j', 'clients',
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=3)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode or len(output) > 1024 * 1024:
        raise RuntimeError('Could not list running applications in Hyprland')
    clients = json.loads(output)
    if not isinstance(clients, list) or len(clients) > 4096:
        raise RuntimeError('Invalid application list from Hyprland')
    windows = []
    for client in clients:
        executable = ''
        pid = client.get('pid')
        if type(pid) is int and pid > 0:
            try:
                executable = os.readlink(f'/proc/{pid}/exe')
            except OSError:
                pass
        if client.get('class') or executable:
            windows.append(Window(str(client.get('address', '')), str(client.get('class', '')),
                                  str(client.get('title', '')), executable))
    return windows


class HyprlandWatcher:
    def __init__(self, coordinator: ProfileCoordinator, runtime: Path | None = None, signature: str | None = None):
        self.coordinator = coordinator
        self.runtime = runtime or Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
        self.signature = signature if signature is not None else os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        self.last_error = ""

    def socket_path(self):
        if self.signature and "/" not in self.signature and self.signature not in {".", ".."}:
            path = self.runtime / "hypr" / self.signature / ".socket2.sock"
            if path.exists():
                return path
        candidates = list((self.runtime / "hypr").glob("*/.socket2.sock"))
        if len(candidates) != 1:
            raise RuntimeError("No unambiguous Hyprland event socket")
        self.signature = candidates[0].parent.name
        return candidates[0]

    async def run(self):
        try:
            while True:
                writer = None
                try:
                    reader, writer = await asyncio.open_unix_connection(str(self.socket_path()), limit=131072)
                    await self.monitor(reader)
                except (OSError, ValueError, RuntimeError, asyncio.TimeoutError) as error:
                    self.last_error = str(error)
                    await self.coordinator.unavailable()
                    await asyncio.sleep(1)
                finally:
                    if writer:
                        writer.close()
                        try:
                            await writer.wait_closed()
                        except OSError:
                            pass  # A reset socket must not prevent reconnection.
        finally:
            await self.coordinator.unavailable()

    async def monitor(self, reader):
        """Keep consuming events independently of the single window query.

        Active-window events cancel before querying. Title notifications still
        refresh matching without canceling an otherwise unchanged profile.
        An Event coalesces refresh work; revisions prevent stale publication.
        """
        refresh = asyncio.Event()
        refresh.set()  # Subscribe before the initial query.

        async def events():
            while True:
                line = await reader.readline()
                if not line:
                    raise ConnectionError('Hyprland event stream disconnected')
                moved = line.startswith((b'activewindowv2>>', b'activewindow>>'))
                if moved or line.startswith((b'windowtitle>>', b'windowtitlev2>>')):
                    await self.coordinator.focus_event(moved=moved)
                    refresh.set()

        async def queries():
            while True:
                await refresh.wait()
                refresh.clear()
                revision = self.coordinator.focus_revision
                window = await query_window(self.signature)
                if await self.coordinator.focus_changed(window, revision=revision):
                    self.last_error = ''

        jobs = [asyncio.create_task(events()), asyncio.create_task(queries())]
        try:
            done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for job in done:
                job.result()
        finally:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
