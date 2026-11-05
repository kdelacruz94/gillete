import asyncio
import errno
import json
import socket
from types import SimpleNamespace

import pytest

from gillete import device_session as sessions, hardware, hid, service
from gillete.compile_onboard import CONTROL_IDS
from gillete.device_controls import Controls
from gillete.device_session import DeviceSession, SessionInterrupted, retryable_session_error
from gillete.devices import Device
from gillete.hardware import Snapshot
from gillete.focus import ProfileCoordinator
from gillete.model import MODELS
from gillete.onboard import Location
from gillete.profiles import Configuration, ProfileStore
from gillete.protocol import Command, DeviceStatusError, DeviceUnavailable, ProtocolError, checksum


@pytest.mark.parametrize('number', [errno.ENOENT, errno.ENODEV, errno.ENXIO, errno.EIO, errno.ETIMEDOUT,
                                   errno.EPIPE, errno.ENOTCONN, errno.ESHUTDOWN])
def test_only_device_io_wraps_os_availability_failures(number):
    original = OSError(number, 'arbitrary OS wording')
    with pytest.raises(DeviceUnavailable) as error:
        with hid.device_io():
            raise original
    assert error.value.__cause__ is original and retryable_session_error(error.value)
    # The same errno from a journal, executable or unrelated resource is not
    # silently promoted to a device retry elsewhere in the application.
    assert not retryable_session_error(original)


@pytest.mark.parametrize('error', [PermissionError(errno.EACCES, 'timeout in filename'),
                                 OSError(errno.EBUSY, 'busy'), BlockingIOError(errno.EAGAIN, 'locked'),
                                 OSError(errno.EBADF, 'programming error')])
def test_permission_ownership_and_invalid_fd_errors_remain_actionable(error):
    with pytest.raises(type(error)) as caught:
        with hid.device_io():
            raise error
    assert caught.value is error and not retryable_session_error(error)


@pytest.mark.parametrize('status, retry', [(1, True), (3, False), (4, True), (5, False), (0, False), (255, False)])
def test_firmware_status_is_classified_by_code_not_words(status, retry):
    error = DeviceStatusError(status)
    error.args = ('timeout disconnected busy',)  # Display wording is irrelevant.
    assert retryable_session_error(error) is retry


def test_recovery_failure_does_not_inherit_retry_permission_from_its_cause():
    try:
        raise DeviceUnavailable('radio timeout')
    except DeviceUnavailable as cause:
        error = ProtocolError('Settings recovery required at timeout.json')
        error.__cause__ = cause
    assert not retryable_session_error(error)
    assert not retryable_session_error(ProtocolError('Timeout game: unknown stored mapping'))
    assert not retryable_session_error(TimeoutError('Unrelated operation timed out'))
    assert retryable_session_error(SessionInterrupted('monitor went away'))


@pytest.mark.parametrize('mode, retry', [(bytes(2), True), (b'\x03\0', None), (b'\x02\0', False)])
def test_only_a_known_normal_mode_restart_can_reactivate(tmp_path, mode, retry):
    async def check():
        session = DeviceSession(SimpleNamespace(), ProfileCoordinator(Configuration()), tmp_path, None)
        session.io = SimpleNamespace(execute=lambda _: mode)
        if retry is None:
            await session.verify_mode()
        else:
            with pytest.raises(ProtocolError) as error:
                await session.verify_mode()
            assert retryable_session_error(error.value) is retry
    asyncio.run(check())


def test_disconnect_during_setting_rollback_identity_check_requires_recovery(tmp_path):
    writes = []
    def exchange(command):
        writes.append(command)
        raise DeviceUnavailable('Setter reply lost')
    def serial(): raise DeviceUnavailable('Receiver removed before rollback')
    io = SimpleNamespace(product=0xE8, device_serial=serial, _exchange=exchange)
    controls = Controls(io, SimpleNamespace(serial='test'), tmp_path)
    with pytest.raises(ProtocolError, match='Setting recovery required') as error:
        controls.write_checked(2, 0x30, 0xB0, b'\1\0', b'\1\1', b'\1\0')
    assert not retryable_session_error(error.value)
    assert isinstance(error.value.__cause__, DeviceUnavailable)
    assert len(writes) == 1
    document = json.loads(next(tmp_path.glob('setting-*.json')).read_text())
    assert document['status'] == 'prepared' and document['before'] == '0100'


