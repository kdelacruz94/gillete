import json
import signal
from types import SimpleNamespace

import pytest

from gillete import dpi_probe as probe
from gillete import dpi_sensor_probe as sensor
from gillete import dpi_replug_probe as replug
from gillete import dpi_driver_probe as driverdpi
from gillete.compile_onboard import CONTROL_IDS
from gillete.devices import PRODUCTS
from gillete.protocol import DeviceStatusError, DeviceUnavailable, ProtocolError
from gillete.settings import SPECS, Stages


class Mouse:
    """Independent, aliased or unresponsive storage; never opens real hardware."""
    def __init__(self, product=0xB4, *, alias=False):
        self.product, self.alias = product, alias
        self.serial, self.mode, self.firmware = 'dpi-test', bytes(2), b'\1\2'
        self.assigned, self.active = ((1,) if product == 0xB4 else (1, 3)), 1
        self.controls = tuple(CONTROL_IDS[PRODUCTS[product][0]].values())
        self.values = {'stages': bytes.fromhex('0101020104b004b0aabb0203200320ccdd') + bytes(21),
                       'dpi': bytes.fromhex('01070807080000'), 'polling': b'\1'}
        self.zero = b'\0' + self.values['dpi'][1:]
        self.writes, self.reads = [], []
        self.binding_change, self.reply_flag = False, 0
        self.fail_at, self.sleep_after_write, self.ignore_setters = set(), False, False
        self.awake = True

    def __enter__(self): return self
    def __exit__(self, *_): pass
    def device_serial(self):
        if not self.awake: raise DeviceUnavailable('Mouse unavailable')
        return self.serial
    def require_normal_mode(self):
        self.device_serial()
        if self.mode != bytes(2): raise ProtocolError('Normal mode required')

    def read_binding_record(self, bank, control, layer):
        function = bytes.fromhex('05020000000000')  # Opaque old macro references stay raw.
        if self.binding_change and bank == self.assigned[-1]:
            function = bytes.fromhex('0202001e000000')
        return bytes((bank, control, self.reply_flag)) + function

    def execute(self, command):
        self.device_serial()
        self.reads.append(command)
        pair, data = (command.category, command.operation), command.payload
        if pair == (0, 0x84): return self.mode
        if pair == (0, 0x81): return self.firmware
        if pair == (5, 0x80): return bytes((len(self.assigned),))
        if pair == (5, 0x81): return bytes((1 if self.product == 0xB4 else 5, *self.assigned))
        if pair == (5, 0x84): return bytes((self.active,))
        if pair == (2, 0x84): return bytes((len(self.controls), *self.controls))[:len(data)]
        if pair == (2, 0x8C): return self.read_binding_record(*data[:3])
        if pair == (4, 0x85):
            assert data in (bytes(7), b'\1' + bytes(6))
            return self.zero if data[0] == 0 else self.values['dpi']
        for name, (category, _, getter, payload) in SPECS.items():
            if pair == (category, getter):
                assert data == payload
                return self.values[name]
        raise AssertionError('Unexpected query')

    def _exchange(self, command):
        self.device_serial()
        self.writes.append(command)
        pair, raw = (command.category, command.operation), command.payload
        assert pair in {(4, 5), (4, 6), (0, 5)}, 'No mode, profile or binding setters allowed'
        if not self.ignore_setters:
            if pair == (4, 5):
                assert len(raw) == 7 and raw[0] in (0, 1)
                if raw[0] == 0: self.zero = raw
                else: self.values['dpi'] = raw
                if self.alias:
                    self.zero, self.values['dpi'] = b'\0' + raw[1:], b'\1' + raw[1:]
            elif pair == (4, 6):
                self.values['stages'] = raw
                stage = Stages.decode(raw, self.product)
                self.values['dpi'] = b'\1' + b''.join(v.to_bytes(2, 'big') for v in stage.values[stage.active - 1]) + bytes(2)
            else:
                self.values['polling'] = raw
        if self.sleep_after_write:
            self.awake = False
        if len(self.writes) in self.fail_at:
            raise DeviceUnavailable('ACK lost after applying setter')


