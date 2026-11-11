import json

import pytest

from gillete import firmware_probe, polling_reads
from gillete.compile_onboard import CONTROL_IDS
from gillete.devices import Device
from gillete.hid import READ_COMMANDS, ReadOnlyHID
from gillete.model import MODELS
from gillete.protocol import Command, DeviceStatusError, ProtocolError
from gillete.settings import POLLING, query as setting_query


class PollingDevice:
    product = 0xE8

    def __init__(self, *, assigned=(1, 3), failure=None, changed=False):
        self.assigned, self.failure, self.changed = assigned, failure, changed
        self.commands, self.seen = [], {}

    def execute(self, command):
        self.commands.append(command)
        pair = command.category, command.operation
        assert command.operation >= 0x80, 'No setter is permitted in polling diagnostics'
        if pair == (0, 0x81): return b'\1\1'
        if pair == (0, 0x84): return bytes(2)
        if pair == (0, 0x82): return b'test-v3' + bytes(15)
        if pair == (5, 0x80): return bytes((len(self.assigned),))
        if pair == (5, 0x81): return bytes((5, *self.assigned))
        if pair == (5, 0x84): return bytes((self.assigned[0],))
        if pair == (2, 0x84): return bytes((25, *CONTROL_IDS[MODELS[1]].values()))
        if pair == (2, 0x8C): return command.payload[:2] + b'\1' + bytes.fromhex('0202001e000000')
        if pair == (4, 0x85): return bytes.fromhex('01064006400000')
        if pair == (4, 0x86): return bytes.fromhex('01010101064006400000') + bytes(28)
        if pair == (0, 0x85): return b'\1'
        assert pair in ((0, 0x8E), (0, 0xC0)), 'Unexpected query'
        profile = command.payload[0]
        assert profile in self.assigned, 'Never query an unassigned bank'
        self.seen[pair, profile] = self.seen.get((pair, profile), 0) + 1
        if self.failure:
            value = self.failure(command, self.seen[pair, profile])
            if isinstance(value, Exception): raise value
            if value is not None: return value
        code = 1 if pair[1] == 0x8E else 8
        if self.changed and self.seen[pair, profile] > 1: code = 2
        return bytes((profile, code))

    def __enter__(self): return self
    def __exit__(self, *_): pass


def document():
    return {'queries': [], 'sections': {}, 'state_unchanged': None}


def candidates(io):
    return [(c.operation, c.payload.hex()) for c in io.commands if c.operation in (0x8E, 0xC0)]


def test_distinct_getter_encodings_cannot_be_confused_with_ordinary_polling_or_enable_new_settings():
    ordinary = setting_query('polling')
    assert (ordinary.category, ordinary.operation, ordinary.payload) == (0, 0x85, b'\0')
    assert polling_reads.query('profile', 3).encode()[5:10] == bytes.fromhex('02008e0300')
    assert polling_reads.query('high-speed', 3).encode()[5:10] == bytes.fromhex('0200c00300')
    assert POLLING == {125: 8, 500: 2, 1000: 1}
    assert (0, 0x8E) not in READ_COMMANDS and (0, 0xC0) not in READ_COMMANDS
    # Code1 means 1000 Hz in one family and 8000 Hz in the other.
    assert polling_reads.decode('profile', 3, b'\3\1')['nominal_hz'] == 1000
    assert polling_reads.decode('high-speed', 3, b'\3\1')['nominal_hz'] == 8000


@pytest.mark.parametrize('route,expected', [
    ('profile', {1: 1000, 2: 500, 3: 333, 4: 250, 5: 200, 8: 125, 10: 100}),
    ('high-speed', {1: 8000, 2: 4000, 4: 2000, 8: 1000, 16: 500, 32: 250, 64: 125}),
])
def test_all_byte_codes_preserve_unknown_values_without_defaulting_to_8000(route, expected):
    for code in range(256):
        raw = bytes((1, code))
        result = polling_reads.decode(route, 1, raw)
        assert result['raw'] == raw.hex() and result['code'] == code
        assert result['nominal_hz'] == expected.get(code)
        assert result['status'] == ('recognized-code' if code in expected else 'unknown-code')


