import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from gillete import guided_service as guided
from gillete import wired_acceptance as acceptance
from gillete import wired_probe as wired
from gillete.device_session import DeviceSession
from gillete.driver_mode import ModeLease
from gillete.focus import ProfileCoordinator
from gillete.hardware import read_journal, transport
from gillete.hid import CONFIG_INTERFACE, ReadOnlyHID
from gillete.model import MODEL_CONTROLS, MODELS
from gillete.onboard import durable_json
from gillete.profiles import ProfileStore
from gillete.protocol import Command, ProtocolError
from gillete.reports import decode_wired
from gillete.wired_probe import WiredQueryHID
from test_wired_capture import environment


TRACE = json.loads((Path(__file__).parent / 'fixtures/naga_v3_wired_controls.json').read_text())


@pytest.fixture
def accepted(environment, monkeypatch):
    _, device, mouse, inspection, directory = environment
    expected = deepcopy(inspection['routes'][0]['before'])
    proof = {'version':1, 'kind':'wired-input-proof', 'inspection':inspection,
        'verification':{'normal_mode_verified':True,'stored_state_unchanged':True,
            'before':expected, 'after':deepcopy(expected), 'transport_health':{'setting_commands':2}},
        'mode':{'version':1,'kind':'driver-mode','product':0xE7,'serial':expected['serial'],
                'before':'0000','status':'normal-mode-restored'}, 'capture':deepcopy(TRACE)}
    monkeypatch.setattr(acceptance, 'discover', lambda: [device])
    # Use the real getter guard over the environment's fake low-level exchange.
    monkeypatch.setattr(wired, 'WiredQueryHID', WiredQueryHID)
    test_dir = directory.parent / 'software'
    hardware = acceptance.Hardware(proof, test_dir)
    return device, mouse, proof, test_dir, hardware


def test_live_excerpt_replays_all_controls_and_cross_interface_combinations():
    result = acceptance.coverage(TRACE)
    assert result['controls'] == sorted(MODEL_CONTROLS[MODELS[1]])
    assert result['combinations'] == [['left_click','side_1'],['ring_finger','side_12']]
    assert result['held'] == [] and result['records'] == 58


@pytest.mark.parametrize('problem', ['missing-control','missing-release','missing-combination','time','receiver-report'])
def test_incomplete_or_incompatible_capture_cannot_admit_software(accepted, problem):
    _, _, proof, directory, _ = accepted
    if problem == 'missing-control':
        proof['capture']['events'] = [e for e in proof['capture']['events'] if not e['raw'].startswith('0421')]
    elif problem == 'missing-release': proof['capture']['events'][-1]['raw'] = '0100000000000000'
    elif problem == 'missing-combination':
        proof['capture']['events'] = [e for e in proof['capture']['events'] if e['t'] < 24]
    elif problem == 'time': proof['capture']['events'][-1]['t'] = float('nan')
    else: proof['capture']['events'][0] = {'t':0,'interface':'01','raw':'08'+('00'*15)}
    with pytest.raises(ProtocolError): acceptance.Hardware(proof, directory)


@pytest.mark.parametrize('problem', ['mode','settings','snapshot','setter-count','descriptor','firmware','serial','version'])
def test_restoration_and_exact_capture_identity_are_required(accepted, problem):
    _, mouse, proof, directory, _ = accepted
    if problem == 'mode': proof['mode']['status'] = 'driver-mode-active'
    elif problem == 'settings': proof['verification']['stored_state_unchanged'] = False
    elif problem == 'snapshot': proof['verification']['after']['settings']['dpi'] = 'changed'
    elif problem == 'setter-count': proof['verification']['transport_health']['setting_commands'] = 3
    elif problem == 'descriptor': proof['capture']['descriptors']['00'] += '00'
    elif problem == 'firmware': proof['inspection']['routes'][0]['before']['firmware'] = '01020000'
    elif problem == 'serial': proof['mode']['serial'] = 'another'
    else: proof['version'] = True
    with pytest.raises(ProtocolError): acceptance.Hardware(proof, directory)
    assert not mouse.writes


def test_preparation_is_read_only_and_cannot_enable_the_normal_backend(accepted, monkeypatch):
    device, mouse, proof, directory, hardware = accepted
    monkeypatch.setattr(acceptance, 'proof_from', lambda _: proof)
    monkeypatch.setattr(guided, 'socket_path', lambda: directory / 'absent.sock')
    def forbidden(*args, **kwargs): raise AssertionError('No software activation during prepare')
    monkeypatch.setattr(acceptance, 'Daemon', forbidden)
    acceptance.prepare(directory.parent / 'capture', directory)
    plan = read_journal(directory / 'prepared.json')
    assert plan['snapshot']['product'] == 0xE7 and len(plan['coverage']['steps']) == 50
    assert plan['wired_proof'] == proof and len(plan['snapshot']['records']) == 50
    assert not mouse.writes and not (directory / 'run').exists()
    assert directory.stat().st_mode & 0o777 == 0o700
    assert 0xE7 not in CONFIG_INTERFACE
    monkeypatch.setattr('gillete.hardware.discover', lambda: [device])
    with pytest.raises(ProtocolError, match='needs validation'): transport(device)
    loaded = acceptance.prepared_hardware(directory)
    assert loaded.expected['serial'] == hardware.expected['serial']


