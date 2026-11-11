"""Complete function-key maps for uniquely owned Hyprland virtual outputs.

Physical selectors are deliberately unsupported. A unique output name is never
reused, so a retired runtime rule cannot configure a future keyboard. No global
option or physical keymap is changed, including during cleanup.
"""

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory

from .function_keymap import MAX_TEXT, compile_keymap


class KeyboardMap:
    def __init__(self, name, signature=None):
        if not re.fullmatch(r'gillete-virtual-input(?:-[a-z0-9]+)*-[0-9a-f]{32}', name):
            raise ValueError('Keyboard correction requires a unique owned Gillete output name')
        self.name = name
        self.signature = signature or os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
        self.marker = 'gillete-fkeys-' + name[-32:]
        self.address = self.rules = self.compiled = self.directory = self.path = None
        self.source_path = self.source_hash = self.source_value = None
        self.backend = 'lua'

    async def hyprctl(self, *args):
        process = await asyncio.create_subprocess_exec(
            'hyprctl', '-i', self.signature, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, error = await asyncio.wait_for(process.communicate(), 3)
        except BaseException:
            if process.returncode is None: process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError('Virtual keyboard setup: ' + error.decode(errors='replace').strip())
        return out.decode()

    async def keyboard(self):
        matches = [k for k in json.loads(await self.hyprctl('-j', 'devices'))['keyboards'] if k['name'] == self.name]
        if len(matches) > 1:
            raise RuntimeError('Ambiguous Gillete virtual keyboard')
        return matches[0] if matches else None

    async def global_source(self):
        value = json.loads(await self.hyprctl('-j', 'getoption', 'input.kb_file'))
        if not isinstance(value.get('str'), str):
            raise RuntimeError('Could not inspect the inherited custom keyboard file')
        return '' if value['str'] == '[[EMPTY]]' else value['str']

    @staticmethod
    def read_source(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RuntimeError('Keyboard maps must be regular files')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_TEXT + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_TEXT:
            raise RuntimeError('Inherited keyboard file exceeds the bounded size limit')
        return raw.decode(), sha256(raw).hexdigest()

    async def set_file(self):
        if self.backend == 'lua':
            result = await self.hyprctl('eval', 'hl.device({name=' + json.dumps(self.name)
                                       + ', resolve_binds_by_sym=true, kb_file=' + json.dumps(str(self.path), ensure_ascii=False) + '})')
            if 'unknown request' not in result.lower(): return
            self.backend = 'legacy'
        await self.hyprctl('keyword', f'device[{self.name}]:resolve_binds_by_sym', 'true')
        await self.hyprctl('keyword', f'device[{self.name}]:kb_file', str(self.path))

    def current_rules(self, keyboard):
        return {key: keyboard.get(key, '') for key in ('rules', 'model', 'layout', 'variant', 'options')}

    async def install(self):
        if self.directory is not None:
            raise RuntimeError('Virtual keymap is already installed')
        for _ in range(30):
            keyboard = await self.keyboard()
            if keyboard is not None: break
            await asyncio.sleep(.1)
        else:
            raise RuntimeError('Hyprland did not discover the Gillete virtual keyboard')
        self.address, self.rules = keyboard['address'], self.current_rules(keyboard)
        self.source_value = await self.global_source()
        source = None
        if self.source_value:
            self.source_path = Path(self.source_value).expanduser()
            if not self.source_path.is_absolute():
                raise RuntimeError('Use an absolute inherited kb_file path before enabling Gillete; no layout was substituted')
            source, self.source_hash = self.read_source(self.source_path)
        self.compiled = await asyncio.to_thread(compile_keymap, self.rules, marker=self.marker, source=source)
        current = await self.keyboard()
        if (current is None or current['address'] != self.address or self.current_rules(current) != self.rules
                or await self.global_source() != self.source_value):
            raise RuntimeError('Virtual keyboard changed during keymap preparation')
        self.directory = TemporaryDirectory(prefix='gillete-keymap-')
        self.path = Path(self.directory.name) / 'keyboard.xkb'
        try:
            with self.path.open('x', encoding='utf-8') as stream:
                os.chmod(self.path, 0o600)
                stream.write(self.compiled.text)
            self.file_hash = sha256(self.compiled.text.encode()).hexdigest()
            await self.set_file()
            for _ in range(30):
                try:
                    await self.verify()
                    return
                except RuntimeError:
                    await asyncio.sleep(.1)
            await self.verify()
        except BaseException:
            await self.restore()
            raise

    async def verify(self):
        keyboard = await self.keyboard()
        if (self.compiled is None or self.path is None or keyboard is None
                or keyboard['address'] != self.address or self.current_rules(keyboard) != self.rules
                or keyboard.get('active_keymap') not in self.compiled.layout_names
                or await self.global_source() != self.source_value):
            raise RuntimeError('Gillete function-key map was not retained by Hyprland')
        if self.read_source(self.path)[1] != self.file_hash:
            raise RuntimeError('Gillete virtual keymap file changed')
        if self.source_path and self.read_source(self.source_path)[1] != self.source_hash:
            raise RuntimeError('Inherited custom keymap changed; restart software control to rebuild it')

    async def watch(self):
        while True:
            await asyncio.sleep(1)
            await self.verify()

    async def restore(self):
        # Close the uniquely named output before retiring its file. Never
        # issue inverse setters or guess inherited settings. Hyprland has no
        # exact per-field unset API; this name is never reused by the producer.
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
        self.path = None