@pytest.mark.parametrize('product', [0xB4, 0xE8])
def test_independent_roundtrip_preserves_every_bank_and_opaque_bytes_without_enabling_support(tmp_path, product):
    mouse = Mouse(product)
    mouse.zero = bytes.fromhex('00064006a41234')
    prepared = probe.prepare_document(mouse)
    assert not mouse.writes
    assert len(prepared['before']['records']) == len(mouse.controls) * 2 * (1 + len(mouse.assigned))
    waits = []
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=2, wait=waits.append)
    assert result['status'] == 'readback-roundtrip-restored'
    assert result['selector_readback_independent'] and result['original_state_restored']
    assert not result['temporary_dpi_supported']
    assert len(waits) == 20 and sum(waits) == pytest.approx(2)
    assert [c.payload for c in mouse.writes] == [bytes.fromhex(prepared['target']), bytes.fromhex(prepared['before']['selector_zero'])]
    assert all(c.payload[-2:] == b'\x12\x34' for c in mouse.writes)
    assert probe.stable_state(probe.capture(mouse)) == probe.stable_state(prepared['before'])
    assert prepared['status'] == 'prepared-read-only'
    assert json.loads((tmp_path / 'journal.json').read_text()) == result
    assert (tmp_path / 'journal.json').stat().st_mode & 0o777 == 0o600


def test_aliasing_saved_storage_fails_the_experiment_and_restores_original_saved_dpi(tmp_path):
    mouse = Mouse(alias=True)
    prepared = probe.prepare_document(mouse)
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=0)
    assert result['status'] == 'test-failed-restored'
    assert 'changed saved-settings readback' in result['experiment_error']
    assert not result['selector_readback_independent'] and result['original_state_restored']
    assert [c.payload[0] for c in mouse.writes] == [0, 1]
    assert probe.capture(mouse) == prepared['before']


def test_ignored_candidate_is_not_claimed_successful_or_repeated(tmp_path):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    mouse.ignore_setters = True
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=0)
    assert result['status'] == 'test-failed-restored'
    assert len(mouse.writes) == 1 and not result['selector_readback_independent']


@pytest.mark.parametrize('status', [3, 5])
def test_rejected_candidate_stops_without_unnecessary_restore_setters(tmp_path, status):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    def rejected(command):
        mouse.writes.append(command)
        raise DeviceStatusError(status)
    mouse._exchange = rejected
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=0)
    assert result['status'] == 'test-failed-restored'
    assert len(mouse.writes) == 1 and not result['selector_readback_independent']


def test_aliasing_that_cannot_restore_both_getters_is_reported_as_unresolved(tmp_path):
    mouse = Mouse()
    mouse.zero = bytes.fromhex('00064006400000')
    prepared = probe.prepare_document(mouse)
    original = mouse._exchange
    def exchange(command):
        mouse.alias = True
        original(command)
    mouse._exchange = exchange
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=0)
    assert result['status'] == 'recovery-required'
    assert not result['original_state_restored'] and not result['selector_readback_independent']
    assert [c.payload[0] for c in mouse.writes] == [0, 1, 0, 1]
    assert mouse.values['dpi'].hex() == prepared['before']['settings']['dpi']
    assert mouse.zero.hex() != prepared['before']['selector_zero']


def test_lost_ack_restores_using_readback_without_resending_the_target(tmp_path):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    mouse.fail_at = {1}
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=0)
    assert result['status'] == 'test-failed-restored' and 'ACK lost' in result['experiment_error']
    assert [c.payload.hex() for c in mouse.writes] == [prepared['target'], prepared['before']['selector_zero']]


def test_lost_restore_ack_retains_journal_and_explicit_recovery_needs_no_repeat_set(tmp_path, monkeypatch):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    mouse.fail_at = {2}
    path = tmp_path / 'journal.json'
    result = probe.exercise(mouse, prepared, path, hold_seconds=0)
    assert result['status'] == 'recovery-required' and not result['original_state_restored']
    assert mouse.zero.hex() == prepared['before']['selector_zero']
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    assert probe.main(['recover', '--journal', str(path)]) == 0
    document = json.loads(path.read_text())
    assert document['original_state_restored'] and 'recovery_error' not in document
    assert len(mouse.writes) == 2  # Readback resolves uncertainty without another write.


def test_disconnect_then_wake_can_recover_original_bytes_from_disk(tmp_path, monkeypatch):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    mouse.sleep_after_write = True
    path = tmp_path / 'journal.json'
    result = probe.exercise(mouse, prepared, path, hold_seconds=0)
    assert result['status'] == 'recovery-required'
    assert json.loads(path.read_text())['before'] == prepared['before']
    mouse.awake, mouse.sleep_after_write = True, False
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    result = probe.recover(path)
    assert result['original_state_restored'] and probe.capture(mouse) == prepared['before']
    assert len(mouse.writes) == 2


