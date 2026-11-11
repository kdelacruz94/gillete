from types import SimpleNamespace
import fcntl
import struct
import time

import pytest
from evdev import ecodes

from gillete import native_macro_observer as observer
from gillete.protocol import ProtocolError


def event(value, stamp, code=ecodes.KEY_F24, kind=ecodes.EV_KEY):
    return SimpleNamespace(type=kind, code=code, value=value, timestamp=lambda: stamp)


def setup(monkeypatch, events):
    clock = [10.]
    source = SimpleNamespace(fd=123, read=lambda: events)
    watcher = observer.Observer(SimpleNamespace(interfaces=[]))
    watcher.sources = [source]
    monkeypatch.setattr(observer.time, 'monotonic', lambda: clock[0])
    def readable(*_):
        clock[0] += .2
        return [source], [], []
    monkeypatch.setattr(observer.select, 'select', readable)
    return watcher, clock


def test_monotonic_observer_ignores_stale_events_and_measures_first_press_release(monkeypatch):
    watcher, _ = setup(monkeypatch, [event(1, 9), event(0, 9.1), event(0, 10.01),
                                    event(1, 10.02), event(2, 10.05), event(0, 10.1)])
    watcher.arm()
    result = watcher.observe(lambda: False)
    assert result['f24_down'] and result['f24_up']
    assert result['hold_ms'] == pytest.approx(80.)


def test_unarmed_cancelled_timedout_or_dropped_stream_is_not_accepted(monkeypatch):
    watcher, _ = setup(monkeypatch, [])
    with pytest.raises(ProtocolError, match='armed'): watcher.observe(lambda: False)
    watcher.arm()
    with pytest.raises(InterruptedError): watcher.observe(lambda: True)
    with pytest.raises(ProtocolError, match='timed out'): watcher.observe(lambda: False)
    watcher, _ = setup(monkeypatch, [event(0, 10.1, ecodes.SYN_DROPPED, ecodes.EV_SYN)])
    watcher.arm()
    with pytest.raises(ProtocolError, match='dropped'): watcher.observe(lambda: False)


def test_observer_closes_every_opened_source_on_failure_and_never_grabs(monkeypatch):
    closed = []
    def make(path):
        if path == 'bad': raise PermissionError('unreadable keyboard')
        return SimpleNamespace(fd=123, close=lambda: closed.append(path),
                               capabilities=lambda: {ecodes.EV_KEY: [ecodes.KEY_F24]}, set_clockid=lambda _: None)
    monkeypatch.setattr(fcntl, 'ioctl', lambda *_: 0)
    monkeypatch.setattr(observer, 'InputDevice', make)
    watcher = observer.Observer(SimpleNamespace(interfaces=[{'kind': 'input', 'path': 'ok'},
                                                            {'kind': 'input', 'path': 'bad'}]))
    with pytest.raises(PermissionError): watcher.__enter__()
    assert closed == ['ok'] and watcher.sources == []


def test_monotonic_clock_works_with_installed_evdev_without_set_clockid_method(monkeypatch):
    calls, closed = [], []
    source = SimpleNamespace(fd=123, close=lambda: closed.append(True),
                             capabilities=lambda: {ecodes.EV_KEY: [ecodes.KEY_F24]})
    monkeypatch.setattr(observer, 'InputDevice', lambda _: source)
    monkeypatch.setattr(fcntl, 'ioctl', lambda *args: calls.append(args))
    with observer.Observer(SimpleNamespace(interfaces=[{'kind': 'input', 'path': 'keyboard'}])):
        pass
    assert calls == [(123, 0x400445A0, struct.pack('i', time.CLOCK_MONOTONIC))]
    assert closed == [True]
