import asyncio
from copy import deepcopy

from evdev import ecodes
import pytest

from gillete import stored_native as native
from gillete.engine import Engine
from gillete.focus import ProfileCoordinator
from gillete.hardware import load_snapshot, snapshot_document
from gillete.macros import KeyLedger, MacroRunner, RecordingOutput
from gillete.model import Action, ConfigurationError, MODELS
from gillete.native_macro import compile_macro
from gillete.onboard import Location
from gillete.profile_from_mouse import MouseProfileDraft
from gillete.profiles import Configuration, ProfileStore, Window
from gillete.protocol import ProtocolError
from gillete.stored_actions import from_snapshot
from test_stored_native import setup


# Exact keyboard event shapes used in the accepted combined native experiment:
# Ctrl down;20; K down;40; K up;20; Ctrl up;80; M down;40; M up.
CHORD = bytes.fromhex('01e01114010e1128020e111402e01150011011280210')
# F24 down;40; F24 up;150. The delay belongs to every iteration, including last.
COUNTED = bytes.fromhex('0173112802731196')
ONCE = bytes.fromhex('017311280273')


def combined():
    mouse, snapshot = setup()
    mouse.macros.clear()
    for control, layer, identifier, count, body in (
            (0x4B,0,7,1,CHORD), (0x4B,1,8,3,COUNTED),
            (0x4A,0,9,1,ONCE), (0x4A,1,9,1,ONCE)):
        mouse.macros[identifier] = {'data':bytearray(body),'metadata':bytearray(250)}
        mouse.functions[1,control,layer] = bytes((3,3,0,identifier,count,0,0))
        snapshot.records[Location(1,control,layer)] = mouse.read_binding_record(1,control,layer)
    snapshot.native_macros = native.read(mouse,snapshot)
    return mouse,snapshot


def test_combined_shapes_read_shared_objects_and_copy_exact_actions_into_local_profiles(tmp_path):
    mouse,snapshot = combined()
    stored,unknown = from_snapshot(snapshot)
    assert not unknown and snapshot.native_macros == {7:CHORD.hex(),8:COUNTED.hex(),9:ONCE.hex()}
    chord,counted = stored['side_12',False],stored['side_12',True]
    assert [s.key for s in chord.steps if s.kind=='down'] == ['KEY_LEFTCTRL','KEY_K','KEY_M']
    assert [s.milliseconds for s in chord.steps if s.kind=='wait'] == [20,40,20,80,40]
    assert (counted.playback,counted.count,counted.interval_ms)==('count',3,0)
    assert counted.steps[-1].milliseconds==150
    assert stored['side_11',False]==stored['side_11',True]
    assert load_snapshot(snapshot_document(snapshot))==snapshot
    profile=MouseProfileDraft(snapshot).profile('copy','Copied native sequences')
    store=ProfileStore(tmp_path/'profiles.json')
    config=Configuration()
    config.profiles[profile.id]=profile
    store.save(config,expected_revision=0)
    copied=store.read().profiles[profile.id]
    assert copied.resolve(MODELS[1],'side_12',False)==chord
    assert copied.resolve(MODELS[1],'side_12',True)==counted
    from gillete.shortcuts import describe
    assert describe(counted)=='Macro · 4 steps · 3 times'
    assert compile_macro(counted).data==COUNTED
    assert compile_macro(counted).binding(8)==bytes.fromhex('03030008030000')
    assert not mouse.writes


@pytest.mark.parametrize('count',[1,2,3,255])
def test_count_byte_is_retained_without_adding_another_repeat_gap(count):
    _,snapshot=combined()
    binding=bytes((3,3,0,8,count,0,0))
    assert native.reference(binding)==8
    action=native.action(snapshot,binding)
    assert action.steps[-1].milliseconds==150
    assert action.playback==('once' if count==1 else 'count')
    if count>1: assert action.count==count and action.interval_ms==0


def test_counted_chords_and_multi_press_bodies_stay_unresolved():
    _,snapshot=combined()
    for body in (CHORD,ONCE+ONCE):
        snapshot.native_macros[8]=body.hex()
        assert native.action(snapshot,bytes.fromhex('03030008030000')) is None
        assert native.action(snapshot,bytes.fromhex('03030008010000')) is not None