@pytest.mark.parametrize('change', ['serial', 'mode', 'firmware', 'profile', 'binding', 'dpi', 'zero'])
def test_stale_preparation_rejects_before_any_write_or_journal(tmp_path, change):
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse)
    if change == 'serial': mouse.serial = 'replacement'
    elif change == 'mode': mouse.mode = b'\3\0'
    elif change == 'firmware': mouse.firmware = b'\2\0'
    elif change == 'profile': mouse.active = 3
    elif change == 'binding': mouse.binding_change = True
    elif change == 'dpi': mouse.values['dpi'] = bytes.fromhex('01032003200000')
    else: mouse.zero = bytes.fromhex('00032003200000')
    path = tmp_path / 'journal.json'
    with pytest.raises(ProtocolError): probe.exercise(mouse, prepared, path, hold_seconds=0)
    assert not mouse.writes and not path.exists()


@pytest.mark.parametrize('change', ['serial', 'mode', 'firmware', 'profile'])
def test_changed_identity_mode_or_profile_during_hold_prevents_recovery_writes(tmp_path, change):
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse)
    def alter(_):
        if change == 'serial': mouse.serial = 'replacement'
        elif change == 'mode': mouse.mode = b'\3\0'
        elif change == 'firmware': mouse.firmware = b'\2\0'
        else: mouse.active = 3
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=1, wait=alter)
    assert result['status'] == 'recovery-required' and len(mouse.writes) == 1


def test_changes_to_an_inactive_bank_are_detected_but_never_overwritten(tmp_path):
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse)
    def alter(_): mouse.binding_change = True
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=1, wait=alter)
    assert result['status'] == 'recovery-required'
    assert not result['selector_readback_independent'] and not result['original_state_restored']
    assert mouse.zero.hex() == prepared['before']['selector_zero']
    assert len(mouse.writes) == 2 and all((c.category, c.operation) == (4, 5) for c in mouse.writes)


def test_changed_reply_metadata_does_not_fabricate_a_binding_difference(tmp_path):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    def alter(_): mouse.reply_flag = 1
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=1, wait=alter)
    assert result['status'] == 'readback-roundtrip-restored'
    assert result['after_restore']['records'] != prepared['before']['records']


def test_coupled_stage_and_scalar_recovery_preserves_independent_original_dpi(tmp_path):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    def alter(_):
        raw = bytearray(mouse.values['stages'])
        raw[1] = 2
        mouse.values['stages'] = bytes(raw)
        mouse.values['polling'] = b'\2'
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=1, wait=alter)
    assert result['status'] == 'test-failed-restored'
    assert [(c.category, c.operation) for c in mouse.writes] == [(4, 5), (4, 6), (4, 5), (0, 5), (4, 5)]
    assert probe.capture(mouse) == prepared['before']


def test_failed_saved_restoration_is_not_blindly_repeated(tmp_path):
    mouse = Mouse(alias=True)
    prepared = probe.prepare_document(mouse)
    original = mouse._exchange
    def exchange(command):
        if mouse.writes: mouse.ignore_setters = True
        original(command)
    mouse._exchange = exchange
    result = probe.exercise(mouse, prepared, tmp_path / 'journal.json', hold_seconds=0)
    assert result['status'] == 'recovery-required' and len(mouse.writes) == 2
    assert 'restoration did not verify' in result['recovery_error']


@pytest.mark.parametrize('when', ['before', 'hold', 'budget'])
def test_cancellation_and_read_budget_never_skip_restoration(tmp_path, monkeypatch, when):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    stop = False
    original = probe.ReadBudget.checkpoint
    def checkpoint(self):
        if when == 'budget' and mouse.writes: self.remaining = 0
        return original(self)
    monkeypatch.setattr(probe.ReadBudget, 'checkpoint', checkpoint)
    def wait(_):
        nonlocal stop
        stop = True
    path = tmp_path / 'journal.json'
    if when == 'before':
        with pytest.raises(InterruptedError): probe.exercise(mouse, prepared, path, stopped=lambda: True)
        assert not mouse.writes and not path.exists()
    else:
        result = probe.exercise(mouse, prepared, path, hold_seconds=1, stopped=lambda: stop, wait=wait)
        assert result['status'] == 'test-failed-restored' and len(mouse.writes) == 2
        assert probe.capture(mouse) == prepared['before']


def test_journal_failure_before_write_prevents_mutation_and_after_write_still_restores(tmp_path, monkeypatch):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    real = probe.durable_json
    def fail(path, document): raise OSError('Disk full')
    monkeypatch.setattr(probe, 'durable_json', fail)
    with pytest.raises(OSError): probe.exercise(mouse, prepared, tmp_path / 'never.json', hold_seconds=0)
    assert not mouse.writes
    def fail_update(path, document):
        if path.exists(): raise OSError('Disk full after write')
        real(path, document)
    monkeypatch.setattr(probe, 'durable_json', fail_update)
    path = tmp_path / 'retained.json'
    with pytest.raises(OSError): probe.exercise(mouse, prepared, path, hold_seconds=0)
    assert probe.capture(mouse) == prepared['before'] and len(mouse.writes) == 2
    assert json.loads(path.read_text())['status'] == 'armed'