def test_isolated_transport_restores_mode_and_rejects_settings_even_during_an_owned_lease(accepted):
    device, mouse, _, _, hardware = accepted
    io = hardware.transport(device)
    with io:
        with ModeLease(io, hardware.state / 'mode-test.json'):
            for command in (Command(4,5,bytes(7)),Command(2,0x0C,bytes(10)),Command(6,8,bytes(6))):
                with pytest.raises(ProtocolError): io._exchange(command)
    assert [c.payload for c in mouse.writes] == [b'\3\0',b'\0\0']
    assert read_journal(hardware.state / 'mode-test.json')['status'] == 'normal-mode-restored'
    assert io.execute(Command(0,0x84,bytes(2))) == bytes(2)


def test_unowned_or_ambiguous_journals_cannot_change_modes(accepted):
    device, mouse, proof, _, hardware = accepted
    io = hardware.transport(device)
    with pytest.raises(ProtocolError, match='Exactly one'): io._exchange(Command(0,4,b'\3\0'))
    document = deepcopy(proof['mode']); document['status'] = 'prepared'
    for name in ('mode-one.json','mode-two.json'): durable_json(hardware.state/name,document)
    with pytest.raises(ProtocolError, match='Exactly one'): io._exchange(Command(0,4,b'\3\0'))
    assert not mouse.writes


def test_receiver_or_other_model_is_rejected_before_input_ownership(accepted, monkeypatch):
    device, mouse, _, _, hardware = accepted
    receiver = deepcopy(device); receiver.product_id = 0xE8
    monkeypatch.setattr(acceptance, 'discover', lambda:[device,receiver])
    with pytest.raises(ProtocolError, match='disconnect its receiver'): hardware.inspect(device)
    other = deepcopy(device); other.product_id = 0xB4; other.model = MODELS[0]
    with pytest.raises(ProtocolError, match='another mouse'): hardware.session(other, None, None, None)
    assert not mouse.writes


def test_prepared_snapshot_rejects_dpi_drift_before_opening_a_window(accepted, monkeypatch):
    device, mouse, proof, directory, hardware = accepted
    monkeypatch.setattr(acceptance, 'proof_from', lambda _: proof)
    monkeypatch.setattr(guided, 'socket_path', lambda: directory / 'absent.sock')
    acceptance.prepare(directory.parent/'capture', directory)
    mouse.dpi = bytes.fromhex('01064006400000')
    async def forbidden(*args, **kwargs): raise AssertionError('No subprocess after stale preflight')
    monkeypatch.setattr(guided.asyncio,'create_subprocess_exec',forbidden)
    with pytest.raises(RuntimeError, match='settings'):
        asyncio.run(guided.run(directory,30,hardware=hardware))
    assert not mouse.writes and not (directory/'run').exists()


def test_session_factory_keeps_the_wired_adapter_and_report_layout(accepted):
    device, _, _, directory, hardware = accepted
    config = ProfileStore(directory/'profiles.json')
    session = hardware.session(device,ProfileCoordinator(config.read()),hardware.state,None,trace_controls=True)
    assert isinstance(session,DeviceSession) and session.hardware is hardware
    assert session.inspect_mouse().product == 0xE7
    assert session.hardware.decode(MODELS[1],'02',bytes.fromhex('00002e0000000000')).controls == {'side_12'}
    for raw in (bytes.fromhex('08000000000000000000000000000000'),bytes(9)):
        with pytest.raises(ProtocolError): decode_wired(MODELS[1],'01',raw)
    assert 'gillete.wired_acceptance' in hardware.daemon_command(directory/'run/profiles.json','controls')


def test_captured_frames_route_into_shifted_keys_and_release_every_output(accepted):
    from gillete.control_trace import ControlTrace
    from gillete.control_validation import build
    from gillete.engine import Engine
    from gillete.macros import KeyLedger, RecordingOutput
    from gillete.runtime import Router
    from gillete.stored_actions import from_snapshot
    device, _, _, _, hardware = accepted
    before = hardware.inspect(device)
    config, _ = build(before)
    stored, _ = from_snapshot(before)
    output, trace = RecordingOutput(), ControlTrace()
    engine = Engine(MODELS[1],config.profiles['validation'],KeyLedger(output),stored=stored)
    router = Router(engine,trace=trace)
    async def replay():
        for event in TRACE['events']:
            frame = hardware.decode(MODELS[1],event['interface'],bytes.fromhex(event['raw']))
            if frame is not None: await router.feed(frame)
        assert not router.held and not engine.pressed and not engine.ledger.holders
        await router.close()
    asyncio.run(replay())
    entries = trace.document(engine)['entries']
    assert {(e['control'],e['direction']) for e in entries} >= {
        (control,direction) for control in MODEL_CONTROLS[MODELS[1]] for direction in ('down','up')}
    assert any(e['control']=='side_12' and e['direction']=='down' and e['shifted'] for e in entries)
    assert any(e['control']=='side_12' and e['direction']=='up' and e['shifted'] for e in entries)


