"""Offline XKB compilation for modifier-stable F13–F24 on owned outputs.

No file, device or compositor operation occurs here. The caller must establish
ownership before installing the result. This deliberately does not reuse the
physical-device selectors or mutate the system XKB database.
"""

from contextlib import contextmanager
import ctypes as C
from ctypes.util import find_library
from dataclasses import dataclass
import json
import re
from evdev import ecodes


MAX_TEXT = 1024 * 1024
REAL_MODIFIERS = ('Shift', 'Lock', 'Control', 'Mod1', 'Mod2', 'Mod3', 'Mod4', 'Mod5')
LogCallback = C.CFUNCTYPE(None, C.c_void_p, C.c_int, C.c_char_p, C.c_void_p)


class Names(C.Structure):
    _fields_ = [(name, C.c_char_p) for name in ('rules', 'model', 'layout', 'variant', 'options')]


class XKB:
    """Small typed binding; all allocated C objects have explicit lifetimes."""
    def __init__(self):
        path = find_library('xkbcommon')
        if not path:
            raise RuntimeError('libxkbcommon is required for virtual function keys')
        self.lib = C.CDLL(path)
        ptr, number, string = C.c_void_p, C.c_uint32, C.c_char_p
        functions = {
            'context_new': (ptr, [C.c_int]), 'context_unref': (None, [ptr]),
            'context_set_log_fn': (None, [ptr, LogCallback]),
            'keymap_new_from_names': (ptr, [ptr, C.POINTER(Names), C.c_int]),
            'keymap_new_from_string': (ptr, [ptr, string, C.c_int, C.c_int]),
            'keymap_get_as_string': (ptr, [ptr, C.c_int]), 'keymap_unref': (None, [ptr]),
            'keymap_num_layouts': (number, [ptr]), 'keymap_layout_get_name': (string, [ptr, number]),
            'keymap_key_by_name': (number, [ptr, string]), 'keymap_key_repeats': (C.c_int, [ptr, number]),
            'keymap_mod_get_index': (number, [ptr, string]),
            'state_new': (ptr, [ptr]), 'state_unref': (None, [ptr]),
            'state_update_mask': (number, [ptr, *([number] * 6)]),
            'state_key_get_one_sym': (number, [ptr, number]),
            'state_key_get_consumed_mods': (number, [ptr, number]),
            'state_update_key': (number, [ptr, number, C.c_int]),
            'state_serialize_mods': (number, [ptr, C.c_int]),
            'state_serialize_layout': (number, [ptr, C.c_int]),
            'keysym_from_name': (number, [string, C.c_int]),
        }
        for name, (result, arguments) in functions.items():
            function = getattr(self.lib, 'xkb_' + name)
            function.restype, function.argtypes = result, arguments
            setattr(self, name, function)
        self.free = C.CDLL(None).free
        self.free.argtypes, self.free.restype = [ptr], None
        self.errors = {}

    @contextmanager
    def context(self):
        context = self.context_new(0)
        if not context:
            raise RuntimeError('Could not allocate XKB context')
        errors = self.errors[context] = []
        @LogCallback
        def log(_context, level, _format, _arguments):
            # libxkbcommon may return a usable pointer after ignoring bad
            # RMLVO components. Reject that partial fallback too. va_list is
            # deliberately never dereferenced or formatted from Python.
            if level <= 20: errors.append(level)
        self.context_set_log_fn(context, log)
        try:
            yield context
        finally:
            self.context_unref(context)
            self.errors.pop(context, None)

    @contextmanager
    def keymap(self, context, *, names=None, text=None, format=1):
        self.errors[context].clear()
        if text is not None:
            if not isinstance(text, str) or '\0' in text or len(text.encode()) > MAX_TEXT:
                raise ValueError('XKB source is invalid or exceeds the size limit')
            pointer = self.keymap_new_from_string(context, text.encode(), format, 0)
        elif format == 1:
            values = Names(*(names[name].encode() for name, _ in Names._fields_))
            pointer = self.keymap_new_from_names(context, C.byref(values), 0)
        else:
            try:
                function = self.lib.xkb_keymap_new_from_names2
            except AttributeError as error:
                raise RuntimeError('XKB format2 requires libxkbcommon1.11 or newer') from error
            function.restype, function.argtypes = C.c_void_p, [C.c_void_p, C.POINTER(Names), C.c_int, C.c_int]
            values = Names(*(names[name].encode() for name, _ in Names._fields_))
            pointer = function(context, C.byref(values), format, 0)
        if not pointer or self.errors[context]:
            if pointer: self.keymap_unref(pointer)
            raise ValueError('XKB keymap compilation failed; no fallback layout was substituted')
        try:
            yield pointer
        finally:
            self.keymap_unref(pointer)

    def text(self, keymap, format):
        pointer = self.keymap_get_as_string(keymap, format)
        if not pointer:
            raise RuntimeError('Could not serialize XKB keymap')
        try:
            value = C.string_at(pointer)
            if len(value) > MAX_TEXT:
                raise ValueError('Serialized XKB keymap exceeds the size limit')
            return value.decode()
        finally:
            self.free(pointer)

    @contextmanager
    def state(self, keymap):
        pointer = self.state_new(keymap)
        if not pointer:
            raise RuntimeError('Could not allocate XKB state')
        try:
            yield pointer
        finally:
            self.state_unref(pointer)


