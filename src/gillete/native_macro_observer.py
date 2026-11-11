"""Read only F24 transitions from the selected V3; no grabs or injection."""

import fcntl
import select
import struct
import time

from evdev import InputDevice, ecodes

from .protocol import ProtocolError


class Observer:
    def __init__(self, device):
        self.device, self.sources, self.armed_at = device, [], None

    def __enter__(self):
        try:
            for interface in self.device.interfaces:
                if interface['kind'] != 'input': continue
                source = InputDevice(interface['path'])
                self.sources.append(source)
                if ecodes.KEY_F24 not in source.capabilities().get(ecodes.EV_KEY, []):
                    self.sources.pop().close()
                else:
                    # Linux EVIOCSCLOCKID is not exposed by installed evdev.
                    # This changes timestamps on our fd only, not mouse state.
                    fcntl.ioctl(source.fd, 0x400445A0, struct.pack('i', time.CLOCK_MONOTONIC))
            if not self.sources:
                raise ProtocolError('No readable V3 F24 keyboard interface; no macro change attempted')
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_):
        for source in self.sources: source.close()
        self.sources.clear()

    def arm(self):
        self.armed_at = time.monotonic()

    def observe(self, stopped):
        if self.armed_at is None:
            raise ProtocolError('F24 observer was not armed')
        pressed = {}
        deadline = self.armed_at + 180
        while time.monotonic() < deadline:
            if stopped(): raise InterruptedError('Native macro observation cancelled')
            readable, _, _ = select.select(self.sources, [], [], .2)
            for source in readable:
                for event in source.read():
                    if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                        raise ProtocolError('Keyboard events dropped; native macro observation invalid')
                    if (event.timestamp() < self.armed_at or event.type != ecodes.EV_KEY
                            or event.code != ecodes.KEY_F24): continue
                    if event.value == 1: pressed.setdefault(source.fd, event.timestamp())
                    elif event.value == 0 and source.fd in pressed:
                        return {'f24_down': True, 'f24_up': True,
                                'hold_ms': (event.timestamp() - pressed[source.fd]) * 1000}
        raise ProtocolError('Native F24 press/release observation timed out')


class SequenceObserver(Observer):
    """Observe the fixed four-press profile test; never grabs or injects."""
    expected = (ecodes.KEY_F24, ecodes.KEY_F23, ecodes.KEY_F24, ecodes.KEY_F23)

    def __enter__(self):
        super().__enter__()
        try:
            if not all(set(self.expected) <= set(s.capabilities().get(ecodes.EV_KEY, [])) for s in self.sources):
                raise ProtocolError('Selected V3 keyboard lacks F23/F24 event capabilities')
            return self
        except BaseException:
            self.__exit__()
            raise

    def observe(self, stopped):
        if self.armed_at is None: raise ProtocolError('Sequence observer was not armed')
        pressed, result = {}, []
        while time.monotonic() < self.armed_at + 180:
            if stopped(): raise InterruptedError('Native profile observation cancelled')
            readable, _, _ = select.select(self.sources, [], [], .2)
            for source in readable:
                for event in source.read():
                    if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                        raise ProtocolError('Keyboard events dropped during profile observation')
                    if (event.timestamp() < self.armed_at or event.type != ecodes.EV_KEY
                            or event.code not in self.expected): continue
                    key = (source.fd, event.code)
                    if event.code != self.expected[len(result)]:
                        raise ProtocolError('F23/F24 sequence differs from the requested button order')
                    if event.value == 1:
                        if pressed and key not in pressed: raise ProtocolError('Overlapping native test keys')
                        pressed.setdefault(key, event.timestamp())
                    elif event.value == 0 and key in pressed:
                        result.append({'key': 'F24' if event.code == ecodes.KEY_F24 else 'F23',
                                       'hold_ms': (event.timestamp() - pressed.pop(key)) * 1000})
                        if len(result) == len(self.expected): return {'sequence': result}
        raise ProtocolError('Native profile sequence timed out')
