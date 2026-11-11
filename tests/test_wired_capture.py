from copy import deepcopy
from pathlib import Path
import struct

import pytest

from gillete import wired_capture as capture
from gillete import wired_probe as wired
from gillete.driver_mode import ModeLease
from gillete.hardware import read_journal
from gillete.hid import CONFIG_INTERFACE, ReadOnlyHID
from gillete.onboard import durable_json
from gillete.protocol import Command, ProtocolError
from test_wired_probe import Mouse, fake_sysfs


@pytest.fixture
def environment(tmp_path, monkeypatch):
    sysfs, device = fake_sysfs(tmp_path)
    monkeypatch.setattr(wired, 'discover', lambda *_: [device])
    mouse = Mouse()
    monkeypatch.setattr(wired, 'WiredQueryHID', lambda _: mouse)
    report_path = tmp_path / 'inspection.json'
    report = wired.run(report_path, query=True, sysfs=sysfs)
    assert report['status'] == 'read-only-state-verified'
    monkeypatch.setattr(capture, 'discover', lambda: [device])
    monkeypatch.setattr(wired, 'descriptors', lambda _: deepcopy(report['descriptors']))
    directory = tmp_path / 'proposal'
    capture.prepare(report_path, directory)
    mouse.writes = []
    mouse.lose_ack = False
    def exchange(_io, command):
        if command.operation < 0x80:
            mouse.writes.append(command)
            mouse.mode = command.payload
            if mouse.lose_ack:
                mouse.lose_ack = False
                raise TimeoutError('Mode applied but reply lost')
            return command.payload
        if (command.category, command.operation) == (4, 0x85) and hasattr(mouse, 'dpi'):
            return mouse.dpi
        return Mouse._exchange(mouse, command)
    monkeypatch.setattr(ReadOnlyHID, '_exchange', exchange)
    monkeypatch.setattr(ReadOnlyHID, '__enter__', lambda io: io)
    monkeypatch.setattr(ReadOnlyHID, '__exit__', lambda *_: None)
    monkeypatch.setattr(capture, 'socket_path', lambda: tmp_path / 'absent.sock')
    return sysfs, device, mouse, report, directory


def test_read_only_preparation_and_stale_transport_do_not_enable_normal_wired_support(environment, monkeypatch):
    _, device, mouse, report, directory = environment
    assert capture.validate_inspection(report) == report['routes'][0]['before']
    assert not mouse.writes and not (directory / 'run').exists() and 0xE7 not in CONFIG_INTERFACE
    with pytest.raises(FileExistsError): capture.prepare(directory.parent / 'inspection.json', directory)
    monkeypatch.setattr(capture, 'discover', lambda: [])
    with pytest.raises(ProtocolError, match='missing or changed'): capture.run(directory)
    assert not mouse.writes


@pytest.mark.parametrize('problem', ['unverified', 'changed', 'mode', 'descriptor', 'route', 'writes', 'version'])
def test_unverified_inspection_never_authorizes_mode_changes(environment, problem):
    _, _, mouse, report, _ = environment
    report = deepcopy(report)
    if problem == 'unverified': report['status'] = 'route-failed'
    elif problem == 'changed': report['routes'][0]['state_unchanged'] = False
    elif problem == 'mode': report['routes'][0]['before']['mode'] = '0300'
    elif problem == 'descriptor': report['descriptors']['01']['raw'] = ''
    elif problem == 'route': report['read_only_route'] = '02'
    elif problem == 'writes': report['writes_enabled'] = True
    else: report['version'] = True
    with pytest.raises(ProtocolError): capture.validate_inspection(report)
    assert not mouse.writes


@pytest.mark.parametrize('command', [Command(2, 0x0C, bytes(10)), Command(4, 5, bytes(7)),
    Command(6, 8, bytes(6)), Command(0, 4, b'\1\0'), Command(0, 0x81, bytes(2)),
    Command(2, 0x8C, bytes(10))])
def test_capture_transport_rejects_other_setters_and_unverified_getter_shapes(environment, command):
    _, _, mouse, report, directory = environment
    journal = directory / 'mode.json'
    before = capture.validate_inspection(report)
    io = capture.ModeCaptureHID('/dev/hidraw-test', journal, before['serial'])
    durable_json(journal, {'kind': 'driver-mode', 'product': 0xE7, 'serial': before['serial'], 'before': '0000'})
    with pytest.raises(ProtocolError): io._exchange(command)
    assert not mouse.writes