@pytest.mark.parametrize('product,command', [
    (0xB4, Command(0, 0xC0, b'\1\0')), (0xE7, Command(0, 0xC0, b'\1\0')),
    (0xE8, Command(0, 0x40, b'\1\1')), (0xE8, Command(0, 0x0E, b'\1\1')),
    (0xE8, Command(0, 0xC0, b'\0\0')), (0xE8, Command(0, 0xC0, b'\6\0')),
    (0xE8, Command(0, 0xC0, b'\1\1')), (0xE8, Command(0, 0xC0, b'\1')),
    (0xE8, Command(0, 0xC0, b'\1\0', transaction=0x3F)),
])
def test_candidate_transport_rejects_setters_routes_and_unbounded_selectors_before_exchange(monkeypatch, product, command):
    exchanges = []
    monkeypatch.setattr(ReadOnlyHID, '_exchange', lambda self, command: exchanges.append(command))
    with pytest.raises(ProtocolError): firmware_probe.FirmwareQueryHID('/dev/hidraw999', product).execute(command)
    assert not exchanges


def test_only_opt_in_adapter_accepts_exact_candidate_getters(monkeypatch):
    exchanges = []
    monkeypatch.setattr(ReadOnlyHID, '_exchange', lambda self, command: exchanges.append(command) or b'\1\10')
    for route in ('profile', 'high-speed'):
        command = polling_reads.query(route, 1)
        with pytest.raises(ProtocolError): ReadOnlyHID('/dev/hidraw999', 0xE8).execute(command)
        assert firmware_probe.FirmwareQueryHID('/dev/hidraw999', 0xE8).execute(command) == b'\1\10'
    assert len(exchanges) == 2


def test_read_only_collection_uses_assigned_slots_rechecks_values_and_never_admits_a_write():
    io, report = PollingDevice(), document()
    firmware_probe.collect(io, MODELS[1], report, ['polling'])
    assert report['status'] == 'read-complete' and report['state_unchanged']
    section = report['sections']['polling']
    assert section['values_unchanged'] and section['before'] == section['after']
    assert not any(section[name] for name in ('dispatch_verified', 'cadence_verified', 'writes_verified'))
    assert candidates(io) == [(0x8E, '0100'), (0x8E, '0300'), (0xC0, '0100'), (0xC0, '0300')] * 2
    assert {q['phase'] for q in report['queries']} == {'before', 'polling', 'after', 'polling-recheck'}
    assert report['before']['settings']['polling'] == '01'
    assert report['before']['firmware'] == '0101'


@pytest.mark.parametrize('status', [3, 5])
def test_clean_rejection_stops_the_family_and_is_never_retried(status):
    io = PollingDevice(failure=lambda command, count: DeviceStatusError(status) if command.operation == 0x8E else None)
    result = polling_reads.observe(io, io.assigned)
    polling_reads.recheck(io, result)
    assert result['status'] == 'partially-queried' and result['values_unchanged']
    assert result['before'][0]['device_status'] == status
    assert candidates(io) == [(0x8E, '0100'), (0xC0, '0100'), (0xC0, '0300'), (0xC0, '0100'), (0xC0, '0300')]


@pytest.mark.parametrize('error', [TimeoutError('asleep'), PermissionError('access lost'),
    DeviceStatusError(4), ProtocolError('checksum mismatch')])
def test_uncertain_candidate_failure_stops_all_candidates_without_retry_but_keeps_baseline_verification(error):
    io = PollingDevice(failure=lambda *_: error)
    report = document()
    firmware_probe.collect(io, MODELS[1], report, ['polling'])
    assert report['state_unchanged'] and report['sections']['polling']['status'] == 'stopped'
    assert candidates(io) == [(0x8E, '0100')]
    assert report['sections']['polling']['values_unchanged'] is None


