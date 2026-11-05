import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from gillete.device_controls import Controls
from gillete.protocol import ProtocolError
from gillete.settings import (SettingsDraft, SettingsTransaction, SPECS, Stages,
                             encode_stages, plan)


# Physical V2 read: scalar1800 and selected stage1=1200 differ intentionally.
V2_STAGES = bytes.fromhex('0101050104b004b000000203e803e800000304b004b000000406400640000005070807080000')


class Mouse:
    product = 0xB4
    serial = 'settings-test'
    mode = 0
    active = 1

    def __init__(self):
        self.values = {'stages': V2_STAGES, 'dpi': bytes.fromhex('01070807080000'), 'polling': b'\1'}
        self.writes = []
        self.fail_at = None

    def device_serial(self): return self.serial

    def execute(self, command):
        if (command.category, command.operation) == (0, 0x84): return bytes((self.mode, 0))
        if (command.category, command.operation) == (5, 0x84): return bytes((self.active,))
        for name, (category, _, getter, query) in SPECS.items():
            if (command.category, command.operation) == (category, getter):
                assert command.payload == query  # storage1, never profile2..5
                return self.values[name]
        raise AssertionError('Unexpected command')

    def _exchange(self, command):
        for name, (category, setter, _, _) in SPECS.items():
            if (command.category, command.operation) == (category, setter):
                self.writes.append(name)
                self.values[name] = command.payload
                if name == 'stages':
                    stage = Stages.decode(command.payload, self.product)
                    x, y = stage.values[stage.active - 1]
                    self.values['dpi'] = b'\1' + x.to_bytes(2, 'big') + y.to_bytes(2, 'big') + bytes(2)
                if len(self.writes) == self.fail_at:
                    raise TimeoutError('SET applied but ACK lost')
                return
        raise AssertionError('Unexpected setter, including button programming')


def snapshot(mouse):
    return SimpleNamespace(product=mouse.product, serial=mouse.serial, active=mouse.active,
                           settings={k: v.hex() for k, v in mouse.values.items()})


def test_unchanged_settings_preserve_scalar_stage_mismatch_and_do_not_write(tmp_path):
    mouse = Mouse()
    values = Stages.decode(V2_STAGES, mouse.product)
    proposed = plan(snapshot(mouse), SettingsDraft((1800, 1800), values.values, values.active, 1000))
    assert not proposed.changes
    result = SettingsTransaction(mouse, tmp_path / 'save.json', mouse.serial, 1).apply(proposed)
    assert result['status'] == 'unchanged' and not mouse.writes
    assert not (tmp_path / 'save.json').exists()


def test_table_edit_preserves_opaque_bytes_and_independent_scalar(tmp_path):
    mouse = Mouse()
    raw = bytearray(V2_STAGES)
    raw[8:10] = b'\xaa\xbb'
    mouse.values['stages'] = bytes(raw)
    original = dict(mouse.values)
    proposed = plan(snapshot(mouse), SettingsDraft(stages=((1300, 1400),)))
    assert proposed.after['stages'][8:10] == b'\xaa\xbb'
    assert proposed.after['stages'][10:] == original['stages'][10:]
    path = tmp_path / 'save.json'
    transaction = SettingsTransaction(mouse, path, mouse.serial, 1)
    document = transaction.apply(proposed)
    assert mouse.values['dpi'] == original['dpi']
    assert mouse.writes == ['stages', 'dpi']
    transaction.restore(document)
    assert mouse.values == original


@pytest.mark.parametrize('lost_ack', [1, 2, 3])
def test_partial_bundle_and_uncertain_ack_restore_all_original_values(tmp_path, lost_ack):
    mouse = Mouse()
    original = dict(mouse.values)
    proposed = plan(snapshot(mouse), SettingsDraft(dpi=(800, 900), active=2, polling=500))
    mouse.fail_at = lost_ack
    path = tmp_path / 'save.json'
    with pytest.raises(TimeoutError, match='ACK lost'):
        SettingsTransaction(mouse, path, mouse.serial, 1).apply(proposed)
    assert mouse.values == original
    assert mouse.writes[-3:] == ['stages', 'dpi', 'polling']
    assert json.loads(path.read_text())['status'] == 'rolled-back-readback-verified'


def test_disk_failure_after_write_still_recovers_hardware(tmp_path, monkeypatch):
    import gillete.settings as settings
    mouse = Mouse()
    original = dict(mouse.values)
    proposed = plan(snapshot(mouse), SettingsDraft(dpi=(800, 800), polling=500))
    path = tmp_path / 'save.json'
    durable = settings.durable_json
    def fail_updates(path, data):
        if path.exists(): raise OSError('Disk full')
        durable(path, data)
    monkeypatch.setattr(settings, 'durable_json', fail_updates)
    with pytest.raises(OSError, match='Disk full'):
        SettingsTransaction(mouse, path, mouse.serial, 1).apply(proposed)
    assert mouse.values == original
    assert json.loads(path.read_text())['status'] == 'prepared'


@pytest.mark.parametrize('change', ['serial', 'mode', 'settings', 'profile'])
def test_stale_preview_prevents_every_write(tmp_path, change):
    mouse = Mouse()
    mouse.product = 0xE8
    proposed = plan(snapshot(mouse), SettingsDraft(dpi=(900, 900)))
    serial = mouse.serial
    if change == 'serial': mouse.serial = 'replacement'
    if change == 'mode': mouse.mode = 3
    if change == 'settings': mouse.values['polling'] = b'\2'; mouse.values['dpi'] = bytes.fromhex('01032003200000')
    if change == 'profile': mouse.active = 2
    with pytest.raises(ProtocolError):
        SettingsTransaction(mouse, tmp_path / 'save.json', serial, 1).apply(proposed)
    assert not mouse.writes and not (tmp_path / 'save.json').exists()


