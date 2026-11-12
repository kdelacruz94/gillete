import asyncio
from copy import deepcopy

from evdev import ecodes
import pytest

from gillete import hardware, stored_native as native
from gillete.compile_onboard import CONTROL_IDS, encode_action
from gillete.devices import Device
from gillete.engine import Engine
from gillete.hardware import Snapshot, load_snapshot, snapshot_document
from gillete.macros import KeyLedger, RecordingOutput
from gillete.model import Action, Layers, MODELS, Profile
from gillete.onboard import Location
from gillete.protocol import Command, DeviceUnavailable, ProtocolError
from gillete.stored_actions import from_snapshot
from test_native_macro_probe import Mouse


BODY = bytes.fromhex('017311500273')


def setup():
    mouse = Mouse()
    for control in CONTROL_IDS[MODELS[1]].values():
        for layer in (0, 1):
            mouse.functions[1, control, layer] = encode_action(Action('keys', keys=('KEY_1',)), MODELS[1])
    mouse.functions[1, 0x4B, 0] = mouse.functions[1, 0x4A, 1] = bytes.fromhex('03030007010000')
    mouse.macros[7] = {'data': bytearray(BODY), 'metadata': bytearray(250)}
    # The real adapter submits queries via the transport's framed exchange.
    # This simulated mouse ordinarily uses that method for setters only.
    mouse._exchange = mouse.execute
    records = {Location(1, c, l): mouse.read_binding_record(1, c, l)
               for c in CONTROL_IDS[MODELS[1]].values() for l in (0, 1)}
    snapshot = Snapshot(0xE8, MODELS[1], mouse.serial, 1, (1,), 1,
                        set(mouse.controls), records, {}, {'firmware': '0101'})
    return mouse, snapshot


def test_single_keyboard_press_preserves_exact_delays_and_snapshot_round_trip():
    mouse, snapshot = setup()
    snapshot.native_macros = native.read(mouse, snapshot)
    assert snapshot.native_macros == {7: BODY.hex()}
    restored = load_snapshot(snapshot_document(snapshot))
    assert restored == snapshot and not mouse.writes
    stored, unknown = from_snapshot(restored)
    action = stored['side_12', False]
    assert action.kind == 'macro' and action.playback == 'once'
    assert [s.kind for s in action.steps] == ['down', 'wait', 'up']
    assert action.steps[1].milliseconds == 80
    assert stored['side_11', True] == action and not unknown
    reads = [(c.category, c.operation) for c in mouse.reads]
    assert reads.count((6, 0x88)) == reads.count((6, 0x89)) == 2
    assert all(op >= 0x80 for category, op in reads if category == 6)


@pytest.mark.parametrize('data', [b'', b'\1', b'\xff\0', b'\1\0\2\0', b'\1\x73',
    b'\2\x73', b'\1\x73\1\x73\2\x73', b'\1\x73\2\x72',
    b'\x08\1\x08\0', b'\x0a\1',
    b'\x15\0\0\0\0', b'\1\xff\2\xff', b'\1\x73\x14\x80\0\0\0\2\x73',
    b'\1\x73\x14\0\x36\xee\x81\2\x73'])
def test_opaque_unbalanced_mouse_and_unsafe_delays_stay_unresolved(data):
    assert native.decode_once(data) is None


@pytest.mark.parametrize('binding', ['03030000010000', '03030007000000',
    '03030007010001', '03038000010000', '04020007000000', '05020007000000', '0f020007000000'])
def test_invalid_ids_counts_padding_and_unaccepted_reference_families_stay_unresolved(binding):
    assert native.reference(bytes.fromhex(binding)) is None


@pytest.mark.parametrize('change', ['v2', 'wired', 'firmware', 'no-reference'])
def test_unaccepted_routes_firmware_and_plain_snapshots_make_no_macro_queries(change):
    mouse, snapshot = setup()
    if change == 'v2': snapshot.product, snapshot.model = 0xB4, MODELS[0]
    elif change == 'wired': snapshot.product = 0xE7
    elif change == 'firmware': snapshot.metadata['firmware'] = '0102'
    else: snapshot.records = {}
    before = len(mouse.reads)
    assert native.read(mouse, snapshot) == {} and len(mouse.reads) == before


def test_missing_and_opaque_objects_never_become_empty_executable_macros():
    mouse, snapshot = setup()
    mouse.macros.clear()
    assert native.read(mouse, snapshot) == {}
    mouse.macros[7] = {'data': bytearray(b'\xff\0'), 'metadata': bytearray(250)}
    snapshot.native_macros = native.read(mouse, snapshot)
    stored, unknown = from_snapshot(snapshot)
    assert ('side_12', False) in unknown and ('side_12', False) not in stored
    assert ('side_11', True) in unknown and not mouse.writes


@pytest.mark.parametrize('change', ['body', 'binding', 'timeout'])
def test_changed_or_unreadable_macro_cannot_yield_an_executable_result(change):
    mouse, snapshot = setup()
    original = mouse._exchange
    reads = 0
    def changed(command):
        nonlocal reads
        if command.operation == 0x89:
            reads += 1
            if change == 'timeout': raise DeviceUnavailable('Macro getter timed out')
            if change == 'body' and reads == 2: mouse.macros[7]['data'][1] = 0x72
            if change == 'binding': mouse.functions[1, 0x4B, 0] = bytes(7)
        return original(command)
    mouse._exchange = changed
    with pytest.raises(ProtocolError): native.read(mouse, snapshot)
    assert not mouse.writes and snapshot.native_macros == {}


