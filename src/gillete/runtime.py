"""Route decoded physical controls into the engine without event feedback."""

from evdev import ecodes, UInput
from uuid import uuid4

from .engine import Engine
from .reports import Frame
from .keyboard_map import KeyboardMap


class UInputOutput:
    """Only constructed when software remapping is explicitly enabled."""
    def __init__(self, suffix=''):
        name = 'Gillete virtual input' + (' ' + suffix if suffix else '') + ' ' + uuid4().hex
        keys = sorted({value for name, value in ecodes.ecodes.items()
                       if name.startswith(('KEY_', 'BTN_')) and isinstance(value, int)
                       and 0 < value < ecodes.KEY_MAX and name not in ('KEY_CNT',)})
        self.device = UInput({ecodes.EV_KEY: keys,
                              ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL]},
                             name=name, phys='gillete/uinput', bustype=ecodes.BUS_VIRTUAL)
        self.closed = False
        self.keymap = KeyboardMap(name.lower().replace(' ', '-'))

    async def prepare_keyboard(self):
        await self.keymap.install()

    async def restore_keyboard(self):
        await self.keymap.restore()

    def key(self, code, value):
        self.device.write(ecodes.EV_KEY, code, value)
        self.device.syn()

    def relative(self, code, value):
        self.device.write(ecodes.EV_REL, code, value)
        self.device.syn()

    def close(self):
        if not self.closed:
            self.device.close()
            self.closed = True


class Router:
    """Merge multi-interface held states and pair releases with their press.

    Engine actions must be fully resolved before this router is used with a
    grabbed device. Keeping an unrecognized stored binding is a preflight error,
    never permission to silently emit a factory key instead.
    """
    def __init__(self, engine: Engine, *, trace=None):
        self.engine = engine
        self.trace = trace
        self.groups: dict[str, frozenset[str]] = {}

    @property
    def held(self):
        return frozenset().union(*self.groups.values())

    async def feed(self, frame: Frame, *, activate=True):
        before = self.held
        self.groups[frame.source] = frame.controls
        after = self.held
        if self.trace is not None:
            self.trace.held = after
        # Release non-trigger controls first when a device reports both at once.
        released = before - after
        for control in sorted(released, key=lambda c: c in self.engine.shift_holders):
            self.observe(frame, control, 'up', activate)
            await self.engine.release(control)
        pressed = after - before
        if activate:
            for control in sorted(pressed, key=lambda c: self.engine.resolve(c).kind != 'hypershift'):
                self.observe(frame, control, 'down', activate)
                if not await self.engine.press(control):
                    raise RuntimeError(f'Unresolved stored assignment: {control}')
        else:
            # Old reports still carry releases and held-state information.
            # Suppress a held control until its release, rather than dropping
            # the frame and mistaking a later duplicate for a new press.
            for control in pressed:
                self.observe(frame, control, 'down', activate)
                self.engine.block_until_release(control)
        for axis, value in frame.motion:
            self.engine.ledger.output.relative(ecodes.ecodes[axis], value)
        if not activate:
            return
        for control, count in frame.pulses:
            # Wheel movement has no held state and must produce a complete pair
            # for each detent, including when the mapped action emits a key.
            if control in after:
                continue
            for _ in range(count):
                self.observe(frame, control, 'down', activate)
                if not await self.engine.press(control):
                    raise RuntimeError(f'Unresolved stored assignment: {control}')
                self.observe(frame, control, 'up', activate)
                await self.engine.release(control)

    def observe(self, frame, control, direction, activate):
        if self.trace is not None:
            self.trace.record(self.engine, frame.source, control, direction, activate=activate)

    async def close(self):
        await self.engine.disconnect()
        self.groups.clear()