def test_lost_mode_ack_restores_through_real_lease_and_preserves_settings(environment):
    _, device, mouse, report, directory = environment
    root = directory / 'run'; root.mkdir()
    mouse.lose_ack = True
    with pytest.raises(TimeoutError, match='reply lost'):
        with capture.capture_transport(device, report, root) as io:
            ModeLease(io, root / 'mode.json').enter()
    assert [c.payload for c in mouse.writes] == [b'\3\0', b'\0\0']
    assert mouse.mode == b'\0\0'
    assert read_journal(root / 'mode.json')['status'] == 'normal-mode-restored'
    verified = read_journal(root / 'verification.json')
    assert verified['normal_mode_verified'] and verified['stored_state_unchanged']


@pytest.mark.parametrize('problem', ['missing', 'serial', 'product', 'before', 'version', 'status'])
def test_mode_setter_requires_matching_durable_lease_before_submission(environment, problem):
    _, _, mouse, report, directory = environment
    expected = capture.validate_inspection(report)
    path = directory / 'mode.json'
    document = {'version': 1, 'kind': 'driver-mode', 'product': 0xE7,
                'serial': expected['serial'], 'before': '0000', 'status': 'prepared'}
    if problem != 'missing':
        document[problem] = {'serial': 'another', 'product': 0xE8, 'before': '0300',
                             'version': True, 'status': 'normal-mode-restored'}[problem]
        durable_json(path, document)
    io = capture.ModeCaptureHID('/dev/hidraw-test', path, expected['serial'])
    with pytest.raises((OSError, ProtocolError)): io._exchange(Command(0, 4, b'\3\0'))
    assert not mouse.writes


def test_external_dpi_change_is_reported_and_preserved_without_a_setting_repair(environment):
    _, device, mouse, report, directory = environment
    root = directory / 'run'; root.mkdir()
    with pytest.raises(ProtocolError, match='saved state changed'):
        with capture.capture_transport(device, report, root) as io:
            with ModeLease(io, root / 'mode.json'):
                mouse.dpi = bytes.fromhex('0104b004b00000')
    verification = read_journal(root / 'verification.json')
    assert verification['normal_mode_verified'] and not verification['stored_state_unchanged']
    assert verification['after']['settings']['dpi'] == mouse.dpi.hex()
    assert [c.payload for c in mouse.writes] == [b'\3\0', b'\0\0']


def test_stale_snapshot_prevents_lease_creation_or_settings_repair(environment):
    _, device, mouse, report, directory = environment
    root = directory / 'run'; root.mkdir()
    mouse.mode = b'\3\0'
    with pytest.raises(ProtocolError):
        with capture.capture_transport(device, report, root): raise AssertionError('Stale state admitted')
    assert not mouse.writes and not (root / 'mode.json').exists()
    assert mouse.mode == b'\3\0'


@pytest.mark.parametrize('finish', ['user-report', 'record-limit'])
def test_real_capture_loop_uses_guarded_route_and_stop_file_then_verifies_restore(environment, monkeypatch, finish):
    sysfs, device, mouse, report, directory = environment
    module = capture.driver_capture
    original_open, original_close = module.os.open, module.os.close
    original_ioctl = module.fcntl.ioctl
    fds = {node['path']: 10000 + int(node['number']) for node in device.interfaces if node['kind'] == 'hidraw'}
    flushed, frames = set(), []
    def open_node(path, flags, *args):
        return fds[str(path)] if str(path) in fds else original_open(path, flags, *args)
    def close_node(fd):
        if fd not in fds.values(): return original_close(fd)
    def ioctl(fd, code, data, *args):
        if fd in fds.values(): data[:] = struct.pack('IHH', 3, 0x1532, 0xE7); return 0
        return original_ioctl(fd, code, data, *args)
    def read_node(fd, _length):
        if fd not in flushed:
            flushed.add(fd); raise BlockingIOError
        frames.append(struct.pack('<I', len(frames) + 1) + bytes(4))
        if finish == 'user-report':
            durable_json(directory / 'run/user-report.json', {'version': 1, 'sequence_completed': True})
        return frames[-1]
    monkeypatch.setattr(module.os, 'open', open_node)
    monkeypatch.setattr(module.os, 'close', close_node)
    monkeypatch.setattr(module.fcntl, 'ioctl', ioctl)
    monkeypatch.setattr(module.os, 'read', read_node)
    monkeypatch.setattr(module.select, 'select', lambda *_: ([fds['/dev/hidraw10']], [], []))
    monkeypatch.setattr(module, 'Path', lambda value: sysfs / 'class/hidraw' if value == '/sys/class/hidraw' else Path(value))
    if finish == 'user-report': capture.run(directory)
    else:
        with pytest.raises(ProtocolError, match='Capture limit reached'): capture.run(directory)
    root = directory / 'run'
    assert len(read_journal(root / 'capture.json')['events']) == (1 if finish == 'user-report' else 4096)
    verification = read_journal(root / 'verification.json')
    assert verification['normal_mode_verified'] and verification['stored_state_unchanged']
    assert read_journal(root / 'mode.json')['status'] == 'normal-mode-restored'
    assert [c.payload for c in mouse.writes] == [b'\3\0', b'\0\0']
    assert 0xE7 not in CONFIG_INTERFACE
    capture.run(directory, recover=True)
    assert read_journal(root / 'recovery.json')['stored_state_unchanged']
    assert len(mouse.writes) == 2  # Idempotent recovery did not resend a setter.


