import json

import pytest

from gillete import firmware_probe
from gillete.compile_onboard import CONTROL_IDS
from gillete.devices import Device
from gillete.firmware_probe import Probe, collect, dpi_selectors
from gillete.model import MODELS
from gillete.protocol import Command, DeviceStatusError, ProtocolError


class DeviceReads:
    product = 0xB4

    def __init__(self, *, mode=bytes(2), macro_error=None, selector_echo=True, drift=False):
        self.mode, self.macro_error, self.selector_echo, self.drift = mode, macro_error, selector_echo, drift
        self.queried_macro = False
        self.commands = []

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def execute(self, command):
        self.commands.append(command)
        pair, data = (command.category, command.operation), command.payload
        assert command.operation >= 0x80, 'Only getter commands are permitted'
        if pair == (0, 0x84): return self.mode
        if pair == (0, 0x82): return b'test-mouse' + bytes(12)
        if pair == (5, 0x80): return b'\1'
        if pair == (5, 0x81): return b'\1\1'
        if pair == (2, 0x84): return bytes((21, *CONTROL_IDS[MODELS[0]].values()))
        if pair == (2, 0x8C): return data[:2] + b'\1' + bytes.fromhex('0202001e000000')
        if pair == (4, 0x85):
            selector = data[0] if self.selector_echo else 1
            dpi = 900 if self.drift and self.queried_macro else 800
            return bytes((selector,)) + dpi.to_bytes(2, 'big') * 2 + bytes(2)
        if pair == (4, 0x86): return bytes.fromhex('01010101032003200000') + bytes(28)
        if pair == (0, 0x85): return b'\1'
        if pair[0] == 6:
            self.queried_macro = True
            if self.macro_error:
                raise self.macro_error
            if pair[1] == 0x8E: return b'\0\x10' + (4096).to_bytes(4, 'big') * 2 + bytes(4)
            if pair[1] == 0x80: return bytes(2)
        raise AssertionError('Unexpected query')


def report():
    return {'queries': [], 'sections': {}, 'state_unchanged': None}


def test_read_only_probe_compares_stored_and_active_bindings_and_rejects_playback_or_temporary_write_claims():
    io, document = DeviceReads(), report()
    collect(io, MODELS[0], document, ['macros', 'dpi'], include_data=True)
    assert document['status'] == 'read-complete' and document['state_unchanged']
    assert len(document['before']['records']) == 84
    assert document['sections']['macros']['count'] == 0
    assert not document['sections']['macros']['zero_reference_resolved']
    assert not document['sections']['dpi']['temporary_writes_verified']
    assert document['sections']['dpi']['selectors']['0']['dpi'] == [800, 800]


@pytest.mark.parametrize('failure', [DeviceStatusError(5), DeviceStatusError(3), TimeoutError('Mouse asleep')])
def test_macro_rejection_stops_that_family_and_preserves_its_reason_without_followup_memory_reads(failure):
    io, document = DeviceReads(macro_error=failure), report()
    collect(io, MODELS[0], document, ['macros'], include_data=True)
    assert document['state_unchanged']
    assert document['sections']['macros']['status'] == 'stopped'
    assert document['sections']['macros']['error'] == str(failure)
    assert [(c.category, c.operation) for c in io.commands if c.category == 6] == [(6, 0x8E)]


def test_driver_mode_and_asleep_preflight_prevent_candidate_queries():
    io, document = DeviceReads(mode=b'\3\0'), report()
    collect(io, MODELS[0], document, ['macros', 'dpi'])
    assert document['status'] == 'preflight-failed' and len(io.commands) == 1
    class Asleep(DeviceReads):
        def execute(self, command):
            self.commands.append(command)
            raise DeviceStatusError(4)
    io, document = Asleep(), report()
    collect(io, MODELS[0], document, ['macros', 'dpi'])
    assert document['status'] == 'preflight-failed' and len(io.commands) == 1
    assert not document['sections'] and document['state_unchanged'] is None


def test_selector_echo_and_external_state_changes_are_not_misreported_as_verified_support():
    with pytest.raises(ProtocolError, match='echo'):
        dpi_selectors(DeviceReads(selector_echo=False))
    document = report()
    collect(DeviceReads(drift=True), MODELS[0], document, ['macros'])
    assert document['status'] == 'state-difference-observed' and not document['state_unchanged']


def test_probe_reserves_verification_budget_and_enforces_time_limit(monkeypatch):
    io, document = DeviceReads(), report()
    probe = Probe(io, document, max_requests=3)
    probe.reserve = 1
    probe.execute(Command(0, 0x84, bytes(2)))
    probe.execute(Command(0, 0x84, bytes(2)))
    with pytest.raises(ProtocolError, match='limit'):
        probe.execute(Command(0, 0x84, bytes(2)))
    probe.reserve = 0
    probe.execute(Command(0, 0x84, bytes(2)))
    assert len(io.commands) == 3
    probe = Probe(io, report())
    monkeypatch.setattr(firmware_probe.time, 'monotonic', lambda: probe.deadline + 1)
    with pytest.raises(ProtocolError, match='limit'):
        probe.execute(Command(0, 0x84, bytes(2)))
    assert len(io.commands) == 3


def test_private_report_is_new_only_and_terminal_output_omits_identity(monkeypatch, tmp_path, capsys):
    device = Device(MODELS[0], 'Test', '2.4 GHz', 0xB4, '/test', '',
                    [{'kind': 'hidraw', 'path': '/dev/hidraw999', 'number': '00'}])
    monkeypatch.setattr(firmware_probe, 'discover', lambda: [device])
    io = DeviceReads()
    monkeypatch.setattr(firmware_probe, 'FirmwareQueryHID', lambda *_: io)
    path = tmp_path / 'private' / 'probe.local.json'
    assert firmware_probe.main(['--product', '00b4', '--output', str(path)]) == 0
    assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text())['before']['serial'] == 'test-mouse'
    assert 'test-mouse' not in capsys.readouterr().out
    calls, original = len(io.commands), path.read_bytes()
    with pytest.raises(FileExistsError):
        firmware_probe.run(0xB4, path, ['macros'])
    assert len(io.commands) == calls and path.read_bytes() == original