def test_getter_adapter_rejects_setters_and_non_identity_validating_commands():
    mouse, _ = setup()
    reads = native.Reads(mouse)
    for command in (Command(6, 3, b'\0\7'), Command(6, 0x80, bytes(2))):
        with pytest.raises(ProtocolError): reads.execute(command)
    assert not mouse.reads and not mouse.writes
    reads.remaining = 0
    from gillete.macro_reads import request
    with pytest.raises(ProtocolError, match='limit'): reads.execute(request(0x80, bytes(2)))


@pytest.mark.parametrize('change', ['missing', 'changed', 'opaque'])
def test_second_transport_rechecks_body_before_software_ownership(change):
    mouse, snapshot = setup()
    snapshot.native_macros = native.read(mouse, snapshot)
    if change == 'missing': mouse.macros.clear()
    elif change == 'changed': mouse.macros[7]['data'][1] = mouse.macros[7]['data'][-1] = 0x72
    else: mouse.macros[7]['data'] = bytearray(b'\xff\0')
    with pytest.raises(ProtocolError, match='changed after inspection'): native.verify(mouse, snapshot)
    assert not mouse.writes


@pytest.mark.parametrize('values', [[], {'0': BODY.hex()}, {'07': BODY.hex()}, {'true': BODY.hex()},
    {'7': 123}, {'7': ''}, {'7': 'gg'}, {'7': '00' * 4097},
    {str(i): '00' * 4096 for i in (1, 2, 3)}])
def test_invalid_private_snapshot_bodies_cannot_be_imported(values):
    _, snapshot = setup()
    document = snapshot_document(snapshot)
    document['native_macros'] = values
    with pytest.raises(ProtocolError, match='native macro snapshot'): load_snapshot(document)


def test_keep_stored_native_body_unblocks_service_profile_preflight_without_claiming_unknown_functions(tmp_path):
    from gillete.device_session import DeviceSession
    from gillete.focus import ProfileCoordinator
    from gillete.profiles import Configuration
    mouse, snapshot = setup()
    device = Device(MODELS[1], 'Test Naga', '2.4 GHz', 0xE8, '/test', '')
    config = Configuration()
    session = DeviceSession(device, ProfileCoordinator(config), tmp_path, None)
    session.snapshot = snapshot
    stored, _ = from_snapshot(snapshot)
    session.engine = Engine(MODELS[1], config.profiles['default'], KeyLedger(RecordingOutput()), stored=stored)
    with pytest.raises(ProtocolError, match='Stored firmware actions'): session.validate_profiles(config)
    snapshot.native_macros = native.read(mouse, snapshot)
    session.engine.stored = from_snapshot(snapshot)[0]
    session.validate_profiles(config)
    assert not mouse.writes


def test_explicit_overrides_do_not_depend_on_unused_native_bodies():
    mouse, snapshot = setup()
    snapshot.native_macros = native.read(mouse, snapshot)
    profile = Profile('override', 'Override', Layers(normal={c: Action('keys', keys=('KEY_A',))
                                                          for c in ('side_11', 'side_12')}))
    assert native.required_ids(snapshot, [Profile('stored', 'Stored')]) == {7}
    assert native.required_ids(snapshot, [profile]) == set()
    mouse.macros.clear()
    queries = len(mouse.reads)
    native.verify(mouse, snapshot, set())
    assert len(mouse.reads) == queries and not mouse.writes


def test_software_acceptance_comparison_includes_captured_native_bodies():
    from gillete.validation_plan import assert_unchanged
    mouse, snapshot = setup()
    snapshot.native_macros = native.read(mouse, snapshot)
    after = deepcopy(snapshot)
    after.native_macros.clear()
    with pytest.raises(RuntimeError, match='native_macros changed'): assert_unchanged(snapshot, after)


def test_optional_inspection_failure_preserves_bindings_and_cannot_publish_partial_bodies(monkeypatch):
    mouse, snapshot = setup()
    original = deepcopy(snapshot.records)
    execute = mouse.execute
    def inspection_query(command):
        if (command.category, command.operation) == (7, 0x80): return b'\0\x80'
        if (command.category, command.operation) == (2, 0xB0): return b'\1\0'
        return execute(command)
    mouse.execute = inspection_query
    monkeypatch.setattr(hardware, 'transport', lambda _: mouse)
    device = Device(MODELS[1], 'Test Naga', '2.4 GHz', 0xE8, '/test', '')
    def failed(*args): raise DeviceUnavailable('Macro getter timed out')
    monkeypatch.setattr(native, 'read', failed)
    inspected = hardware.inspect(device)
    assert inspected.records == original and inspected.native_macros == {}
    assert 'timed out' in inspected.metadata['native_macro_error'] and not mouse.writes


def test_keep_stored_native_macro_runs_once_and_cancels_with_balanced_output():
    async def check():
        mouse, snapshot = setup()
        snapshot.native_macros = native.read(mouse, snapshot)
        stored, _ = from_snapshot(snapshot)
        output = RecordingOutput()
        engine = Engine(MODELS[1], Profile('stored', 'Stored'), KeyLedger(output), stored=stored)
        await engine.press('side_12')
        await engine.release('side_12')
        await asyncio.sleep(.01)
        assert output.events == [('key', ecodes.KEY_F24, 1)]
        await engine.cancel()
        assert output.events == [('key', ecodes.KEY_F24, 1), ('key', ecodes.KEY_F24, 0)]
        assert not engine.macros.jobs and not engine.ledger.holders
        await engine.press('side_12')
        await engine.release('side_12')
        await asyncio.gather(*engine.macros.jobs.values())
        assert output.events[-2:] == [('key', ecodes.KEY_F24, 1), ('key', ecodes.KEY_F24, 0)]
        assert not mouse.writes
    asyncio.run(check())