def test_recovery_rejects_unsupported_payload_before_writing(tmp_path):
    mouse = Mouse()
    path = tmp_path / 'save.json'
    transaction = SettingsTransaction(mouse, path, mouse.serial, 1)
    document = transaction.apply(plan(snapshot(mouse), SettingsDraft(polling=500)))
    count = len(mouse.writes)
    document['before']['polling'] = '00'
    with pytest.raises(ProtocolError): transaction.restore(document)
    assert len(mouse.writes) == count
    document['before'] = {'dpi': '02070807080000', 'stages': V2_STAGES.hex()}
    with pytest.raises(ProtocolError): transaction.restore(document)
    assert len(mouse.writes) == count


@pytest.mark.parametrize('base', [0, 1])
def test_stage_ordinals_are_independent_of_identifiers_and_profile_slot(tmp_path, base):
    mouse = Mouse()
    mouse.product, mouse.active, mouse.mode = 0xE8, 3, 3
    raw = bytearray(V2_STAGES)
    for i in range(5): raw[3 + 7*i] = base + i
    mouse.values['stages'] = bytes(raw)
    controls = Controls(mouse, snapshot(mouse), tmp_path)
    controls.dpi('up')
    assert mouse.values['stages'][1] == 2
    assert mouse.values['dpi'][1:5] == bytes.fromhex('03e803e8')
    assert mouse.values['stages'][3::7] == bytes(range(base, base + 5))


def test_limits_and_stage_growth_preserve_the_existing_format():
    mouse = Mouse()
    with pytest.raises(ProtocolError): plan(snapshot(mouse), SettingsDraft(dpi=(30001, 100)))
    with pytest.raises(ProtocolError): plan(snapshot(mouse), SettingsDraft(polling=8000))
    small = encode_stages(V2_STAGES, ((1200, 1200),), 1, mouse.product)
    larger = encode_stages(small, ((1200, 1200), (800, 900)), 2, mouse.product)
    assert Stages.decode(larger, mouse.product).identifiers == (1, 2)
    mouse.product = 0xE8
    assert plan(snapshot(mouse), SettingsDraft(dpi=(50000, 100))).changes


def test_hardware_entrypoint_and_journal_recovery_round_trip(tmp_path, monkeypatch):
    from gillete import hardware
    mouse = Mouse()
    original = dict(mouse.values)
    inspected = snapshot(mouse)
    inspected.bank, inspected.model = 1, 'naga_v2_hyperspeed'
    device = SimpleNamespace(model=inspected.model)
    monkeypatch.setattr(hardware, 'transport', lambda _: nullcontext(mouse))
    path = tmp_path / 'settings.json'
    result = hardware.apply_settings(device, inspected, SettingsDraft(dpi=(950, 1050), polling=500), path)
    assert result['status'] == 'applied-readback-verified'
    assert mouse.values['dpi'][1:5] == bytes.fromhex('03b6041a')
    assert hardware.restore(device, path)['status'] == 'restored-readback-verified'
    assert mouse.values == original


def test_failed_rollback_keeps_a_usable_original_journal(tmp_path):
    mouse = Mouse()
    original = dict(mouse.values)
    exchange = mouse._exchange
    def disconnect(command):
        exchange(command)
        raise OSError('Disconnected')
    mouse._exchange = disconnect
    path = tmp_path / 'settings.json'
    transaction = SettingsTransaction(mouse, path, mouse.serial, 1)
    with pytest.raises(ProtocolError, match='recovery required'):
        transaction.apply(plan(snapshot(mouse), SettingsDraft(active=2, dpi=(1000, 1000))))
    document = json.loads(path.read_text())
    assert document['before']['dpi'] == original['dpi'].hex()
    mouse._exchange = exchange
    transaction.restore(document)
    assert mouse.values == original


def test_dpi_button_at_boundary_uses_the_stage_even_if_scalar_was_customized(tmp_path):
    mouse = Mouse()
    mouse.mode = 3
    Controls(mouse, snapshot(mouse), tmp_path).dpi('down')
    assert mouse.values['stages'] == V2_STAGES
    assert mouse.values['dpi'][1:5] == bytes.fromhex('04b004b0')
    assert mouse.writes == ['dpi']


def test_physical_check_preparation_is_bounded_and_snapshot_roundtrips():
    from gillete.hardware import Snapshot
    from gillete.onboard import Location
    from gillete.settings_check import test_draft as make_test_draft, snapshot_document, load_snapshot
    mouse = Mouse()
    before = Snapshot(mouse.product, 'naga_v2_hyperspeed', mouse.serial, 1, (1,), 1, {0x40},
                      {Location(1, 0x40, 0): b'\1\x40\0' + bytes(7)}, snapshot(mouse).settings)
    assert load_snapshot(snapshot_document(before)) == before
    draft = make_test_draft(before)
    assert draft.dpi == (1900, 1900) and draft.active == 2 and draft.polling == 500
    assert draft.stages[0] == (1200, 1200) and draft.stages[1] == (1900, 1900)
    assert not mouse.writes
