"""Session-only Hyprland emergency shortcut; preserves an existing binding."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

from .onboard import durable_json


class EmergencyShortcut:
    label = 'Ctrl+Alt+Pause'

    def __init__(self, focus, receipt=None):
        self.focus = focus
        self.installed = False
        self.backend = None
        self.binding = None
        self.receipt = receipt or Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'gillete/emergency.json'
        self.command = shlex.join(['/usr/bin/env', f'PYTHONPATH={Path(__file__).resolve().parent.parent}',
                                   sys.executable, '-m', 'gillete.cli', 'control', 'stop-actions'])
        self.description = 'Gillete emergency stop ' + hashlib.sha256(self.command.encode()).hexdigest()[:16]

    async def hyprctl(self, *args):
        process = await asyncio.create_subprocess_exec('hyprctl', '-i', self.focus.signature, *args,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, error = await asyncio.wait_for(process.communicate(), 3)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError('Emergency shortcut: ' + error.decode(errors='replace').strip())
        return out.decode()

    async def matches(self):
        bindings = json.loads(await self.hyprctl('-j', 'binds'))
        return [b for b in bindings if b.get('modmask') == 12
                and (b.get('key', '').lower() == 'pause' or b.get('keycode') in (119, 127))]

    async def install(self):
        matches = await self.matches()
        if matches:
            if len(matches) == 1 and matches[0].get('dispatcher') == 'exec' and matches[0].get('arg') == self.command:
                self.backend, self.binding = 'legacy', matches[0]
                self.installed = True
                return
            try:
                receipt = json.loads(self.receipt.read_text())
            except (OSError, ValueError):
                receipt = {}
            if (len(matches) == 1 and receipt.get('command') == self.command
                    and receipt.get('binding') == matches[0] and receipt.get('backend') in ('lua', 'legacy')):
                self.backend, self.binding = receipt['backend'], matches[0]
                self.installed = True
                return
            raise RuntimeError('Ctrl+Alt+Pause is already bound in Hyprland; choose another shortcut before enabling Gillete')
        # Hyprland 0.55+ supports Lua; 0.57 removed keyword config requests.
        # Query registered state after either API instead of trusting an "ok".
        code = ('hl.bind("CTRL + ALT + Pause", hl.dsp.exec_cmd('
                + json.dumps(self.command, ensure_ascii=False) + '), {description='
                + json.dumps(self.description) + '})')
        self.backend = 'lua'
        result = await self.hyprctl('eval', code)
        if 'unknown request' in result.lower():
            self.backend = 'legacy'
            await self.hyprctl('keyword', 'bind', 'CTRL ALT, Pause, exec, ' + self.command)
        matches = await self.matches()
        own = (len(matches) == 1 and ((self.backend == 'lua' and matches[0].get('description') == self.description)
                                     or (self.backend == 'legacy' and matches[0].get('arg') == self.command)))
        if not own:
            raise RuntimeError('Hyprland did not accept the emergency shortcut')
        self.binding = matches[0]
        self.installed = True
        durable_json(self.receipt, {'version': 1, 'command': self.command, 'backend': self.backend, 'binding': self.binding})

    async def remove(self):
        if not self.installed:
            return
        matches = await self.matches()
        if len(matches) == 1 and matches[0] == self.binding:
            if self.backend == 'lua':
                await self.hyprctl('eval', 'hl.unbind("CTRL + ALT + Pause")')
            else:
                await self.hyprctl('keyword', 'unbind', 'CTRL ALT, Pause')
        self.receipt.unlink(missing_ok=True)
        self.installed = False