@pytest.mark.parametrize('damage', ['target', 'settings', 'zero', 'records', 'firmware', 'claims'])
def test_malformed_experiment_cannot_write_recovery_bytes(tmp_path, damage):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    if damage == 'target': prepared['target'] = '01' + prepared['target'][2:]
    elif damage == 'settings': prepared['before']['settings']['dpi'] = '02032003200000'
    elif damage == 'zero': prepared['before']['selector_zero'] = 'ff'
    elif damage == 'records': prepared['before']['records'].pop()
    elif damage == 'firmware': prepared['before']['firmware'] = '00'
    else: prepared['temporary_dpi_supported'] = True
    with pytest.raises(ProtocolError): probe.restore_original(mouse, prepared)
    assert not mouse.writes


def test_prepare_and_run_use_private_one_shot_directories_and_no_production_changes(tmp_path, monkeypatch):
    mouse = Mouse()
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    directory = tmp_path / 'trial'
    assert probe.main(['prepare', '--product', '00b4', '--directory', str(directory)]) == 0
    assert not mouse.writes and directory.stat().st_mode & 0o777 == 0o700
    assert probe.main(['run', '--directory', str(directory), '--hold-seconds', '0']) == 0
    count = len(mouse.writes)
    with pytest.raises(SystemExit): probe.main(['run', '--directory', str(directory), '--hold-seconds', '0'])
    with pytest.raises(SystemExit): probe.main(['prepare', '--product', '00b4', '--directory', str(directory)])
    assert len(mouse.writes) == count


def test_receiver_selection_refuses_an_additional_wired_transport(monkeypatch):
    devices = [SimpleNamespace(product_id=0xE8, model=PRODUCTS[0xE8][0])]
    monkeypatch.setattr(probe, 'discover', lambda: devices)
    assert probe.connected(0xE8) is devices[0]
    devices.append(SimpleNamespace(product_id=0xE7, model=PRODUCTS[0xE7][0]))
    with pytest.raises(ProtocolError): probe.connected(0xE8)
    with pytest.raises(ProtocolError): probe.connected(0xE7)


def test_a_read_only_preparation_is_not_a_restore_request(tmp_path, monkeypatch):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    path = tmp_path / 'prepared.json'
    probe.durable_json(path, prepared)
    def forbidden(_): raise AssertionError('No hardware open for an unattempted journal')
    monkeypatch.setattr(probe, 'connected', forbidden)
    with pytest.raises(ProtocolError, match='attempted experiment'): probe.recover(path)


def test_signal_cancellation_is_observed_and_original_handlers_are_restored():
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    with probe.cancellation() as stopped:
        assert not stopped()
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert stopped()
    assert all(signal.getsignal(sig) == handler for sig, handler in previous.items())


@pytest.mark.parametrize('dpi', [100, 200, 29900, 30000])
def test_prepared_target_stays_in_range_and_differs_from_both_getters(dpi):
    mouse = Mouse()
    mouse.zero = b'\0' + dpi.to_bytes(2, 'big') * 2 + b'\xaa\xbb'
    prepared = probe.prepare_document(mouse)
    pair = probe.selector_zero(bytes.fromhex(prepared['target']), mouse.product)
    assert all(100 <= v <= 30000 and v not in (dpi, 1800) for v in pair)
    assert prepared['target'].endswith('aabb')


@pytest.mark.parametrize('reset', [True, False])
def test_sensor_observation_records_reported_cycle_and_restores_without_claiming_support(tmp_path, reset):
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE)
    assert probe.selector_zero(bytes.fromhex(prepared['target']), mouse.product) == (900, 900)
    events = []
    def feedback():
        if reset:
            mouse.zero = bytes.fromhex(prepared['before']['selector_zero'])
        return {'slower': True, 'power_cycled': True, 'speed_after_cycle': 'original' if reset else 'slower'}
    result = sensor.exercise(mouse, prepared, tmp_path / 'journal.json', feedback, ready=lambda: events.append('ready'))
    assert result['status'] == 'sensor-observation-restored' and events == ['ready']
    assert result['power_cycle_readback'] == ('original' if reset else 'candidate')
    assert result['user_report']['slower'] and not result['temporary_dpi_supported']
    assert result['original_state_restored'] and probe.capture(mouse) == prepared['before']
    assert len(mouse.writes) == (1 if reset else 2)
    assert json.loads((tmp_path / 'journal.json').read_text()) == result