def test_unknown_code_retained_and_rechecked_without_support_claim():
    io = PollingDevice(failure=lambda command, count: bytes((command.payload[0], 255)))
    result = polling_reads.observe(io, (1,))
    polling_reads.recheck(io, result)
    assert result['values_unchanged']
    assert all(e['raw'] == '01ff' and e['status'] == 'unknown-code' and e['nominal_hz'] is None for e in result['before'])
    assert not result['cadence_verified'] and not result['dispatch_verified']


@pytest.mark.parametrize('raw', [b'', b'\1', b'\1\10\0', b'\2\10'])
def test_malformed_or_wrong_selector_replies_stop_candidates_and_retain_raw_bytes(raw):
    io = PollingDevice(failure=lambda *_: raw)
    result = polling_reads.observe(io, (1,))
    assert result['status'] == 'stopped' and result['before'][0]['raw'] == raw.hex()
    assert len(candidates(io)) == 1


def test_candidate_value_change_is_not_hidden_by_unchanged_ordinary_settings():
    io, report = PollingDevice(changed=True), document()
    firmware_probe.collect(io, MODELS[1], report, ['polling'])
    assert report['before'] == report['after']
    assert report['status'] == 'state-difference-observed' and report['state_unchanged'] is False
    assert report['sections']['polling']['values_unchanged'] is False


def test_failed_recheck_is_not_treated_as_unchanged_and_is_not_retried():
    io, report = PollingDevice(failure=lambda command, count: TimeoutError('reply lost') if count == 2 else None), document()
    firmware_probe.collect(io, MODELS[1], report, ['polling'])
    assert report['status'] == 'verification-unavailable'
    assert report['sections']['polling']['values_unchanged'] is None
    assert len(candidates(io)) == 5


def test_polling_section_rejects_other_transports_before_discovery_or_report_creation(tmp_path, monkeypatch):
    def unexpected(): raise AssertionError('No discovery needed for a disallowed product')
    monkeypatch.setattr(firmware_probe, 'discover', unexpected)
    for product in (0xB4, 0xE7):
        with pytest.raises(ProtocolError, match='receiver route'):
            firmware_probe.run(product, tmp_path / 'not-created.json', ['polling'])
    assert not list(tmp_path.iterdir())


def test_changed_baseline_firmware_prevents_polling_recheck():
    class ChangedFirmware(PollingDevice):
        def execute(self, command):
            raw = super().execute(command)
            if (command.category, command.operation) == (0, 0x81) and self.seen:
                return b'\1\2'
            return raw
    io, report = ChangedFirmware(), document()
    firmware_probe.collect(io, MODELS[1], report, ['polling'])
    assert report['status'] == 'state-difference-observed' and not report['state_unchanged']
    assert len(candidates(io)) == 4 and not report['sections']['polling']['after']


def test_explicit_polling_cli_writes_private_new_only_report_without_terminal_identity(tmp_path, monkeypatch, capsys):
    io = PollingDevice()
    device = Device(MODELS[1], 'Test V3', '2.4 GHz', 0xE8, '/test', '',
                    [{'kind': 'hidraw', 'path': '/dev/hidraw999', 'number': '03'}])
    monkeypatch.setattr(firmware_probe, 'discover', lambda: [device])
    monkeypatch.setattr(firmware_probe, 'FirmwareQueryHID', lambda *_: io)
    path = tmp_path / 'private/report.json'
    args = ['--product', '00e8', '--sections', 'polling', '--output', str(path)]
    assert firmware_probe.main(args) == 0
    saved = json.loads(path.read_text())
    assert set(saved['sections']) == {'polling'} and saved['before']['firmware'] == '0101'
    assert saved['sections']['polling']['values_unchanged']
    assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o777 == 0o700
    summary = capsys.readouterr().out
    assert 'effective rate unverified' in summary and 'test-v3' not in summary
    before, calls = path.read_bytes(), len(io.commands)
    with pytest.raises(FileExistsError): firmware_probe.run(0xE8, path, ['polling'])
    assert path.read_bytes() == before and len(io.commands) == calls