def test_missing_receiver_or_interface_can_retry_but_ambiguous_or_unverified_transport_cannot(monkeypatch):
    device = Device(MODELS[0], 'Test', '2.4 GHz', 0xB4, '/test', 'test')
    monkeypatch.setattr(hardware, 'discover', lambda: [])
    with pytest.raises(DeviceUnavailable): hardware.transport(device)
    monkeypatch.setattr(hardware, 'discover', lambda: [device])
    with pytest.raises(DeviceUnavailable, match='interface'): hardware.transport(device)
    device.interfaces = [{'kind': 'hidraw', 'number': '00', 'path': '/dev/hidraw-test'}] * 2
    with pytest.raises(ProtocolError) as error: hardware.transport(device)
    assert not retryable_session_error(error.value)
    device.product_id = 0xE7
    with pytest.raises(ProtocolError) as error: hardware.transport(device)
    assert not retryable_session_error(error.value)


@pytest.mark.parametrize('operation', ['open', 'feature'])
def test_real_hid_boundary_converts_removed_device_errors(monkeypatch, operation):
    io = hid.ReadOnlyHID('/dev/hidraw-test', 0xB4)
    def removed(*_args): raise OSError(errno.ENODEV, 'No such device')
    if operation == 'open':
        monkeypatch.setattr(hid.os, 'open', removed)
        with pytest.raises(DeviceUnavailable): io.__enter__()
        assert io.fd is None
    else:
        io.fd = 123
        monkeypatch.setattr(hid.fcntl, 'ioctl', removed)
        with pytest.raises(DeviceUnavailable): io._exchange(Command(0, 0x84, bytes(2)))