@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'invalid', 'alias', 'changed-settings', 'lost-ack'])
def test_sensor_observation_failures_restore_original_values(tmp_path, failure):
    mouse = Mouse(0xE8, alias=failure == 'alias')
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE)
    if failure == 'lost-ack': mouse.fail_at = {1}
    clock = [0]
    def wait(_): clock[0] = 181
    def feedback():
        if failure == 'timeout': return None
        if failure == 'invalid': return {'power_cycled': True}
        if failure == 'changed-settings': mouse.values['polling'] = b'\2'
        return {'slower': True, 'power_cycled': True, 'speed_after_cycle': 'unsure'}
    result = sensor.exercise(mouse, prepared, tmp_path / 'journal.json', feedback,
                             ready=lambda: None, stopped=lambda: failure == 'cancel' and bool(mouse.writes),
                             now=lambda: clock[0], wait=wait)
    assert result['status'] == 'test-failed-restored'
    assert result['original_state_restored'] and probe.capture(mouse) == prepared['before']
    assert not result['temporary_dpi_supported']


def test_sensor_recovery_handles_interruption_while_waiting_for_user(tmp_path, monkeypatch):
    mouse = Mouse(0xE8)
    document = probe.prepare_document(mouse, purpose=sensor.PURPOSE)
    path = tmp_path / 'journal.json'
    document['status'] = 'awaiting-user-observation'
    mouse.zero = bytes.fromhex(document['target'])
    path.write_text(json.dumps(document))
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    result = probe.recover(path)
    assert result['status'] == 'original-state-restored' and result['original_state_restored']
    assert probe.capture(mouse) == document['before']


def test_sensor_target_and_mode_are_validated_before_any_write(tmp_path):
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE)
    with pytest.raises(ProtocolError, match='user-paced'):
        probe.exercise(mouse, prepared, tmp_path / 'wrong.json')
    prepared['target'] = '00006400640000'
    with pytest.raises(ProtocolError):
        sensor.exercise(mouse, prepared, tmp_path / 'wrong.json', lambda: None)
    assert not mouse.writes and not (tmp_path / 'wrong.json').exists()


def test_requested_sensor_dpi_uses_exact_prepared_lower_value_and_restores(tmp_path):
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=1200)
    assert probe.selector_zero(bytes.fromhex(prepared['target']), mouse.product) == (1200, 1200)
    report = {'slower': True, 'power_cycled': True, 'speed_after_cycle': 'original'}
    result = sensor.exercise(mouse, prepared, tmp_path / 'journal.json', lambda: report)
    assert result['original_state_restored'] and probe.capture(mouse) == prepared['before']
    assert mouse.writes[0].payload == bytes.fromhex(prepared['target'])


@pytest.mark.parametrize('requested', [True, 99, 1800, 2000, 50001, '1200', 1200.0])
def test_requested_sensor_dpi_is_bounded_lower_and_cannot_change_readback_experiment(requested):
    mouse = Mouse(0xE8)
    with pytest.raises(ProtocolError):
        probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=requested)
    with pytest.raises(ProtocolError):
        probe.prepare_document(mouse, requested_dpi=1200)
    assert not mouse.writes


@pytest.mark.parametrize('reset', [True, False])
def test_receiver_replug_reopens_transport_observes_usb_boundary_and_restores(tmp_path, reset):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=1200)
    before = {'product': mouse.product, 'usb_path': '/sys/devices/usb1/1-2', 'busnum': '1', 'devnum': '4'}
    prepared.update(experiment='receiver-replug', receiver_route=before)
    after = {**before, 'devnum': '5'}
    seen = iter([before, None, None, {'pending': True}, after])
    opened, closed, active = [], [], []
    @contextmanager
    def opening():
        index = len(opened) + 1
        opened.append(index)
        active.append(index)
        if index == 2 and reset:
            mouse.zero = bytes.fromhex(prepared['before']['selector_zero'])
        try: yield mouse
        finally:
            active.remove(index)
            closed.append(index)
    def observe():
        assert not active
        return next(seen)
    ready = []
    result = replug.exercise(prepared, tmp_path / 'journal.json', opening, observe,
                             ready=lambda: ready.append(True), wait=lambda _: None)
    assert result['status'] == 'receiver-replug-restored' and ready == [True]
    assert result['receiver_disconnect_observed'] and result['reconnected_route'] == after
    assert result['receiver_replug_readback'] == ('original' if reset else 'candidate')
    assert opened == closed == [1, 2, 3]
    assert result['original_state_restored'] and not result['temporary_dpi_supported']
    assert probe.capture(mouse) == prepared['before']
    assert len(mouse.writes) == (1 if reset else 2)