def test_daemon_supervision_uses_the_isolated_factory(accepted, monkeypatch):
    import gillete.service as service
    from gillete.service import Daemon
    device, _, _, directory, hardware = accepted
    daemon = Daemon(ProfileStore(directory/'profiles.json'),session_factory=hardware.session,trace_controls=True)
    daemon.coordinator.available = daemon.sleep_monitor_ready = True
    daemon.requested.add(MODELS[1])
    monkeypatch.setattr(service,'discover',lambda:[device])
    monkeypatch.setattr(service,'journal_directory',lambda:hardware.state)
    seen=[]
    async def inert(session): seen.append(session)
    monkeypatch.setattr(DeviceSession,'run',inert)
    async def supervise():
        await daemon.supervise_once()
        await asyncio.gather(*daemon.tasks.values())
    asyncio.run(supervise())
    assert len(seen)==1 and seen[0].hardware is hardware and seen[0].input_trace is not None


def test_wrong_daemon_configuration_or_journal_root_cannot_activate_the_mouse(accepted, monkeypatch):
    device, mouse, proof, directory, hardware = accepted
    monkeypatch.setattr(acceptance,'proof_from',lambda _:proof)
    monkeypatch.setattr(guided,'socket_path',lambda:directory/'absent.sock')
    acceptance.prepare(directory.parent/'capture',directory)
    def forbidden(*args,**kwargs): raise AssertionError('No daemon for an unrelated configuration')
    monkeypatch.setattr(acceptance,'Daemon',forbidden)
    with pytest.raises(SystemExit):
        acceptance.main(['daemon','--directory',str(directory),'--config',str(directory/'other.json')])
    with pytest.raises(ProtocolError,match='isolated journal'):
        hardware.session(device,None,directory/'wrong-state',None)
    assert not mouse.writes


def test_explicit_recovery_after_replug_restores_only_the_owned_mode(accepted, monkeypatch):
    device, mouse, proof, directory, hardware = accepted
    monkeypatch.setattr(acceptance,'proof_from',lambda _:proof)
    monkeypatch.setattr(guided,'socket_path',lambda:directory/'absent.sock')
    monkeypatch.setattr(acceptance,'socket_path',lambda:directory/'absent.sock')
    acceptance.prepare(directory.parent/'capture',directory)
    lease = deepcopy(proof['mode']); lease['status']='driver-mode-active'
    durable_json(hardware.state/'mode-interrupted.json',lease)
    mouse.mode=b'\3\0'
    device.usb_path += '-replugged'
    current=deepcopy(proof['inspection']['descriptors'])
    for number,node in current.items(): node['node']=f'/dev/hidraw{30+int(number)}'
    monkeypatch.setattr(wired,'descriptors',lambda _:current)
    with pytest.raises(ProtocolError): hardware.connected(0xE7)
    acceptance.recover(directory)
    assert [c.payload for c in mouse.writes] == [bytes(2)]
    assert read_journal(directory/'run/recovery.json')['stored_state_unchanged']
    acceptance.recover(directory)
    assert len(mouse.writes)==1


@pytest.mark.parametrize('changed',['firmware','serial'])
def test_opening_a_changed_device_rejects_mode_commands_before_creating_a_lease(accepted, monkeypatch, changed):
    device, mouse, _, _, hardware = accepted
    exchange=ReadOnlyHID._exchange
    def replaced(io,command):
        if changed=='firmware' and (command.category,command.operation)==(0,0x81):
            return bytes.fromhex('01020000')
        if changed=='serial' and (command.category,command.operation)==(0,0x82):
            return b'another-unit'+bytes(10)
        return exchange(io,command)
    monkeypatch.setattr(ReadOnlyHID,'_exchange',replaced)
    with pytest.raises(ProtocolError,match='firmware or identity changed'):
        with hardware.transport(device) as io:
            ModeLease(io,hardware.state/'mode-test.json').enter()
    assert not mouse.writes and not hardware.state.exists()


def test_recovery_preserves_external_dpi_changes_and_reports_the_difference(accepted, monkeypatch):
    _, mouse, proof, directory, hardware = accepted
    monkeypatch.setattr(acceptance,'proof_from',lambda _:proof)
    monkeypatch.setattr(guided,'socket_path',lambda:directory/'absent.sock')
    monkeypatch.setattr(acceptance,'socket_path',lambda:directory/'absent.sock')
    acceptance.prepare(directory.parent/'capture',directory)
    lease=deepcopy(proof['mode']);lease['status']='driver-mode-active'
    durable_json(hardware.state/'mode-interrupted.json',lease)
    mouse.mode=b'\3\0';mouse.dpi=bytes.fromhex('0104b004b00000')
    with pytest.raises(RuntimeError,match='settings changed'): acceptance.recover(directory)
    assert mouse.dpi==bytes.fromhex('0104b004b00000') and mouse.mode==bytes(2)
    assert [c.payload for c in mouse.writes]==[bytes(2)]
    assert not (directory/'run/recovery.json').exists()
