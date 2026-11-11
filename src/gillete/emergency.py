"""Session-only Hyprland emergency shortcut; preserves an existing binding."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

from .onboard import durable_json
from .stop_shortcut import DEFAULT, StopShortcut


class EmergencyShortcut:
    def __init__(self, focus, receipt=None, *, shortcut=DEFAULT):
        self.focus = focus
        self.shortcut = StopShortcut.parse(shortcut)
        self.label = self.shortcut.label
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

    async def matches(self, shortcut=None):
        bindings = json.loads(await self.hyprctl('-j', 'binds'))
        if not isinstance(bindings, list) or any(not isinstance(b, dict) for b in bindings):
            raise RuntimeError('Cannot inspect Hyprland emergency shortcut conflicts')
        return [b for b in bindings if (shortcut or self.shortcut).matches(b)]

    async def unbind(self, shortcut, backend):
        if backend == 'lua':
            await self.hyprctl('eval', 'hl.unbind(' + json.dumps(shortcut.lua) + ')')
        else:
            await self.hyprctl('keyword', 'unbind', shortcut.legacy)

    def read_receipt(self):
        try:
            receipt = json.loads(self.receipt.read_text())
        except (OSError, ValueError):
            return {}
        return receipt if isinstance(receipt, dict) else {}

    def owned_binding(self, receipt, matches):
        if receipt.get('command') != self.command or receipt.get('backend') not in ('lua', 'legacy'):
            return None
        for binding in matches:
            if receipt.get('binding') == binding:
                return binding
            if receipt.get('status') == 'prepared':
                if (receipt['backend'] == 'lua' and receipt.get('description') == self.description
                        and binding.get('description') == self.description):
                    return binding
                if (receipt['backend'] == 'legacy' and binding.get('dispatcher') == 'exec'
                        and binding.get('arg') == self.command):
                    return binding
        return None

    def journal(self, status):
        durable_json(self.receipt, {'version': 1, 'command': self.command, 'backend': self.backend,
            'binding': self.binding, 'shortcut': self.label, 'description': self.description, 'status': status})

    async def recover_previous(self):
        """Remove only an exact owned receipt left at a different saved chord."""
        receipt = self.read_receipt()
        if receipt.get('command') != self.command:
            return
        previous = StopShortcut.parse(receipt.get('shortcut', DEFAULT))
        if previous == self.shortcut or receipt.get('backend') not in ('lua', 'legacy'):
            return
        matches = await self.matches(previous)
        if self.owned_binding(receipt, matches) is None:
            return  # Changed or removed by the user; it is no longer ours.
        if len(matches) != 1:
            raise RuntimeError('The previous Gillete emergency shortcut now shares a binding; resolve it before enabling')
        await self.unbind(previous, receipt['backend'])
        if await self.matches(previous):
            raise RuntimeError('Previous Gillete emergency shortcut could not be removed')
        self.receipt.unlink(missing_ok=True)

    async def install(self):
        await self.recover_previous()
        matches = await self.matches()
        if matches:
            if (len(matches) == 1 and matches[0].get('dispatcher') == 'exec' and matches[0].get('arg') == self.command
                    and matches[0].get('key') == self.shortcut.key and not matches[0].get('keycode')):
                self.backend, self.binding = 'legacy', matches[0]
                self.installed = True
                self.journal('installed')
                return
            receipt = self.read_receipt()
            if len(matches) == 1 and self.owned_binding(receipt, matches) is not None:
                self.backend, self.binding = receipt['backend'], matches[0]
                self.installed = True
                self.journal('installed')
                return
            raise RuntimeError(self.label + ' is already bound in Hyprland; choose another emergency shortcut in Startup and restart the service')
        # Hyprland 0.55+ supports Lua; 0.57 removed keyword config requests.
        # Query registered state after either API instead of trusting an "ok".
        code = ('hl.bind(' + json.dumps(self.shortcut.lua) + ', hl.dsp.exec_cmd('
                + json.dumps(self.command, ensure_ascii=False) + '), {description='
                + json.dumps(self.description) + '})')
        self.backend = 'lua'
        self.binding = None
        self.journal('prepared')
        result = await self.hyprctl('eval', code)
        if 'unknown request' in result.lower():
            self.backend = 'legacy'
            self.journal('prepared')
            await self.hyprctl('keyword', 'bind', self.shortcut.legacy + ', exec, ' + self.command)
        matches = await self.matches()
        own = (len(matches) == 1 and ((self.backend == 'lua' and matches[0].get('description') == self.description)
                                     or (self.backend == 'legacy' and matches[0].get('arg') == self.command)))
        if not own:
            raise RuntimeError('Hyprland did not accept the emergency shortcut')
        self.binding = matches[0]
        self.installed = True
        self.journal('installed')

    async def remove(self):
        if not self.installed:
            receipt = self.read_receipt()
            if receipt.get('command') != self.command or StopShortcut.parse(receipt.get('shortcut', DEFAULT)) != self.shortcut:
                return
            matches = await self.matches()
            binding = self.owned_binding(receipt, matches)
            if binding is None:
                return
            self.binding, self.backend = binding, receipt['backend']
            self.installed = True
        matches = await self.matches()
        if self.binding in matches and len(matches) != 1:
            raise RuntimeError('Emergency shortcut now shares a desktop binding; retained its ownership receipt for recovery')
        if len(matches) == 1 and matches[0] == self.binding:
            await self.unbind(self.shortcut, self.backend)
            if await self.matches():
                raise RuntimeError('Emergency shortcut removal was not verified; retained its ownership receipt')
        self.receipt.unlink(missing_ok=True)
        self.installed = False