@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'wrong-port', 'same-address', 'read-failure', 'alias'])
def test_receiver_replug_failures_restore_without_replaying_candidate(tmp_path, failure):
    from contextlib import contextmanager
    mouse = Mouse(0xE8, alias=failure == 'alias')
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=1200)
    before = {'product': mouse.product, 'usb_path': '/sys/devices/usb1/1-2', 'busnum': '1', 'devnum': '4'}
    prepared.update(experiment='receiver-replug', receiver_route=before)
    after = {**before, 'devnum': '5'}
    if failure == 'wrong-port': after['usb_path'] += '-other'
    if failure == 'same-address': after['devnum'] = '4'
    count, opened, clock = [0], [0], [0]
    def observe():
        count[0] += 1
        if count[0] == 1: return before
        return None if count[0] == 2 else after
    @contextmanager
    def opening():
        opened[0] += 1
        if failure == 'read-failure' and opened[0] == 2:
            raise ProtocolError('Invalid response after reconnect')
        yield mouse
    def wait(_):
        if failure in ('timeout', 'same-address'): clock[0] = 181
    result = replug.exercise(prepared, tmp_path / 'journal.json', opening, observe, now=lambda: clock[0], wait=wait,
                             stopped=lambda: failure == 'cancel' and bool(mouse.writes))
    assert result['status'] == 'test-failed-restored'
    assert result['original_state_restored'] and probe.capture(mouse) == prepared['before']
    assert sum(c.payload == bytes.fromhex(prepared['target']) for c in mouse.writes) == 1


def test_receiver_replug_unavailable_cleanup_retains_recoverable_journal(tmp_path, monkeypatch):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=1200)
    before = {'product': mouse.product, 'usb_path': '/sys/devices/usb1/1-2', 'busnum': '1', 'devnum': '4'}
    prepared.update(experiment='receiver-replug', receiver_route=before)
    opened, clock = [0], [0]
    @contextmanager
    def opening():
        opened[0] += 1
        if opened[0] > 1: raise DeviceUnavailable('Receiver remains unplugged')
        yield mouse
    def observe(): return before if not mouse.writes else None
    def wait(_): clock[0] = 181
    path = tmp_path / 'journal.json'
    result = replug.exercise(prepared, path, opening, observe, wait=wait, now=lambda: clock[0])
    assert result['status'] == 'recovery-required' and not result['original_state_restored']
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    assert probe.recover(path)['original_state_restored']
    assert probe.capture(mouse) == prepared['before']


@pytest.mark.parametrize('transient', [DeviceStatusError(4), DeviceUnavailable('Radio is reconnecting')])
def test_receiver_replug_waits_for_radio_after_usb_enumeration_without_replaying_setter(tmp_path, transient):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    prepared = probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=1200)
    before = {'product': mouse.product, 'usb_path': '/sys/devices/usb1/1-2', 'busnum': '1', 'devnum': '4'}
    prepared.update(experiment='receiver-replug', receiver_route=before)
    after = {**before, 'devnum': '5'}
    seen = iter([before, None, after])
    opened = [0]
    @contextmanager
    def opening():
        opened[0] += 1
        if opened[0] in (2, 3):
            raise transient
        yield mouse
    result = replug.exercise(prepared, tmp_path / 'journal.json', opening, lambda: next(seen), wait=lambda _: None)
    assert result['status'] == 'receiver-replug-restored'
    assert result['receiver_replug_readback'] == 'candidate' and result['original_state_restored']
    assert sum(c.payload == bytes.fromhex(prepared['target']) for c in mouse.writes) == 1
    assert probe.capture(mouse) == prepared['before']


@pytest.mark.parametrize('status', [1, 4])
def test_receiver_readiness_retries_actual_getter_failures(tmp_path, status):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    before = probe.capture(mouse)
    calls = [0]
    original = mouse.execute
    def execute(command):
        if (command.category, command.operation) == (0, 0x84):
            calls[0] += 1
            if calls[0] <= 2: raise DeviceStatusError(status)
        return original(command)
    mouse.execute = execute
    @contextmanager
    def opening(): yield mouse
    document = {}
    with replug.responsive_transport(opening, before, document, tmp_path / 'journal.json', 'check',
                                     stopped=lambda: False, wait=lambda _: None, now=lambda: 0) as (io, state):
        assert io is mouse and state == before
    assert len(document['readiness_retries']) == 2 and not mouse.writes


