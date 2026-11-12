from contextlib import contextmanager
import errno

import pytest

from gillete import wired_binding_replug as replug
from gillete.hardware import read_journal
from gillete.protocol import ProtocolError
from test_wired_binding_probe import experiment
from test_wired_backend import connected
from test_wired_capture import environment


def plan(experiment):
    _,mouse,functions,prepared,root,io=experiment
    prepared.update(purpose='cable-replug',power_cycle_requested=True,
                    usb_route={'product':0xE7,'usb_path':'/sys/usb1/1-2','busnum':'1','devnum':'23'})
    return mouse,functions,prepared,root,io


def loop(prepared,*,returned=None,mutate=lambda:None):
    values=iter([prepared['usb_route'],None,{'pending':True},returned or {**prepared['usb_route'],'devnum':'24'}])
    def observe():
        value=next(values)
        if value and value.get('devnum')=='24': mutate()
        return value
    return observe


@pytest.mark.parametrize('canonical',[False,True])
def test_observed_disconnect_new_enumeration_readback_and_physical_key_restore(experiment,canonical):
    mouse,functions,prepared,root,io=plan(experiment)
    original=functions[0];stages=[];opens=[]
    @contextmanager
    def opening():
        opens.append(True)
        yield io
    def mutate():
        if canonical: functions[0]=bytes.fromhex('02010073000000')
    result=replug.exercise(prepared,root,opening,loop(prepared,mutate=mutate),
        lambda:{'f24_down':True,'f24_up':True},announce=stages.append)
    assert result['status']=='cable-replug-restored' and result['usb_disconnect_observed']
    assert result['binding_retained'] and result['physical_press_observed'] and result['original_state_restored']
    assert result['binding_encoding_changed'] is canonical
    assert stages==['awaiting-cable-replug','ready-side12'] and len(opens)==3
    assert [c.payload[3:] for c in mouse.writes]==[replug.base.TARGET,original]
    assert functions[0]==original


@pytest.mark.parametrize('failure',['lost-binding','dpi','wrong-port','no-key','cancel'])
def test_failed_retention_or_key_test_restores_only_the_owned_binding(experiment,failure):
    mouse,functions,prepared,root,io=plan(experiment)
    original=functions[0]
    @contextmanager
    def opening(): yield io
    def mutate():
        if failure=='lost-binding': functions[0]=original
        if failure=='dpi': mouse.dpi=bytes.fromhex('0104b004b00000')
    def key():
        if failure=='no-key': raise TimeoutError('F24 timed out')
        return {'f24_down':True,'f24_up':True}
    returned={**prepared['usb_route'],'devnum':'24'}
    if failure=='wrong-port': returned['usb_path']='/sys/usb1/1-9'
    with pytest.raises(ProtocolError):
        replug.exercise(prepared,root,opening,loop(prepared,returned=returned,mutate=mutate),key,
                        stopped=lambda:failure=='cancel')
    result=read_journal(root/'result.json')
    assert functions[0]==original
    assert all(c.payload[:3]==b'\1\x4b\0' for c in mouse.writes)
    if failure=='dpi':
        assert not result['original_state_restored'] and mouse.dpi==bytes.fromhex('0104b004b00000')
    else: assert result['original_state_restored']


def test_getter_readiness_retries_do_not_replay_a_setter_after_uncertain_ack(experiment):
    mouse,_,prepared,root,io=plan(experiment)
    attempts=[]
    @contextmanager
    def opening():
        attempts.append(True)
        if len(attempts)<=2: raise PermissionError(errno.EACCES,'ACL not ready')
        yield io
    mouse.lose_binding_ack=True
    clock=[0]
    def wait(seconds): clock[0]+=seconds
    with pytest.raises(ProtocolError):
        replug.exercise(prepared,root,opening,loop(prepared),lambda:None,wait=wait,now=lambda:clock[0])
    assert len(attempts)==4 and len(mouse.writes)==2
    assert sum(c.payload[3:]==replug.base.TARGET for c in mouse.writes)==1
    assert read_journal(root/'result.json')['original_state_restored']


def test_same_enumeration_without_removal_cannot_count_as_retention(experiment):
    mouse,functions,prepared,root,io=plan(experiment)
    original=functions[0]
    @contextmanager
    def opening(): yield io
    clock=[0]
    def wait(seconds): clock[0]+=seconds
    with pytest.raises(ProtocolError,match='not observed'):
        replug.exercise(prepared,root,opening,lambda:prepared['usb_route'],lambda:None,
                        wait=wait,now=lambda:clock[0])
    assert functions[0]==original and len(mouse.writes)==2
    assert not read_journal(root/'result.json')['usb_disconnect_observed']