def symbols_end(text):
    """Locate the compiled symbols block, honoring strings and comments."""
    tokens = re.finditer(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|\bxkb_symbols\b|[{}]', text)
    depth, selected = 0, False
    for token in tokens:
        if token.group() == 'xkb_symbols' and depth == 1:
            selected = True
        elif token.group() == '{': depth += 1
        elif token.group() == '}':
            depth -= 1
            if selected and depth == 1: return token.start()
    raise ValueError('Compiled XKB symbols section is missing or unbalanced')


@dataclass(frozen=True)
class CompiledMap:
    text: str
    format: int
    layout_names: tuple[str, ...]
    marker: str
    verified_combinations: int


def verify(xkb, keymap, layouts):
    """All 256 core modifier states, every layout, with no consumed modifiers."""
    indices = [xkb.keymap_mod_get_index(keymap, name.encode()) for name in REAL_MODIFIERS]
    if any(index >= 32 for index in indices):
        raise ValueError('Keymap lacks the eight core XKB modifiers')
    keys = [(xkb.keymap_key_by_name(keymap, f'FK{i}'.encode()),
             xkb.keysym_from_name(f'F{i}'.encode(), 0)) for i in range(13, 25)]
    if any(code == 0xFFFFFFFF or not symbol for code, symbol in keys):
        raise ValueError('Keymap lacks F13–F24 keycodes or symbols')
    count = 0
    with xkb.state(keymap) as state:
        for layout in range(layouts):
            for bits in range(256):
                mask = sum(1 << index for bit, index in enumerate(indices) if bits & (1 << bit))
                xkb.state_update_mask(state, mask, 0, 0, 0, 0, layout)
                before = (xkb.state_serialize_mods(state, 8), xkb.state_serialize_layout(state, 128))
                for code, symbol in keys:
                    if xkb.state_key_get_one_sym(state, code) != symbol or xkb.state_key_get_consumed_mods(state, code):
                        raise ValueError('Function key symbols or modifiers failed offline verification')
                    xkb.state_update_key(state, code, 1)
                    pressed = (xkb.state_serialize_mods(state, 8), xkb.state_serialize_layout(state, 128))
                    xkb.state_update_key(state, code, 0)
                    released = (xkb.state_serialize_mods(state, 8), xkb.state_serialize_layout(state, 128))
                    if pressed != before or released != before:
                        raise ValueError('Function key changes modifier or layout state')
                    count += 1
    return count


def compile_keymap(names, *, marker, source=None, format=1):
    if format not in (1, 2) or type(format) is not int:
        raise ValueError('Expected XKB format1 or2')
    if not isinstance(marker, str) or not re.fullmatch(r'gillete-fkeys-[a-z0-9-]{1,64}', marker):
        raise ValueError('Expected a private Gillete keymap marker')
    allowed = {name for name, _ in Names._fields_}
    if (not isinstance(names, dict) or set(names) - allowed
            or any(not isinstance(value, str) or '\0' in value or len(value) > 4096 for value in names.values())):
        raise ValueError('Invalid keyboard rules/model/layout/variant/options')
    values = {name: names.get(name, '') for name in allowed}
    for name, default in (('rules', 'evdev'), ('model', 'pc105'), ('layout', 'us')):
        if not values[name]: values[name] = default
    if source is None and format == 1 and len(values['layout'].split(',')) > 4:
        raise ValueError('More than four layouts require XKB format2; no layouts were dropped')
    xkb = XKB()
    with xkb.context() as context, xkb.keymap(context, names=values, text=source, format=format) as original:
        layouts = xkb.keymap_num_layouts(original)
        if not 1 <= layouts <= 32:
            raise ValueError('Unsupported XKB layout count')
        if source is None and layouts != len(values['layout'].split(',')):
            raise ValueError('XKB rules changed the requested layout count; no layouts were dropped')
        text = xkb.text(original, format)
        end = symbols_end(text)
        labels, additions = [], []
        for layout in range(layouts):
            original_name = (xkb.keymap_layout_get_name(original, layout) or b'Layout').decode()
            if any(ord(c) < 32 for c in original_name):
                raise ValueError('Unsupported control character in XKB layout name')
            label = f'{marker}: {original_name}'
            labels.append(label)
            additions.append(f'name[Group{layout + 1}] = {json.dumps(label, ensure_ascii=False)};')
        for number in range(13, 25):
            code = xkb.keymap_key_by_name(original, f'FK{number}'.encode())
            if code == 0xFFFFFFFF:
                raise ValueError('Original keymap lacks a required function-key name')
            if code != getattr(ecodes, f'KEY_F{number}') + 8:
                raise ValueError('Custom function-key keycodes differ from Linux evdev; no incorrect map was substituted')
            fields = [f'repeat={"true" if xkb.keymap_key_repeats(original, code) else "false"}']
            for group in range(1, layouts + 1):
                fields.extend((f'type[Group{group}]="ONE_LEVEL"', f'symbols[Group{group}]=[F{number}]',
                               f'actions[Group{group}]=[NoAction()]'))
            additions.append(f'replace key <FK{number}> {{' + ', '.join(fields) + '};')
            additions.append(f'modifier_map None {{ <FK{number}> }};')
        candidate = text[:end] + '\n' + '\n'.join(additions) + '\n' + text[end:]
        with xkb.keymap(context, text=candidate, format=format) as corrected:
            if xkb.keymap_num_layouts(corrected) != layouts:
                raise ValueError('Function-key correction changed layout count')
            if tuple(xkb.keymap_layout_get_name(corrected, i).decode() for i in range(layouts)) != tuple(labels):
                raise ValueError('Function-key map ownership labels did not compile')
            count = verify(xkb, corrected, layouts)
            serialized = xkb.text(corrected, format)
        return CompiledMap(serialized, format, tuple(labels), marker, count)
