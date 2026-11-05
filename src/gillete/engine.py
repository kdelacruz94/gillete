"""Physical-control lifecycle, independent of Linux event routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from evdev import ecodes

from .macros import KeyLedger, MacroRunner
from .hypershift import resolve_action
from .model import Action, Profile, key_code


@dataclass
class Press:
    action: Action
    owner: str
    preserve_pointer: bool = False


class Engine:
    def __init__(self, model: str, profile: Profile, ledger: KeyLedger,
                 launch: Callable[[Action], Awaitable[None]] | None = None,
                 select_profile: Callable[[str], Awaitable[None]] | None = None,
                 dpi: Callable[[str], Awaitable[None]] | None = None,
                 stored: dict[tuple[str, bool], Action] | None = None,
                 device_action: Callable[[str], Awaitable[None]] | None = None):
        self.model, self.profile, self.ledger = model, profile, ledger
        self.macros = MacroRunner(ledger)
        self.launch, self.select_profile = launch, select_profile
        self.dpi = dpi
        self.stored = stored
        self.device_action = device_action
        self.pressed: dict[str, Press] = {}
        self.disarmed: set[str] = set()
        self.shift_holders: set[str] = set()
        self.shift_latched = False
        self.generation = 0
        self.instance = f"device:{id(self)}"

    @property
    def shifted(self) -> bool:
        return self.shift_latched or bool(self.shift_holders)

    def owner(self, control: str) -> str:
        return f"{self.instance}:{self.generation}:{control}"

    def resolve(self, control: str, shifted: bool | None = None) -> Action:
        shifted = self.shifted if shifted is None else shifted
        action = resolve_action(self.profile, self.model, control, shifted, self.stored)
        if action is None:
            raise RuntimeError(f'Stored assignment needs an explicit software mapping: {control}')
        return action

    async def press(self, control: str) -> bool:
        """Return True to suppress the original input; repeats never retrigger."""
        if control in self.disarmed:
            return True
        if control in self.pressed:
            return self.pressed[control].action.kind != "passthrough"
        action = self.resolve(control)
        owner = self.owner(control)
        native_pointer = {'left_click': 'BTN_LEFT', 'right_click': 'BTN_RIGHT', 'wheel_click': 'BTN_MIDDLE'}
        preserve_pointer = (self.profile.resolve(self.model, control, self.shifted).kind == 'passthrough'
                            and action.kind == 'keys' and action.keys == (native_pointer.get(control),))
        self.pressed[control] = Press(action, owner, preserve_pointer)
        if action.kind == "keys":
            for key in action.keys:
                self.ledger.down(owner, key_code(key))
        elif action.kind == "scroll":
            self.ledger.output.relative(ecodes.ecodes[action.axis], action.value)
        elif action.kind == "dpi":
            if self.dpi is None:
                raise RuntimeError("No DPI control adapter attached")
            await self.dpi(action.target)
        elif action.kind == 'device':
            if self.device_action is None:
                raise RuntimeError('No native device action adapter attached')
            await self.device_action(action.target)
        elif action.kind in {"macro", "turbo"}:
            if action.playback == "toggle" and self.macros.running(owner):
                await self.macros.cancel(owner)
            else:
                await self.macros.start(owner, action)
        elif action.kind == "hypershift":
            if action.playback == "toggle":
                self.shift_latched = not self.shift_latched
            else:
                self.shift_holders.add(control)
        elif action.kind == "profile":
            if self.select_profile is None:
                raise RuntimeError("No profile-switch adapter attached")
            await self.select_profile(action.target)
        elif action.kind == "launch":
            if self.launch is None:
                raise RuntimeError("No program-launch adapter attached")
            await self.launch(action)
        return action.kind != "passthrough"

    async def release(self, control: str) -> bool:
        if control in self.disarmed:
            self.disarmed.remove(control)
            return True
        press = self.pressed.pop(control, None)
        if press is None:
            return False
        self.shift_holders.discard(control)
        if press.action.kind == "keys":
            self.ledger.release(press.owner)
        elif press.action.kind in {"macro", "turbo"} and press.action.playback == "held":
            await self.macros.cancel(press.owner)
        return press.action.kind != "passthrough"

    async def cancel(self, *, preserve_pointer=True):
        """Cancel generated actions; a held trigger must be released before reuse."""
        await self.macros.cancel_all()
        for control, press in list(self.pressed.items()):
            if press.action.kind != "passthrough" and not (preserve_pointer and press.preserve_pointer):
                self.ledger.release(press.owner)
                self.disarmed.add(control)
                self.pressed.pop(control)
        self.shift_holders.clear()
        self.shift_latched = False
        self.generation += 1

    async def change_profile(self, profile: Profile):
        await self.cancel()
        self.profile = profile

    async def disconnect(self):
        await self.cancel(preserve_pointer=False)
        self.pressed.clear()
        self.disarmed.clear()