def interrupted_lease(environment):
    _, device, mouse, report, directory = environment
    root = directory / 'run'; root.mkdir()
    expected = capture.validate_inspection(report)
    durable_json(root / 'mode.json', {'version': 1, 'kind': 'driver-mode', 'product': 0xE7,
        'serial': expected['serial'], 'before': '0000', 'status': 'driver-mode-active'})
    mouse.mode = b'\3\0'
    return device, mouse, report, directory


def test_recovery_reopens_replugged_route_and_checks_identity_before_restoring(environment, monkeypatch):
    device, mouse, report, directory = interrupted_lease(environment)
    device.usb_path += '-replugged'
    current = deepcopy(report['descriptors'])
    for number, entry in current.items():
        entry['node'] = f'/dev/hidraw{int(number) + 30}'
        entry['usb_address']['devnum'] = '24'
    monkeypatch.setattr(wired, 'descriptors', lambda _: deepcopy(current))
    with pytest.raises(ProtocolError, match='missing or changed'): capture.run(directory)
    assert mouse.mode == b'\3\0' and not mouse.writes
    opened = []
    def enter(io):
        opened.append(io.path)
        return io
    monkeypatch.setattr(ReadOnlyHID, '__enter__', enter)
    capture.run(directory, recover=True)
    assert opened == ['/dev/hidraw30']
    assert [c.payload for c in mouse.writes] == [b'\0\0']
    assert read_journal(directory / 'run/recovery.json')['stored_state_unchanged']


@pytest.mark.parametrize('changed', ['firmware', 'serial', 'descriptor'])
def test_recovery_rejects_another_identity_without_a_mode_set(environment, monkeypatch, changed):
    _, mouse, report, directory = interrupted_lease(environment)
    exchange = ReadOnlyHID._exchange
    def replaced(io, command):
        pair = command.category, command.operation
        if changed == 'firmware' and pair == (0, 0x81): return bytes.fromhex('01020000')
        if changed == 'serial' and pair == (0, 0x82): return b'another-unit' + bytes(10)
        return exchange(io, command)
    monkeypatch.setattr(ReadOnlyHID, '_exchange', replaced)
    if changed == 'descriptor':
        current = deepcopy(report['descriptors'])
        current['01']['raw'] += '00'
        monkeypatch.setattr(wired, 'descriptors', lambda _: current)
    with pytest.raises(ProtocolError): capture.run(directory, recover=True)
    assert not mouse.writes and mouse.mode == b'\3\0'
    assert read_journal(directory / 'run/mode.json')['status'] == 'driver-mode-active'


def test_completed_lease_cannot_restore_a_later_unowned_driver_mode(environment):
    _, mouse, _, directory = interrupted_lease(environment)
    path = directory / 'run/mode.json'
    document = read_journal(path)
    document['status'] = 'normal-mode-restored'
    durable_json(path, document)
    with pytest.raises(ProtocolError, match='completed lease cannot change modes'):
        capture.run(directory, recover=True)
    assert not mouse.writes and mouse.mode == b'\3\0'
