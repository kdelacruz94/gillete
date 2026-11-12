import asyncio
import time

from evdev import ecodes
import pytest

from gillete import hardware, wired_backend as backend, wired_probe as wired
from gillete.device_action_support import support
from gillete.device_session import DeviceSession
from gillete.driver_mode import ModeLease
from gillete.focus import ProfileCoordinator
from gillete.hardware import read_journal
from gillete.hid import CONFIG_INTERFACE, READ_CONFIG_INTERFACE, ReadOnlyHID
from gillete.macros import RecordingOutput
from gillete.model import Action, Layers, MODEL_CONTROLS, MODELS, Profile
from gillete.onboard import durable_json
from gillete.profile_from_mouse import MouseProfileDraft
from gillete.profiles import Configuration
from gillete.protocol import Command, ProtocolError
from gillete.wired_probe import WiredQueryHID
from test_wired_capture import environment


@pytest.fixture
def connected(environment, monkeypatch):
    _,device,mouse,report,directory=environment
    for entry in report['descriptors'].values(): entry['hid_driver']='hid-generic'
    monkeypatch.setattr(backend,'discover',lambda:[device])
    monkeypatch.setattr(hardware,'discover',lambda:[device])
    monkeypatch.setattr(wired,'WiredQueryHID',WiredQueryHID)
    return device,mouse,report,directory


def test_ordinary_snapshot_and_copy_are_read_only_without_enabling_onboard_transport(connected):
    device,mouse,_,_=connected
    snapshot=hardware.inspect(device)
    assert snapshot.product==0xE7 and len(snapshot.records)==50
    assert snapshot.metadata=={'firmware':'01010000'} and snapshot.native_macros=={}
    profile=MouseProfileDraft(snapshot).profile('copy','Wired mouse')
    assert set(profile.overrides)=={MODELS[1]} and not mouse.writes
    assert READ_CONFIG_INTERFACE[0xE7]=='00' and 0xE7 not in CONFIG_INTERFACE
    with pytest.raises(ProtocolError,match='needs validation'): hardware.transport(device)


@pytest.mark.parametrize('changed',['descriptor','driver','usb-driver','product','model','missing'])
def test_unverified_descriptor_driver_or_identity_is_rejected_before_queries(connected,monkeypatch,changed):
    device,mouse,report,_=connected
    before=len(mouse.commands)
    if changed=='descriptor': report['descriptors']['01']['raw']+='00'
    elif changed=='driver': report['descriptors']['01']['hid_driver']='razermouse'
    elif changed=='usb-driver': report['descriptors']['00']['usb_driver']='other'
    elif changed=='product': device.product_id=0xE8
    elif changed=='model': device.model=MODELS[0]
    else: monkeypatch.setattr(backend,'discover',lambda:[])
    with pytest.raises((OSError,ProtocolError)): backend.inspect_device(device)
    assert not mouse.writes and len(mouse.commands)==before


def test_new_firmware_and_untested_slots_cannot_be_read_as_supported(connected,monkeypatch):
    device,mouse,_,_=connected
    exchange=ReadOnlyHID._exchange
    def replaced(io,command):
        if (command.category,command.operation)==(0,0x81): return bytes.fromhex('01020000')
        return exchange(io,command)
    monkeypatch.setattr(ReadOnlyHID,'_exchange',replaced)
    with pytest.raises(ProtocolError,match='validated firmware'): backend.inspect_device(device)
    for bank in (2,True,False,'1'):
        with pytest.raises(ProtocolError,match='slot1'): backend.inspect_device(device,bank)
    assert not mouse.writes


def test_normal_runtime_mode_lease_pins_serial_and_rejects_all_saved_state_commands(connected):
    device,mouse,_,directory=connected
    adapter=backend.Backend(directory/'state')
    with adapter.transport(device) as io:
        assert io.expected_serial=='wired-test'
        with ModeLease(io,adapter.state/'mode-owned.json'):
            for command in (Command(2,0x0C,bytes(10)),Command(4,5,bytes(7)),Command(6,8,bytes(6)),
                            Command(0,5,b'\1'),Command(2,0x30,b'\1\0'),Command(5,4,b'\1')):
                with pytest.raises(ProtocolError): io._exchange(command)
    assert [c.payload for c in mouse.writes]==[b'\3\0',bytes(2)]
    assert read_journal(adapter.state/'mode-owned.json')['status']=='normal-mode-restored'


