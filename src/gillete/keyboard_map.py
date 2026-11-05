"""Session-only function-key correction for Gillete's own Hyprland keyboard.

XKB's default inet symbols repurpose F13–F18 and F20–F23. Sending the
correct Linux KEY_F23 is insufficient: clients receive XF86TouchpadOff.
Use the standard fkeys option on only our output, keeping other options.
"""

import asyncio
import json
import os


FUNCTION_KEYS = 'fkeys:basic_13-24'


class KeyboardMap:
    def __init__(self, name, signature=None):
        if not name.startswith('gillete-virtual-input'):
            raise ValueError('Keyboard correction is restricted to Gillete outputs')
        self.name = name
        self.signature = signature or os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
        self.before = self.applied = self.address = None
        self.backend = 'lua'

    async def hyprctl(self, *args):
        process = await asyncio.create_subprocess_exec(
            'hyprctl', '-i', self.signature, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, error = await asyncio.wait_for(process.communicate(), 3)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError('Virtual keyboard setup: ' + error.decode(errors='replace').strip())
        return out.decode()

    async def keyboard(self):
        matches = [k for k in json.loads(await self.hyprctl('-j', 'devices'))['keyboards']
                   if k['name'] == self.name]
        if len(matches) > 1:
            raise RuntimeError('Ambiguous Gillete virtual keyboard')
        return matches[0] if matches else None

    async def set_options(self, options):
        if self.backend == 'lua':
            result = await self.hyprctl('eval', 'hl.device({name=' + json.dumps(self.name)
                                       + ', resolve_binds_by_sym=true, kb_options=' + json.dumps(options) + '})')
            if 'unknown request' not in result.lower():
                return
            self.backend = 'legacy'
        await self.hyprctl('keyword', f'device[{self.name}]:resolve_binds_by_sym', 'true')
        await self.hyprctl('keyword', f'device[{self.name}]:kb_options', options)

    async def install(self):
        # udev/compositor discovery is asynchronous. No keys or physical input
        # ownership are allowed until the output has a verified configuration.
        for _ in range(30):
            keyboard = await self.keyboard()
            if keyboard is not None:
                break
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Hyprland did not discover the Gillete virtual keyboard')
        self.address = keyboard['address']
        self.before = keyboard.get('options', '')
        options = [o for o in self.before.split(',') if o]
        if FUNCTION_KEYS not in options:
            options.append(FUNCTION_KEYS)
        self.applied = ','.join(options)
        try:
            # Hyprland otherwise resolves compositor shortcuts against its
            # global keymap: e.g. corrected F20 would still mute the mic.
            # This policy belongs only to our ephemeral virtual keyboard.
            await self.set_options(self.applied)
            await self.verify()
        except BaseException:
            await self.restore()
            raise

    async def verify(self):
        keyboard = await self.keyboard()
        if (keyboard is None or keyboard['address'] != self.address
                or keyboard.get('options', '') != self.applied):
            raise RuntimeError('Gillete function-key correction was not retained by Hyprland')

    async def watch(self):
        while True:
            await asyncio.sleep(1)
            await self.verify()

    async def restore(self):
        if self.applied is None or self.before == self.applied:
            return
        keyboard = await self.keyboard()
        # A reload or user edit owns its new value. Never replace that value
        # or touch a newly created device with a reused name.
        if (keyboard is not None and keyboard['address'] == self.address
                and keyboard.get('options', '') == self.applied):
            await self.set_options(self.before)
            restored = await self.keyboard()
            if restored is not None and restored.get('options', '') != self.before:
                raise RuntimeError('Could not restore Gillete virtual keyboard options')
        self.applied = None
