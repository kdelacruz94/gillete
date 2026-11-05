from evdev import ecodes as E
import pytest

from gillete.model import ConfigurationError, Step
from gillete.recorder import Recorder, replace_delays


def test_fixed_delay_applies_only_between_recorded_events_and_preserves_chords():
    recorder = Recorder(fixed_delay_ms=25)
    for code, value, timestamp in ((E.KEY_LEFTCTRL, 1, 10), (E.KEY_K, 1, 10),
                                    (E.KEY_K, 2, 10.04), (E.KEY_K, 0, 10.21),
                                    (E.KEY_LEFTCTRL, 0, 10.22), (E.KEY_M, 1, 12), (E.KEY_M, 0, 12.05)):
        recorder.feed(E.EV_KEY, code, value, timestamp)
    action = recorder.finish()
    assert [s.milliseconds for s in action.steps if s.kind == 'wait'] == [25] * 5
    assert [(s.kind, s.key) for s in action.steps if s.kind != 'wait'] == [
        ('down', 'KEY_LEFTCTRL'), ('down', 'KEY_K'), ('up', 'KEY_K'), ('up', 'KEY_LEFTCTRL'),
        ('down', 'KEY_M'), ('up', 'KEY_M')]


def test_fixed_zero_no_recording_and_timestamp_errors_are_explicit():
    recorder = Recorder(fixed_delay_ms=0)
    with pytest.raises(ConfigurationError, match='No keys'):
        recorder.finish()
    recorder.feed(E.EV_KEY, E.KEY_A, 1, 1)
    for timestamp in (.9999, float('nan'), float('inf')):
        with pytest.raises(ConfigurationError, match='finite and monotonic'):
            recorder.feed(E.EV_KEY, E.KEY_A, 0, timestamp)
        assert recorder.held == ['KEY_A']
    recorder.feed(E.EV_KEY, E.KEY_A, 0, 2)
    assert recorder.finish().steps == (Step('down', key='KEY_A'), Step('up', key='KEY_A'))
    for value in (-1, 1.5, True, 3_600_001):
        with pytest.raises(ConfigurationError):
            Recorder(fixed_delay_ms=value)


def test_recording_limit_reserves_balanced_release_and_never_admits_oversized_action():
    recorder = Recorder(max_steps=2)
    recorder.feed(E.EV_KEY, E.KEY_A, 1, 1)
    assert len(recorder.finish().steps) == 2
    recorder = Recorder(max_steps=2)
    recorder.feed(E.EV_KEY, E.KEY_A, 1, 1)
    with pytest.raises(ConfigurationError, match='limit'):
        recorder.feed(E.EV_KEY, E.KEY_B, 1, 1)
    with pytest.raises(ConfigurationError, match='limit'):
        recorder.finish()


def test_replace_delays_preserves_event_order_and_zero_gap_chord_members():
    steps = (Step('wait', milliseconds=300), Step('down', key='KEY_LEFTCTRL'), Step('down', key='KEY_K'),
             Step('wait', milliseconds=40), Step('up', key='KEY_K'), Step('up', key='KEY_LEFTCTRL'))
    updated = replace_delays(steps, 70)
    assert [s for s in updated if s.kind != 'wait'] == [s for s in steps if s.kind != 'wait']
    assert [s.milliseconds for s in updated if s.kind == 'wait'] == [70, 70]
    assert steps[0].milliseconds == 300


@pytest.mark.parametrize('fixed_delay, expected_waits', [(None, [250]), (30, [30, 30, 30]), (0, [])])
def test_stop_during_chord_preserves_hold_duration_and_releases_in_reverse_order(fixed_delay, expected_waits):
    recorder = Recorder(fixed_delay_ms=fixed_delay)
    recorder.feed(E.EV_KEY, E.KEY_LEFTCTRL, 1, 1)
    recorder.feed(E.EV_KEY, E.KEY_K, 1, 1)
    steps = recorder.finish(timestamp=1.25).steps
    assert [s.milliseconds for s in steps if s.kind == 'wait'] == expected_waits
    assert [(s.kind, s.key) for s in steps if s.kind != 'wait'] == [
        ('down', 'KEY_LEFTCTRL'), ('down', 'KEY_K'), ('up', 'KEY_K'), ('up', 'KEY_LEFTCTRL')]


def test_stop_timing_never_exceeds_the_recording_step_limit():
    recorder = Recorder(max_steps=2)
    recorder.feed(E.EV_KEY, E.KEY_A, 1, 1)
    with pytest.raises(ConfigurationError, match='limit'):
        recorder.finish(timestamp=1.1)