@pytest.mark.parametrize('failure', [DeviceStatusError(3), DeviceStatusError(5), ProtocolError('Identity mismatch')])
def test_receiver_readiness_does_not_retry_structural_failures(tmp_path, failure):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    before = probe.capture(mouse)
    calls = []
    @contextmanager
    def opening():
        calls.append(True)
        raise failure
        yield mouse
    with pytest.raises(type(failure)):
        with replug.responsive_transport(opening, before, {}, tmp_path / 'never.json', 'check',
                                         stopped=lambda: False, wait=lambda _: None, now=lambda: 0):
            pytest.fail('Should not yield')
    assert len(calls) == 1 and not mouse.writes


def test_receiver_readiness_never_retries_an_uncertain_setter_from_its_caller(tmp_path):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    before = probe.capture(mouse)
    calls = []
    @contextmanager
    def opening():
        calls.append(True)
        yield mouse
    mouse.fail_at = {1}
    with pytest.raises(DeviceUnavailable):
        with replug.responsive_transport(opening, before, {}, tmp_path / 'never.json', 'restore',
                                         stopped=lambda: False, wait=lambda _: None, now=lambda: 0) as (io, _):
            io._exchange(probe.Command(4, 5, bytes.fromhex(before['selector_zero'])))
    assert len(calls) == 1 and len(mouse.writes) == 1


def test_receiver_readiness_bounds_retries_even_when_clock_does_not_advance(tmp_path):
    from contextlib import contextmanager
    mouse = Mouse(0xE8)
    before = probe.capture(mouse)
    calls = []
    @contextmanager
    def opening():
        calls.append(True)
        raise DeviceStatusError(4)
        yield mouse
    document = {}
    with pytest.raises(ProtocolError, match='read-only readiness limit'):
        with replug.responsive_transport(opening, before, document, tmp_path / 'journal.json', 'check',
                                         stopped=lambda: False, wait=lambda _: None, now=lambda: 0):
            pytest.fail('Should not yield')
    assert len(calls) == len(document['readiness_retries']) == 16 and not mouse.writes


@pytest.mark.parametrize('accessible', [False, True])
def test_receiver_route_waits_for_current_hid_access_before_declaring_reconnect(monkeypatch, accessible):
    expected = {'product': 0xE8, 'usb_path': '/sys/devices/usb1/1-2', 'busnum': '1', 'devnum': '5', 'node': '/dev/hidraw12'}
    mouse = SimpleNamespace(product_id=0xE8, usb_path=expected['usb_path'])
    monkeypatch.setattr(replug, 'discover', lambda: [mouse])
    monkeypatch.setattr(replug, 'route', lambda _: expected)
    checked = []
    def access(path, flags):
        checked.append((path, flags))
        return accessible
    monkeypatch.setattr(replug, 'os', SimpleNamespace(access=access, R_OK=4, W_OK=2), raising=False)
    assert replug.observe_route(expected) == (expected if accessible else {'pending': True})
    assert checked == [('/dev/hidraw12', 6)]


class ModeMouse(Mouse):
    def __init__(self):
        super().__init__(0xE8)
        self.mode_writes, self.mode_fail_at = [], set()
    def _exchange(self, command):
        if (command.category, command.operation) == (0, 4):
            self.mode_writes.append(command.payload)
            self.mode = command.payload
            if len(self.mode_writes) in self.mode_fail_at:
                raise DeviceUnavailable('Mode ACK lost after applying')
            return command.payload
        return super()._exchange(command)


def driver_prepared(mouse):
    document = probe.prepare_document(mouse, purpose=sensor.PURPOSE, requested_dpi=1200)
    document['experiment'] = 'driver-dpi'
    return document


@pytest.mark.parametrize('usual', [True, False])
def test_driver_dpi_observation_restores_mode_and_every_original_without_grabbing_input(tmp_path, usual):
    mouse = ModeMouse()
    prepared = driver_prepared(mouse)
    ready = []
    def feedback():
        assert mouse.mode == b'\3\0'
        assert probe.selector_zero(mouse.zero, mouse.product) == (1200, 1200)
        return {'feels_usual': usual}
    result = driverdpi.exercise(mouse, prepared, tmp_path / 'journal.json', tmp_path / 'mode.json', feedback,
                                ready=lambda: ready.append(True))
    assert result['status'] == 'driver-dpi-restored' and ready == [True]
    assert result['normal_mode_restored'] and result['original_state_restored']
    assert result['user_report'] == {'feels_usual': usual} and not result['temporary_dpi_supported']
    assert result['driver_candidate']['settings'] == prepared['before']['settings']
    assert mouse.mode_writes == [b'\3\0', bytes(2)]
    assert [c.payload for c in mouse.writes] == [bytes.fromhex(prepared['target']), bytes.fromhex(prepared['before']['selector_zero'])]
    assert probe.capture(mouse) == prepared['before']
    assert json.loads((tmp_path / 'mode.json').read_text())['status'] == 'normal-mode-restored'