@pytest.mark.parametrize('body,count,expected_time,expected_edges',[
    (CHORD,1,.200,[(0,ecodes.KEY_LEFTCTRL,1),(.020,ecodes.KEY_K,1),(.060,ecodes.KEY_K,0),
                  (.080,ecodes.KEY_LEFTCTRL,0),(.160,ecodes.KEY_M,1),(.200,ecodes.KEY_M,0)]),
    (COUNTED,3,.570,[(0,ecodes.KEY_F24,1),(.040,ecodes.KEY_F24,0),
                    (.190,ecodes.KEY_F24,1),(.230,ecodes.KEY_F24,0),
                    (.380,ecodes.KEY_F24,1),(.420,ecodes.KEY_F24,0)])])
def test_playback_timeline_preserves_stored_delays_including_the_last_gap(monkeypatch,body,count,expected_time,expected_edges):
    _,snapshot=combined()
    snapshot.native_macros[8]=body.hex()
    action=native.action(snapshot,bytes((3,3,0,8,count,0,0)))
    now,edges=[0],[]
    real_sleep=asyncio.sleep
    async def advance(seconds):
        now[0]+=seconds
        await real_sleep(0)
    class Output(RecordingOutput):
        def key(self,code,value): edges.append((now[0],code,value))
    monkeypatch.setattr(asyncio,'sleep',advance)
    async def play():
        runner=MacroRunner(KeyLedger(Output()))
        await runner.start('stored',action)
        await asyncio.gather(*runner.jobs.values())
        assert not runner.ledger.holders and not runner.errors
    asyncio.run(play())
    assert now[0]==pytest.approx(expected_time)
    assert [(code,value) for _,code,value in edges]==[(code,value) for _,code,value in expected_edges]
    assert [t for t,_,_ in edges]==pytest.approx([t for t,_,_ in expected_edges])


@pytest.mark.parametrize('counted',[False,True])
def test_focus_loss_cancels_the_stored_sequence_and_does_not_resume_on_return(counted):
    async def play():
        mouse,snapshot=combined()
        if counted:
            snapshot.records[Location(1,0x4B,0)]=snapshot.records[Location(1,0x4B,1)]
        stored,_=from_snapshot(snapshot)
        config=Configuration()
        coordinator=ProfileCoordinator(config)
        output=RecordingOutput()
        engine=Engine(MODELS[1],config.profiles['default'],KeyLedger(output),stored=stored)
        await coordinator.attach(MODELS[1],engine)
        await coordinator.focus_changed(Window('0x1','target'))
        await engine.press('side_12');await engine.release('side_12')
        await asyncio.sleep(.005)
        code=ecodes.KEY_F24 if counted else ecodes.KEY_LEFTCTRL
        assert output.events==[('key',code,1)]
        await coordinator.focus_changed(Window('0x2','elsewhere'))
        assert output.events==[('key',code,1),('key',code,0)]
        assert not engine.macros.jobs and not engine.ledger.holders
        await coordinator.focus_changed(Window('0x1','target'))
        await asyncio.sleep(.005)
        assert len(output.events)==2 and not mouse.writes
        await coordinator.detach(MODELS[1])
    asyncio.run(play())


def test_changed_repeat_binding_is_rejected_even_when_the_object_bytes_match():
    mouse,snapshot=combined()
    original=deepcopy(snapshot)
    mouse.functions[1,0x4B,1]=bytes.fromhex('03030008020000')
    with pytest.raises(ProtocolError,match='assignment changed'): native.verify(mouse,snapshot)
    assert snapshot==original and not mouse.writes


def test_zero_gap_is_macro_only_and_zero_gap_loops_still_cancel():
    for kind in ('turbo','keys'):
        with pytest.raises(ConfigurationError): Action(kind,keys=('KEY_1',),interval_ms=0)
    action=Action('macro',steps=native.decode_once(ONCE).steps,playback='toggle',interval_ms=0)
    async def play():
        runner=MacroRunner(KeyLedger(RecordingOutput()))
        await runner.start('zero-gap',action)
        await asyncio.sleep(0)
        await runner.cancel('zero-gap')
        assert not runner.jobs and not runner.ledger.holders
    asyncio.run(play())