@pytest.mark.parametrize('reply_kind', ['busy', 'stale'])
def test_reply_deadline_is_retryable_without_resending_a_setter(monkeypatch, reply_kind):
    io = hid.ReadOnlyHID('/dev/hidraw-test', 0xB4)
    io.fd = 123
    command = Command(0, 4, b'\3\0')
    reply = bytearray((command if reply_kind == 'busy' else Command(0, 0x84, bytes(2))).encode())
    reply[0] = 1 if reply_kind == 'busy' else 2
    reply[88] = checksum(reply)
    calls = []
    def ioctl(fd, operation, data, mutate):
        calls.append(operation)
        if operation == hid.feature_ioctl(6): return 91
        data[:] = b'\0' + reply
        return 91
    ticks = iter((0, .5, 1))
    monkeypatch.setattr(hid.fcntl, 'ioctl', ioctl)
    monkeypatch.setattr(hid.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(hid.time, 'sleep', lambda _: None)
    with pytest.raises(DeviceUnavailable, match='not resent'): io._exchange(command)
    assert calls.count(hid.feature_ioctl(6)) == 1 and calls.count(hid.feature_ioctl(7)) == 2


@pytest.mark.parametrize('number', [errno.EBUSY, errno.EACCES, errno.ENODEV])
def test_evdev_grab_distinguishes_another_remapper_from_permission_and_disconnect(tmp_path, monkeypatch, number):
    source = SimpleNamespace(info=SimpleNamespace(vendor=0x1532, product=0xB4), active_keys=lambda: [])
    def grab(): raise OSError(number, 'original OS detail')
    source.grab = grab
    monkeypatch.setattr(sessions, 'InputDevice', lambda _: source)
    device = Device(MODELS[0], 'Test', '2.4 GHz', 0xB4, '/test', 'test',
                    [{'kind': 'input', 'path': '/dev/input/event-test', 'number': '00'}])
    session = DeviceSession(device, ProfileCoordinator(Configuration()), tmp_path, None)
    with pytest.raises((OSError, ProtocolError)) as caught: session.open_inputs()
    assert retryable_session_error(caught.value) is (number == errno.ENODEV)
    assert ('Another application' in str(caught.value)) is (number == errno.EBUSY)
    assert session.evdev == [source]  # Run's cleanup still owns the opened handle.


def test_raw_hid_eof_is_typed_as_retryable_without_relying_on_error_text(tmp_path):
    async def check():
        session = DeviceSession(SimpleNamespace(), ProfileCoordinator(Configuration()), tmp_path, None)
        session.failure = asyncio.get_running_loop().create_future()
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        reader.setblocking(False)
        try:
            writer.send(b'')
            session.read_ready(reader.fileno())
            assert session.stop_requested.is_set()
            assert retryable_session_error(session.failure.result())
        finally:
            reader.close()
            writer.close()
    asyncio.run(check())


@pytest.mark.parametrize('retryable', [True, False])
def test_supervisor_retry_uses_outcome_and_waits_for_backoff_and_unambiguous_transport(tmp_path, monkeypatch, retryable):
    async def check():
        daemon = service.Daemon(ProfileStore(tmp_path / 'profiles.json'))
        model = MODELS[0]
        daemon.coordinator.available = daemon.sleep_monitor_ready = True
        daemon.requested.add(model)
        daemon.sessions[model] = SimpleNamespace(ready=False, retryable=retryable,
                error='No such device' if retryable else 'Invalid binding in profile Timeout', stop_requested=asyncio.Event())
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        daemon.tasks[model] = done
        mouse = SimpleNamespace(model=model)
        devices = [mouse]
        monkeypatch.setattr(service, 'discover', lambda: devices)
        created = []
        class Session:
            ready, error = False, ''
            def __init__(self, *_args):
                self.stop_requested = asyncio.Event()
                created.append(self)
            async def run(self): await self.stop_requested.wait()
        monkeypatch.setattr(service, 'DeviceSession', Session)
        await daemon.supervise_once()
        state = daemon.status()['devices'][model]
        assert state['requested'] is retryable and not created
        if not retryable:
            assert state['retry_in_ms'] == 0
            return
        assert 0 < state['retry_in_ms'] <= 5000
        await daemon.supervise_once()
        assert not created
        daemon.retry_at[model] = 0  # Advance past the deadline without a wall-clock sleep.
        devices.clear()
        await daemon.supervise_once()
        assert not created and daemon.errors[model] == 'Mouse not connected'
        devices.extend([mouse, mouse])
        await daemon.supervise_once()
        assert not created and 'exactly one' in daemon.errors[model]
        devices.pop()
        daemon.suspended = True
        await daemon.supervise_once()
        assert not created
        daemon.suspended = False
        await daemon.supervise_once()
        assert len(created) == 1
        created[0].stop_requested.set()
        await daemon.tasks[model]
    asyncio.run(check())


@pytest.mark.parametrize('outcome', ['cancelled', 'escaped'])
def test_unhandled_session_failure_never_retries_without_a_cleanup_outcome(tmp_path, monkeypatch, outcome):
    async def check():
        daemon = service.Daemon(ProfileStore(tmp_path / 'profiles.json'))
        model = MODELS[0]
        daemon.requested.add(model)
        daemon.sessions[model] = SimpleNamespace(ready=False, error='', retryable=True)
        done = asyncio.get_running_loop().create_future()
        if outcome == 'cancelled': done.cancel()
        else: done.set_exception(DeviceUnavailable('Unexpected escape from run'))
        daemon.tasks[model] = done
        monkeypatch.setattr(service, 'discover', lambda: [])
        await daemon.supervise_once()
        assert model not in daemon.requested and daemon.errors[model]
    asyncio.run(check())


class SimulatedMouse:
    product, serial, mode, awake = 0xB4, 'test-mouse', bytes(2), True

    def __init__(self):
        self.writes = []

    def __enter__(self): return self
    def __exit__(self, *_): pass
    def device_serial(self):
        if not self.awake: raise DeviceUnavailable('Mouse absent')
        return self.serial
    def execute(self, command):
        self.device_serial()
        assert (command.category, command.operation) == (0, 0x84)
        return self.mode
    def _exchange(self, command):
        self.device_serial()
        assert (command.category, command.operation) == (0, 4)
        self.writes.append(command.payload)
        self.mode = command.payload


def session_setup(tmp_path, monkeypatch):
    io = SimulatedMouse()
    device = Device(MODELS[0], 'Test', '2.4 GHz', io.product, '/test', 'test-mouse')
    snapshot = Snapshot(io.product, device.model, io.serial, 1, (1,), 1, set(CONTROL_IDS[device.model].values()),
                        {Location(1, c, l): bytes((1, c, 0)) + bytes.fromhex('0202001e000000')
                         for c in CONTROL_IDS[device.model].values() for l in (0, 1)}, {})
    def inspect(*_args):
        assert io.mode == bytes(2), 'Recovery must precede inspection and new ownership'
        io.device_serial()
        return snapshot
    class Output:
        def __init__(self, *_args): self.keymap = SimpleNamespace(watch=self.watch)
        async def watch(self): await asyncio.Future()
        async def prepare_keyboard(self): pass
        async def restore_keyboard(self): pass
        def close(self): pass
    monkeypatch.setattr(sessions, 'inspect', inspect)
    monkeypatch.setattr(sessions, 'transport', lambda *_: io)
    monkeypatch.setattr(sessions, 'UInputOutput', Output)
    monkeypatch.setattr(DeviceSession, 'open_inputs', lambda *_: None)
    coordinator = ProfileCoordinator(Configuration())
    coordinator.available = True
    return io, device, coordinator


async def ready(session):
    async with asyncio.timeout(1):
        while not session.ready:
            await asyncio.sleep(.001)


def test_reconnected_mouse_recovers_old_mode_before_new_inspection_and_grab(tmp_path, monkeypatch):
    async def check():
        io, device, coordinator = session_setup(tmp_path, monkeypatch)
        first = DeviceSession(device, coordinator, tmp_path, None)
        task = asyncio.create_task(first.run())
        await ready(first)
        io.awake = False
        first.fail(DeviceUnavailable('Receiver removed'))
        await asyncio.wait_for(task, 1)
        assert first.retryable and 'Mode recovery retained' in first.error
        journal = next(tmp_path.glob('mode-*.json'))
        assert json.loads(journal.read_text())['status'] == 'driver-mode-active'
        io.awake = True
        second = DeviceSession(device, coordinator, tmp_path, None)
        task = asyncio.create_task(second.run())
        await ready(second)
        assert json.loads(journal.read_text())['status'] == 'normal-mode-restored'
        assert not second.engine.macros.jobs and not second.engine.ledger.holders
        assert io.writes == [b'\3\0', bytes(2), b'\3\0']
        second.stop_requested.set()
        await asyncio.wait_for(task, 1)
        assert io.mode == bytes(2) and not second.error
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['identity', 'journal', 'output'])
def test_recovery_or_resource_failure_vetoes_retry_after_a_transient_disconnect(tmp_path, monkeypatch, failure):
    async def check():
        io, device, coordinator = session_setup(tmp_path, monkeypatch)
        session = DeviceSession(device, coordinator, tmp_path, None)
        task = asyncio.create_task(session.run())
        await ready(session)
        if failure == 'identity':
            io.serial = 'different-mouse'
        elif failure == 'journal':
            import gillete.driver_mode as driver_mode
            def fail_record(*_): raise OSError(errno.ENOSPC, 'Disk full at timeout.json')
            monkeypatch.setattr(driver_mode, 'durable_json', fail_record)
        else:
            def fail_close(): raise RuntimeError('Output close timeout')
            session.output.close = fail_close
        session.fail(DeviceUnavailable('Receiver link interrupted'))
        await asyncio.wait_for(task, 1)
        assert not session.retryable and session.error
        if failure != 'output':
            journal = next(tmp_path.glob('mode-*.json'))
            assert json.loads(journal.read_text())['status'] == 'driver-mode-active'
        if failure == 'identity': assert io.writes == [b'\3\0']
        else: assert io.mode == bytes(2)
    asyncio.run(check())