@pytest.mark.parametrize('failure', ['timeout', 'cancel', 'invalid', 'lost-dpi-ack', 'lost-mode-ack', 'mode-restore-ack', 'alias'])
def test_driver_dpi_failures_attempt_mode_then_setting_restoration(tmp_path, failure):
    mouse = ModeMouse()
    mouse.alias = failure == 'alias'
    prepared = driver_prepared(mouse)
    if failure == 'lost-dpi-ack': mouse.fail_at = {1}
    if failure == 'lost-mode-ack': mouse.mode_fail_at = {1}
    if failure == 'mode-restore-ack': mouse.mode_fail_at = {2}
    clock = [0]
    def wait(_): clock[0] = 181
    def feedback():
        if failure == 'timeout': return None
        if failure == 'invalid': return {'feels_usual': 'yes'}
        return {'feels_usual': True}
    result = driverdpi.exercise(mouse, prepared, tmp_path / 'journal.json', tmp_path / 'mode.json', feedback,
                                stopped=lambda: failure == 'cancel' and bool(mouse.writes), wait=wait, now=lambda: clock[0])
    assert result['status'] in ('test-failed-restored', 'recovery-required')
    if failure == 'mode-restore-ack':
        assert result['status'] == 'recovery-required'  # Actual mode changed, but ACK remained uncertain.
    else:
        assert result['normal_mode_restored'] and result['original_state_restored']
        assert probe.capture(mouse) == prepared['before']
    assert mouse.mode == bytes(2) and not result['temporary_dpi_supported']


def test_driver_dpi_recover_restores_mode_before_settings_and_keeps_wait_journals(tmp_path, monkeypatch):
    mouse = ModeMouse()
    prepared = driver_prepared(mouse)
    root = tmp_path / 'run'
    root.mkdir()
    prepared.update(status='awaiting-driver-observation', original_state_restored=False, normal_mode_restored=False)
    (root / 'journal.json').write_text(json.dumps(prepared))
    (root / 'mode.json').write_text(json.dumps({'version': 1, 'kind': 'driver-mode', 'product': mouse.product,
                                               'serial': mouse.serial, 'before': '0000', 'status': 'driver-mode-active'}))
    mouse.mode, mouse.zero = b'\3\0', bytes.fromhex(prepared['target'])
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    monkeypatch.setattr(driverdpi, 'transport', lambda _: mouse)
    result = driverdpi.recover(tmp_path)
    assert result['normal_mode_restored'] and result['original_state_restored']
    assert mouse.mode == bytes(2) and probe.capture(mouse) == prepared['before']


def test_driver_dpi_rejects_unrelated_or_already_used_preparation_before_ownership(tmp_path):
    mouse = ModeMouse()
    prepared = driver_prepared(mouse)
    prepared['experiment'] = 'receiver-replug'
    with pytest.raises(ProtocolError):
        driverdpi.exercise(mouse, prepared, tmp_path / 'journal.json', tmp_path / 'mode.json', lambda: None)
    assert not mouse.writes and not mouse.mode_writes


def test_driver_dpi_identity_change_blocks_cleanup_writes_until_original_mouse_returns(tmp_path, monkeypatch):
    mouse = ModeMouse()
    prepared = driver_prepared(mouse)
    root = tmp_path / 'run'
    root.mkdir()
    def feedback():
        mouse.serial = 'different-mouse'
        return {'feels_usual': True}
    result = driverdpi.exercise(mouse, prepared, root / 'journal.json', root / 'mode.json', feedback)
    assert result['status'] == 'recovery-required' and not result['original_state_restored']
    assert mouse.mode_writes == [b'\3\0'] and len(mouse.writes) == 1
    mouse.serial = prepared['before']['serial']
    monkeypatch.setattr(probe, 'connected', lambda _: mouse)
    monkeypatch.setattr(probe, 'transport', lambda _: mouse)
    monkeypatch.setattr(driverdpi, 'transport', lambda _: mouse)
    assert driverdpi.recover(tmp_path)['original_state_restored']


def test_driver_dpi_detects_saved_setting_drift_and_repairs_after_normal_mode(tmp_path):
    mouse = ModeMouse()
    prepared = driver_prepared(mouse)
    def feedback():
        mouse.values['polling'] = b'\2'
        return {'feels_usual': True}
    result = driverdpi.exercise(mouse, prepared, tmp_path / 'journal.json', tmp_path / 'mode.json', feedback)
    assert result['status'] == 'test-failed-restored'
    assert result['normal_mode_restored'] and result['original_state_restored']
    assert mouse.mode == bytes(2) and probe.capture(mouse) == prepared['before']