@pytest.mark.parametrize('kind',['device-settings','device-setting','native-macro-profile-transaction',None])
def test_wired_write_and_recovery_entry_points_fail_before_any_transport_open(connected,kind):
    device,mouse,_,directory=connected
    snapshot=hardware.inspect(device)
    count=len(mouse.commands)
    path=directory/'recovery.json'
    durable_json(path,{'version':1,'kind':kind})
    for call in (lambda:hardware.apply(device,snapshot,Profile('x','X'),path),
                 lambda:hardware.apply_settings(device,snapshot,None,path),
                 lambda:hardware.restore(device,path)):
        with pytest.raises(ProtocolError,match='[Ww]ired'): call()
    assert len(mouse.commands)==count and not mouse.writes


def test_owned_mode_recovery_is_idempotent_and_cannot_claim_another_active_journal(connected):
    device,mouse,_,directory=connected
    snapshot=hardware.inspect(device)
    path=directory/'state/mode-owned.json'
    document={'version':1,'kind':'driver-mode','product':0xE7,'serial':snapshot.serial,
              'before':'0000','status':'driver-mode-active'}
    durable_json(path,document)
    mouse.mode=b'\3\0'
    assert hardware.restore(device,path)['status']=='normal-mode-restored'
    hardware.restore(device,path)
    assert [c.payload for c in mouse.writes]==[bytes(2)]
    other=path.parent/'mode-other.json'
    durable_json(other,document)
    mouse.mode=b'\3\0'
    with pytest.raises(ProtocolError,match='not the active owned lease'): hardware.restore(device,path)
    assert len(mouse.writes)==1 and mouse.mode==b'\3\0'


@pytest.mark.parametrize('action',[Action('dpi',target='up'),Action('device',target='wheel_mode_cycle'),
                                 Action('device',target='onboard_profile_cycle')])
def test_setting_actions_are_explicitly_unavailable_for_wired_software_profiles(connected,action):
    device,_,_,_=connected
    result=support(action,device.model,hardware.inspect(device))
    assert result.available is False and 'Wired' in result.message


def test_default_service_selects_wired_adapter_and_cleans_up_real_mode_lease(connected,monkeypatch):
    import gillete.device_session as sessions
    device,mouse,_,directory=connected
    class Output(RecordingOutput):
        def __init__(self,*args):
            super().__init__();self.keymap=self;self.closed=False
        async def prepare_keyboard(self): pass
        async def restore_keyboard(self): pass
        async def watch(self): await asyncio.Event().wait()
        def close(self): self.closed=True
    monkeypatch.setattr(sessions,'UInputOutput',Output)
    monkeypatch.setattr(DeviceSession,'open_inputs',lambda _:None)
    profile=Profile('default','Default',Layers(normal={c:Action('keys',keys=('KEY_A',)) for c in MODEL_CONTROLS[MODELS[1]]}))
    coordinator=ProfileCoordinator(Configuration(profiles={'default':profile}))
    coordinator.available=True
    async def play():
        session=DeviceSession(device,coordinator,directory/'state',None)
        assert isinstance(session.hardware,backend.Backend)
        task=asyncio.create_task(session.run())
        try:
            for _ in range(200):
                if session.ready or task.done(): break
                await asyncio.sleep(.001)
            assert session.ready,session.error
            frame=session.hardware.decode(device.model,'02',bytes.fromhex('00001e0000000000'))
            await session.frames.put((time.monotonic(),session.engine.generation,frame))
            for _ in range(50):
                if session.output.events: break
                await asyncio.sleep(.001)
            assert session.output.events==[('key',ecodes.KEY_A,1)]
        finally:
            session.stop_requested.set()
            await task
        assert not session.error and session.output.closed and not session.engine.ledger.holders
        assert session.output.events==[('key',ecodes.KEY_A,1),('key',ecodes.KEY_A,0)]
        assert session.lease.document['status']=='normal-mode-restored'
    asyncio.run(play())
    assert [c.payload for c in mouse.writes]==[b'\3\0',bytes(2)]
