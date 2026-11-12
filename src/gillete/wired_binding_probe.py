"""First opt-in wired binding experiment: normal side12 F24, then restore."""

import argparse
from pathlib import Path
import signal

from . import wired_backend as backend
from . import wired_probe as wired
from .compile_onboard import USAGES
from .hardware import read_journal
from .hid import BindingHID, ReadOnlyHID
from .native_macro_observer import Observer
from .onboard import Location, Programmer, durable_json
from .protocol import ProtocolError
from .service import socket_path
from .wired_transport import read_state


TARGET = bytes.fromhex('02020073000000')
WHERE = Location(1, 0x4B, 0)


def is_candidate(function):
    # Both keyboard-size forms are already decoded as the same bare F24 key.
    return function in (TARGET,bytes.fromhex('02010073000000'))


def validate(document):
    try:
        before = document['before']
        originals = {(r['bank'],r['control'],r['layer']):bytes.fromhex(r['raw']) for r in before['records']}
        if (type(document.get('version')) is not int or document['version'] != 1
                or document.get('kind') != 'wired-side12-binding-proposal'
                or document.get('target') != TARGET.hex() or document.get('location') != WHERE.json()
                or type(document.get('seconds')) is not int or document['seconds'] != 180
                or before['firmware'] != backend.FIRMWARE or before['mode'] != '0000'
                or before['assigned'] != [1] or before['active'] != 1):
            raise ValueError('Expected the verified wired firmware and sole active slot1')
        for layer in (0,1):
            raw = originals[1,0x4B,layer]
            if (raw[2] != 0 or raw[3] != 2 or raw[4] not in (1,2) or raw[6] not in USAGES.values() or raw[7:] != bytes(3)
                    or originals[0,0x4B,layer][3:] != raw[3:]):
                raise ValueError('First wired write test requires simple keyboard originals with reply flag0')
        original = originals[1,0x4B,0][3:]
        if original[2:4] == TARGET[2:4]: raise ValueError('Normal side12 is already F24; no distinct test change')
        return original
    except (KeyError,TypeError,ValueError,IndexError) as error:
        raise ProtocolError('Invalid wired binding proposal: '+str(error)) from error


class TestHID(wired.WiredQueryHID, BindingHID):
    def __init__(self,path,prepared,journal):
        super().__init__(path)
        self.original = validate(prepared)
        self.expected_serial = prepared['before']['serial']
        self.journal = journal

    def _exchange(self,command):
        if command.operation < 0x80:
            if ((command.category,command.operation) != (2,0x0C) or command.transaction != 0x1F
                    or command.payload not in (b'\1\x4b\0'+self.original,b'\1\x4b\0'+TARGET)):
                raise ProtocolError('Wired binding test permits only normal side12 F24/original writes')
            document = read_journal(self.journal)
            expected = {'bank':1,'control':0x4B,'layer':0,'before':self.original.hex(),
                        'after':TARGET.hex(),'reply_flag_before':0}
            if (type(document.get('version')) is not int or document['version'] != 1
                    or document.get('product') != wired.PRODUCT or document.get('serial') != self.expected_serial
                    or document.get('entries') != [expected]):
                raise ProtocolError('Wired binding write lacks its exact original/target journal')
            if (document.get('status') not in ('prepared','applied-readback-verified','restore-required')
                    or command.payload[3:] == TARGET and document.get('status') != 'prepared'):
                raise ProtocolError('Wired binding journal does not authorize this write phase')
        else:
            wired.validate_query(command)
        return ReadOnlyHID._exchange(self,command)


class WiredObserver(Observer):
    def __enter__(self):
        super().__enter__()
        if any((s.info.bustype,s.info.vendor,s.info.product) != (3,0x1532,wired.PRODUCT) for s in self.sources):
            self.__exit__()
            raise ProtocolError('Wired F24 input identity changed')
        return self


def selected():
    devices = [d for d in backend.discover() if d.model == 'naga_v3_pro']
    if len(devices) != 1 or devices[0].product_id != wired.PRODUCT:
        raise ProtocolError('Use only the wired V3 transport for this experiment')
    return devices[0]


def prepare(directory):
    if socket_path().exists(): raise ProtocolError('Stop software control before preparing a wired saved-binding test')
    device = selected()
    with wired.WiredQueryHID(backend.node(device)) as io:
        before = read_state(io)
    document = {'version':1,'kind':'wired-side12-binding-proposal','before':before,
                'target':TARGET.hex(),'location':WHERE.json(),'seconds':180}
    validate(document)
    directory.mkdir(parents=True,mode=0o700)
    durable_json(directory/'prepared.json',document)
    print('PREPARED: normal side12 -> F24 for up to180 seconds; original binding/settings retained. No write made.')


