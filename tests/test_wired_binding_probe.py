import pytest

from gillete import wired_binding_probe as probe
from gillete.hardware import read_journal
from gillete.hid import ReadOnlyHID
from gillete.protocol import Command, ProtocolError
from test_wired_backend import connected
from test_wired_capture import environment


@pytest.fixture
def experiment(connected,monkeypatch):
    device,mouse,_,directory=connected
    functions={0:bytes.fromhex('0201001e000000'),1:bytes.fromhex('0201001f000000')}
    low=ReadOnlyHID._exchange
    mouse.lose_binding_ack=False
    def exchange(io,command):
        if (command.category,command.operation)==(2,0x8C) and command.payload[1]==0x4B:
            return command.payload[:2]+b'\0'+functions[command.payload[2]]
        if (command.category,command.operation)==(2,0x0C):
            mouse.writes.append(command)
            functions[command.payload[2]]=command.payload[3:]
            if mouse.lose_binding_ack:
                mouse.lose_binding_ack=False
                raise TimeoutError('Binding applied but reply lost')
            return command.payload
        return low(io,command)
    monkeypatch.setattr(ReadOnlyHID,'_exchange',exchange)
    monkeypatch.setattr(probe,'socket_path',lambda:directory/'absent.sock')
    directory=directory.parent/'binding-proposal'
    probe.prepare(directory)
    prepared=read_journal(directory/'prepared.json')
    root=directory/'run';root.mkdir()
    io=probe.TestHID('/dev/hidraw-test',prepared,root/'binding.json')
    return device,mouse,functions,prepared,root,io


def test_first_wired_binding_change_observation_and_exact_restoration(experiment):
    _,mouse,functions,prepared,root,io=experiment
    original=functions.copy()
    def ready(): assert functions[0]==probe.TARGET and functions[1]==original[1]
    result=probe.exercise(io,prepared,root,lambda:{'f24_down':True,'f24_up':True},ready=ready)
    assert result['physical_press_observed'] and result['original_binding_restored'] and result['saved_state_unchanged']
    assert functions==original
    assert [c.payload[3:] for c in mouse.writes]==[probe.TARGET,original[0]]
    assert read_journal(root/'binding.json')['power_cycle_verified'] is False
    probe.restore(io,prepared,root/'binding.json')
    assert len(mouse.writes)==2
    with pytest.raises(ProtocolError,match='write phase'):
        io._exchange(Command(2,0x0C,b'\1\x4b\0'+probe.TARGET))


@pytest.mark.parametrize('failure',['timeout','lost-ack','interrupted'])
def test_failed_or_uncertain_test_restores_its_original_binding(experiment,failure):
    _,mouse,functions,prepared,root,io=experiment
    original=functions[0]
    if failure=='lost-ack': mouse.lose_binding_ack=True
    def observe():
        if failure=='interrupted': raise KeyboardInterrupt
        raise TimeoutError('No F24 press')
    with pytest.raises((TimeoutError,KeyboardInterrupt)):
        probe.exercise(io,prepared,root,observe)
    assert functions[0]==original and len(mouse.writes)==2
    assert read_journal(root/'result.json')['saved_state_unchanged']


@pytest.mark.parametrize('command',[Command(0,4,b'\3\0'),Command(4,5,bytes(7)),Command(6,8,bytes(6)),
    Command(2,0x0C,b'\1\x4a\0'+probe.TARGET),Command(2,0x0C,b'\1\x4b\1'+probe.TARGET)])
def test_probe_rejects_every_other_setter_control_or_layer(experiment,command):
    _,mouse,_,_,_,io=experiment
    with pytest.raises(ProtocolError): io._exchange(command)
    assert not mouse.writes


def test_missing_original_journal_and_stale_snapshot_make_no_write(experiment):
    _,mouse,functions,prepared,root,io=experiment
    with pytest.raises((OSError,ProtocolError)): io._exchange(Command(2,0x0C,b'\1\x4b\0'+probe.TARGET))
    functions[1]=bytes.fromhex('02020020000000')
    with pytest.raises(ProtocolError,match='changed since preparation'):
        probe.exercise(io,prepared,root,lambda:None)
    assert not mouse.writes


@pytest.mark.parametrize('field',['target','location','seconds','version'])
def test_changed_proposal_scope_is_rejected_before_opening_the_transport(experiment,field):
    _,mouse,_,prepared,root,_=experiment
    prepared[field]={'target':'02020072000000','location':{'bank':1,'control':0x4A,'layer':0},
                     'seconds':300,'version':True}[field]
    with pytest.raises(ProtocolError): probe.TestHID('/dev/hidraw-test',prepared,root/'binding.json')
    assert not mouse.writes


def test_external_dpi_change_is_preserved_while_the_test_binding_is_restored(experiment):
    _,mouse,functions,prepared,root,io=experiment
    original=functions[0]
    def observe():
        mouse.dpi=bytes.fromhex('0104b004b00000')
        return {'f24_down':True,'f24_up':True}
    with pytest.raises(ProtocolError,match='cleanup differs'): probe.exercise(io,prepared,root,observe)
    result=read_journal(root/'result.json')
    assert result['original_binding_restored'] and not result['saved_state_unchanged']
    assert functions[0]==original and mouse.dpi==bytes.fromhex('0104b004b00000')
    assert all((c.category,c.operation)==(2,0x0C) for c in mouse.writes)


def test_external_target_edit_is_never_overwritten_by_cleanup(experiment):
    _,mouse,functions,prepared,root,io=experiment
    other=bytes.fromhex('02020021000000')
    def observe():
        functions[0]=other
        return {'f24_down':True,'f24_up':True}
    with pytest.raises(ProtocolError,match='changed outside'): probe.exercise(io,prepared,root,observe)
    assert functions[0]==other and len(mouse.writes)==1
    assert not read_journal(root/'result.json')['original_binding_restored']
