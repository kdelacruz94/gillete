import json

import pytest

from gillete import native_macro_probe as probe
from gillete.hid import ReadOnlyHID
from gillete.protocol import Command, DeviceUnavailable, ProtocolError
from test_dpi_probe import Mouse as SettingsMouse


class Mouse(SettingsMouse):
    def __init__(self):
        super().__init__(0xE8)
        self.assigned = (1,)
        self.controls += (0xFE,)  # Unknown controls must also be checked for references.
        self.functions, self.flags, self.macros = {}, {}, {}
        self.fail_write = None
        self.ignore = set()
        self.journal = None
        self.catalog_extra = False

    def read_binding_record(self, bank, control, layer):
        self.device_serial()
        requested = bank
        bank = bank or self.active
        function = self.functions.get((bank, control, layer), bytes.fromhex('05020000000000'))
        return bytes((requested, control, self.flags.get((bank, control), 0))) + function

    def read_binding(self, bank, control, layer):
        return self.read_binding_record(bank, control, layer)[3:]

    def write_binding(self, bank, control, layer, function):
        command = Command(2, 12, bytes((bank, control, layer)) + function)
        self.writes.append(command)
        if len(self.writes) not in self.ignore:
            self.functions[bank, control, layer] = function
            self.flags[bank, control] = layer
        self.fail()

    def fail(self):
        if len(self.writes) == self.fail_write:
            raise DeviceUnavailable('SET applied but ACK lost')

    def execute(self, command):
        if command.category != 6:
            raw = super().execute(command)
            # A bank-zero response echoes requested bank zero, not active bank.
            return command.payload[:2] + raw[2:] if (command.category, command.operation) == (2, 0x8C) else raw
        self.device_serial()
        self.reads.append(command)
        op, data = command.operation, command.payload
        ids = sorted(self.macros) + ([30000] if self.catalog_extra else [])
        if op == 0x8E:
            return (128).to_bytes(2, 'big') + (307200).to_bytes(4, 'big') + (307200 - 512 * len(ids)).to_bytes(4, 'big') + bytes(4)
        if op == 0x80: return len(ids).to_bytes(2, 'big')
        if op == 0x8B:
            start = int.from_bytes(data[:2], 'big')
            return data[:2] + bytes(2) + b''.join(v.to_bytes(2, 'big') for v in ids[start:start + (len(data) - 4) // 2])
        entry = self.macros[int.from_bytes(data[:2], 'big')]
        if op == 0x88: return data[:2] + len(entry['data']).to_bytes(4, 'big')
        if op == 0x89:
            offset = int.from_bytes(data[2:6], 'big')
            return data[:7] + bytes(entry['data'][offset:offset + data[6]])
        if op == 0x8C:
            offset = int.from_bytes(data[2:4], 'big')
            return data[:4] + b'\0\xfa' + bytes(entry['metadata'][offset:offset + len(data) - 6])
        raise AssertionError('Unexpected macro read')

    def _exchange(self, command):
        assert command.category == 6
        if self.journal:
            assert self.journal.exists() and json.loads(self.journal.read_text())['status'] != 'prepared-read-only'
        self.writes.append(command)
        op, data = command.operation, command.payload
        identifier = int.from_bytes(data[:2], 'big')
        if len(self.writes) not in self.ignore:
            if op == 8:
                assert identifier not in self.macros
                self.macros[identifier] = {'metadata': bytearray(250), 'data': bytearray(int.from_bytes(data[2:], 'big'))}
            elif op in (9, 12):
                offset = int.from_bytes(data[2:6] if op == 9 else data[2:4], 'big')
                payload = data[7:] if op == 9 else data[6:]
                self.macros[identifier]['data' if op == 9 else 'metadata'][offset:offset + len(payload)] = payload
            elif op == 3:
                # The macro must never be deleted while any bank references it.
                assert not probe.references(probe.snapshot(self), identifier)
                self.macros.pop(identifier)
            else: raise AssertionError('Unexpected macro setter')
        self.fail()


def run(mouse, tmp_path, observe=lambda stopped: {'f24_down': True, 'f24_up': True, 'hold_ms': 80.0}, **kwargs):
    prepared = probe.prepare_document(mouse)
    assert not mouse.writes
    mouse.journal = tmp_path / 'journal.json'
    result = probe.exercise(mouse, prepared, mouse.journal, observe, **kwargs)
    assert json.loads(mouse.journal.read_text()) == result
    return prepared, result


def test_complete_native_roundtrip_checks_unknown_controls_and_restores_flags_before_delete(tmp_path):
    mouse = Mouse()
    mouse.flags[1, probe.CONTROL] = 1
    prepared, result = run(mouse, tmp_path)
    assert result['status'] == 'native-macro-restored'
    assert result['native_playback_verified'] and result['original_state_restored']
    assert len(prepared['before']['all_records']) == len(mouse.controls) * 12
    assert not mouse.macros and mouse.flags[1, probe.CONTROL] == 1
    assert [c.operation for c in mouse.writes if c.category == 6] == [8, 12, 12, 12, 12, 9, 3]
    assert mouse.writes[-1].operation == 3
    assert probe.normalized(probe.snapshot(mouse)) == probe.normalized(prepared['before'])
    assert mouse.journal.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('failure', [1, 2, 3, 4, 5, 6, 7])
def test_uncertain_writes_never_repeat_and_partial_unowned_objects_are_retained(tmp_path, failure):
    mouse = Mouse()
    mouse.fail_write = failure
    prepared, result = run(mouse, tmp_path)
    assert len([c for c in mouse.writes if c.category == 6 and c.operation == 8]) == 1
    # Full metadata AND body only exist after write 6; before that ownership
    # cannot meet the experiment's strict cleanup rule, so retain the orphan.
    if failure <= 5:
        assert result['status'] == 'recovery-required' and mouse.macros
        assert not any(c.category == 2 for c in mouse.writes)
        assert not any(c.category == 6 and c.operation == 3 for c in mouse.writes)
    else:
        assert result['status'] == 'test-failed-restored' and not mouse.macros
        assert result['original_state_restored']
    assert all(mouse.read_binding(1, probe.CONTROL, layer).hex() ==
               next(e['raw'][6:] for e in prepared['before']['all_records']
                    if (e['bank'], e['control'], e['layer']) == (1, probe.CONTROL, layer)) for layer in (0, 1))


def test_failed_body_readback_prevents_binding_and_keeps_recovery_evidence(tmp_path):
    mouse = Mouse()
    mouse.ignore.add(6)
    _, result = run(mouse, tmp_path)
    assert result['status'] == 'recovery-required'
    assert not any(c.category == 2 for c in mouse.writes)
    assert 'readback' in result['experiment_error'] and mouse.macros


def test_delete_ack_loss_is_recovered_by_catalog_without_resending_delete(tmp_path):
    mouse = Mouse()
    def observation(stopped):
        # Normal original flag 0: restore normal+shifted+normal flag handling is
        # handled by Programmer. Choose the upcoming delete dynamically.
        return {'f24_down': True, 'f24_up': True, 'hold_ms': 80.0}
    original = mouse._exchange
    def lost_delete(command):
        original(command)
        if command.operation == 3: raise DeviceUnavailable('delete ACK lost')
    mouse._exchange = lost_delete
    prepared, result = run(mouse, tmp_path, observation)
    assert result['status'] == 'recovery-required' and not mouse.macros
    probe.restore(mouse, result, mouse.journal)
    assert result['original_state_restored']
    assert sum(c.category == 6 and c.operation == 3 for c in mouse.writes) == 1


def test_changed_identity_blocks_cleanup_then_original_mouse_can_recover(tmp_path):
    mouse = Mouse()
    def observation(stopped):
        mouse.serial = 'another-mouse'
        raise InterruptedError('disconnect')
    prepared, result = run(mouse, tmp_path, observation)
    assert result['status'] == 'recovery-required'
    assert mouse.writes[-1].category == 2  # No delete or restore on another mouse.
    mouse.serial = prepared['before']['serial']
    probe.restore(mouse, result, mouse.journal)
    assert result['original_state_restored'] and not mouse.macros


@pytest.mark.parametrize('change', ['unknown-reference', 'other-setting', 'side12-external', 'foreign-catalog'])
def test_external_changes_are_preserved_and_prevent_deleting_a_shared_macro(tmp_path, change):
    mouse = Mouse()
    def observation(stopped):
        identifier = next(iter(mouse.macros))
        if change == 'unknown-reference': mouse.functions[5, 0xFE, 1] = bytes.fromhex('0502') + identifier.to_bytes(2, 'big') + bytes(3)
        elif change == 'other-setting': mouse.zero = bytes.fromhex('00064006400000')
        elif change == 'side12-external': mouse.functions[1, probe.CONTROL, 0] = bytes.fromhex('02020004000000')
        else: mouse.catalog_extra = True
        return {'f24_down': True, 'f24_up': True, 'hold_ms': 80.0}
    _, result = run(mouse, tmp_path, observation)
    assert result['status'] == 'recovery-required' and mouse.macros
    assert not any(c.category == 6 and c.operation == 3 for c in mouse.writes)
    if change == 'side12-external':
        assert mouse.read_binding(1, probe.CONTROL, 0).hex() == '02020004000000'
    else:
        assert mouse.read_binding(1, probe.CONTROL, 0).hex() == '05020000000000'


def test_cancelled_observation_restores_and_never_claims_playback(tmp_path):
    def cancel(stopped): raise InterruptedError('cancelled')
    _, result = run(Mouse(), tmp_path, cancel)
    assert result['status'] == 'test-failed-restored'
    assert result['original_state_restored'] and not result['native_playback_verified']


def test_preflight_drift_or_tampered_journal_cannot_write(tmp_path):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    mouse.zero = bytes.fromhex('00064006400000')
    with pytest.raises(ProtocolError, match='changed since'):
        probe.exercise(mouse, prepared, tmp_path / 'journal.json', lambda _: None)
    assert not mouse.writes
    for field in ('data', 'binding', 'metadata', 'guid', 'identifier'):
        changed = dict(prepared)
        changed[field] = 0 if field == 'identifier' else 'ff'
        with pytest.raises(ProtocolError): probe.validate(changed)
    del prepared['before']['all_records'][-1]
    with pytest.raises(ProtocolError): probe.validate(prepared)
    assert not mouse.writes


def test_journal_failure_before_allocation_prevents_all_setters(tmp_path, monkeypatch):
    mouse = Mouse()
    prepared = probe.prepare_document(mouse)
    def disk_failure(*_): raise OSError('disk full')
    monkeypatch.setattr(probe, 'durable_json', disk_failure)
    with pytest.raises(OSError): probe.exercise(mouse, prepared, tmp_path / 'journal.json', lambda _: None)
    assert not mouse.writes


def test_experimental_reads_do_not_admit_setters_to_normal_or_macro_transport(monkeypatch):
    regular = ReadOnlyHID('/dev/hidraw999', 0xE8)
    experimental = probe.MacroHID('/dev/hidraw999', 0xE8)
    calls = []
    monkeypatch.setattr(experimental, '_exchange', lambda c: calls.append(c))
    with pytest.raises(ProtocolError): regular.execute(probe.memory.allocate(7, 6))
    for command in (probe.memory.allocate(7, 6), probe.memory.delete(7), Command(6, 10, bytes(2))):
        with pytest.raises(ProtocolError): experimental.execute(command)
    assert not calls