def restore(io,prepared,journal):
    original = validate(prepared)
    document = read_journal(journal)
    expected = {'bank':1,'control':0x4B,'layer':0,'before':original.hex(),
                'after':TARGET.hex(),'reply_flag_before':0}
    if (type(document.get('version')) is not int or document['version'] != 1
            or document.get('product') != wired.PRODUCT or document.get('serial') != prepared['before']['serial']
            or document.get('entries') != [expected]):
        raise ProtocolError('Wired binding recovery journal does not match its prepared original')
    current = io.read_binding(1,0x4B,0)
    active = io.read_binding(0,0x4B,0)
    if current == active == original: return
    if (current != original and not is_candidate(current) or active != original and not is_candidate(active)
            or document.get('status') in ('restored-readback-verified','rolled-back-readback-verified')):
        raise ProtocolError('Wired side12 changed outside this active test; recovery retained without overwriting it')
    Programmer(io,journal,prepared['before']['serial'],set(prepared['before']['controls'])).restore()


def exercise(io,prepared,root,observe,*,ready=lambda:None):
    validate(prepared)
    before = prepared['before']
    if read_state(io) != before:
        raise ProtocolError('Wired state changed since preparation; no binding write admitted')
    journal = root/'binding.json'
    result = {'version':1,'kind':'wired-side12-binding-result','physical_press_observed':False,
              'original_binding_restored':False,'saved_state_unchanged':False,'normal_mode_verified':False}
    try:
        Programmer(io,journal,before['serial'],set(before['controls'])).apply({WHERE:TARGET})
        candidate = read_state(io)
        expected = {**before,'records':[{**r,'raw':(bytes.fromhex(r['raw'])[:3]+TARGET).hex()}
                    if r['control']==0x4B and r['layer']==0 else r for r in before['records']]}
        if candidate != expected:
            raise ProtocolError('Stored/active F24 readback or protected state differs; restoring original')
        ready()
        observation = observe()
        if observation.get('f24_down') is not True or observation.get('f24_up') is not True:
            raise ProtocolError('F24 press/release was not observed')
        result.update(physical_press_observed=True,observation=observation)
    finally:
        try:
            if journal.exists(): restore(io,prepared,journal)
            after = read_state(io)
            result.update(normal_mode_verified=True,original_binding_restored=io.read_binding(1,0x4B,0)==validate(prepared),
                          saved_state_unchanged=after==before,after=after,transport_health=dict(io.reply_health))
            if after != before or not result['original_binding_restored']:
                raise ProtocolError('Wired cleanup differs from the baseline; unrelated current state preserved')
        finally:
            durable_json(root/'result.json',result)
    print('RESTORED: original side12, normal mode and complete captured state verified. Persistence not tested.',flush=True)
    return result


def run(directory,*,recover=False):
    if socket_path().exists(): raise ProtocolError('Stop software control before the isolated binding experiment')
    prepared = read_journal(directory/'prepared.json')
    validate(prepared)
    if not recover and prepared.get('purpose') not in (None,'once'):
        raise ProtocolError('Use the prepared experiment’s specific runner')
    root = directory/'run'
    if not recover: root.mkdir(mode=0o700)
    device = selected()
    with TestHID(backend.node(device),prepared,root/'binding.json') as io:
        if io.execute(wired.BOOTSTRAP['firmware']).hex() != prepared['before']['firmware'] or io.device_serial()!=prepared['before']['serial']:
            raise ProtocolError('Wired identity/firmware changed; no write admitted')
        if recover:
            restore(io,prepared,root/'binding.json')
            after = read_state(io)
            durable_json(root/'recovery.json',{'version':1,'normal_mode_verified':True,
                         'saved_state_unchanged':after==prepared['before'],'after':after})
            if after != prepared['before']: raise ProtocolError('Recovery readback differs; current unrelated state preserved')
            return
        with WiredObserver(device) as observer:
            def ready():
                observer.arm()
                print('READY: tap and release wired V3 side12 once. Original mapping restores after F24 or180 seconds.',flush=True)
            return exercise(io,prepared,root,lambda:observer.observe(lambda:False),ready=ready)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('prepare','run','recover'))
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        def interrupted(*_): raise KeyboardInterrupt('Binding experiment interrupted')
        signal.signal(signal.SIGTERM,interrupted)
        if args.operation=='prepare': prepare(args.directory)
        else: run(args.directory,recover=args.operation=='recover')
    except (OSError,ValueError,KeyboardInterrupt) as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__':
    main()
