"""Opt-in wired F24 retention across observed USB cable re-enumeration."""

import argparse
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import errno
from pathlib import Path
import signal
import time

from . import wired_binding_probe as base
from . import wired_probe as wired
from . import wired_backend as backend
from .hardware import read_journal
from .onboard import Programmer, durable_json
from .protocol import DeviceStatusError, DeviceUnavailable, ProtocolError
from .wired_transport import read_state


def route():
    matches=[d for d in backend.discover() if d.product_id==wired.PRODUCT]
    if not matches: return None
    if len(matches)!=1: raise ProtocolError('Ambiguous wired transport')
    device=matches[0]
    if {n['number'] for n in device.interfaces if n['kind']=='hidraw'} != {'00','01','02','03'}:
        return {'pending':True}
    try: entries=wired.descriptors(device)
    except OSError: return {'pending':True}
    return {'product':wired.PRODUCT,'usb_path':device.usb_path,**entries['00']['usb_address']}


def validate(prepared):
    base.validate(prepared)
    expected=prepared.get('usb_route',{})
    if (prepared.get('purpose')!='cable-replug' or prepared.get('power_cycle_requested') is not True
            or not isinstance(expected,dict) or expected.get('product')!=wired.PRODUCT
            or not isinstance(expected.get('usb_path'),str)
            or not expected['usb_path'].startswith('/sys/')
            or any(not isinstance(expected.get(k),str) or not expected[k].isdecimal()
                   or int(expected[k])<1 for k in ('busnum','devnum'))):
        raise ProtocolError('A complete wired cable-replug proposal is required')


def candidate(prepared):
    before=deepcopy(prepared['before'])
    for record in before['records']:
        if record['control']==0x4B and record['layer']==0:
            record['raw']=(bytes.fromhex(record['raw'])[:3]+base.TARGET).hex()
    return before


@contextmanager
def responsive(opening,prepared,*,wait=time.sleep,now=time.monotonic):
    """Retry only opening/getters. A yielded setter is never replayed."""
    deadline=now()+45
    for attempt in range(16):
        stack=ExitStack()
        try:
            io=stack.enter_context(opening())
            observed=read_state(io)
            if (observed['serial']!=prepared['before']['serial']
                    or observed['firmware']!=prepared['before']['firmware']):
                raise ProtocolError('A different wired identity/firmware appeared')
        except BaseException as error:
            stack.close()
            transient=(isinstance(error,DeviceUnavailable)
                       or isinstance(error,DeviceStatusError) and error.status in (1,4)
                       or isinstance(error,OSError) and error.errno in
                       (errno.EACCES,errno.ENOENT,errno.ENODEV,errno.ENXIO,errno.EPIPE,errno.ETIMEDOUT))
            if not transient or attempt==15 or now()>=deadline: raise
            wait(.5)
            continue
        try: yield io,observed
        finally: stack.close()
        return


def exercise(prepared,root,opening,observe_route,observe_press,*,announce=lambda stage:None,
             stopped=lambda:False,wait=time.sleep,now=time.monotonic):
    validate(prepared)
    if observe_route()!=prepared['usb_route']: raise ProtocolError('Wired enumeration changed since preparation')
    journal=root/'binding.json'
    result={'version':1,'kind':'wired-binding-replug-result','usb_disconnect_observed':False,
            'binding_retained':False,'physical_press_observed':False,'original_state_restored':False}
    def stage(value):
        result['status']=value
        durable_json(root/'result.json',result)
        announce(value)
    fatal=None
    @contextmanager
    def tracked_opening():
        with opening() as io:
            try: yield io
            finally: result.setdefault('transport_health',[]).append(dict(io.reply_health))
    try:
        with responsive(tracked_opening,prepared,wait=wait,now=now) as (io,before):
            if before!=prepared['before']: raise ProtocolError('Wired state changed; no new binding admitted')
            Programmer(io,journal,before['serial'],set(before['controls'])).apply({base.WHERE:base.TARGET})
            if read_state(io)!=candidate(prepared): raise ProtocolError('Candidate/protected-state readback differs')
        # All old HID descriptors close before physical USB removal.
        stage('awaiting-cable-replug')
        deadline=now()+180
        while now()<deadline:
            if stopped(): raise InterruptedError('Cable-replug test cancelled')
            current=observe_route()
            if current is None:
                result['usb_disconnect_observed']=True
            elif result['usb_disconnect_observed'] and not current.get('pending'):
                if current['product']!=prepared['usb_route']['product'] or current['usb_path']!=prepared['usb_route']['usb_path']:
                    raise ProtocolError('Wired cable returned on a different route')
                if (current['busnum'],current['devnum'])!=(prepared['usb_route']['busnum'],prepared['usb_route']['devnum']):
                    result['returned_route']=current
                    break
            wait(.2)
        else: raise ProtocolError('Cable removal/re-enumeration was not observed before timeout')
        with responsive(tracked_opening,prepared,wait=wait,now=now) as (io,after):
            result['after_replug']=after
            result['binding_retained']=all(base.is_candidate(bytes.fromhex(r['raw'])[3:]) for r in after['records']
                                          if r['control']==0x4B and r['layer']==0)
            normalized=deepcopy(after)
            for r in normalized['records']:
                if r['control']==0x4B and r['layer']==0 and base.is_candidate(bytes.fromhex(r['raw'])[3:]):
                    r['raw']=(bytes.fromhex(r['raw'])[:3]+base.TARGET).hex()
            result['binding_encoding_changed']=normalized!=after
            if normalized!=candidate(prepared): raise ProtocolError('Candidate/protected state differs after cable replug')
            stage('ready-side12')
            observation=observe_press()
            if observation.get('f24_down') is not True or observation.get('f24_up') is not True:
                raise ProtocolError('F24 press/release not observed after cable replug')
            result.update(physical_press_observed=True,observation=observation)
    except BaseException as error:
        result['experiment_error']=str(error) or type(error).__name__
        if not isinstance(error,Exception): fatal=error
    finally:
        if journal.exists():
            try:
                with responsive(tracked_opening,prepared,wait=wait,now=now) as (io,_):
                    base.restore(io,prepared,journal)
                    after=read_state(io)
                    result.update(after_restore=after,original_state_restored=after==prepared['before'])
                    if after!=prepared['before']: raise ProtocolError('Other current state differs and was preserved')
            except BaseException as error:
                result['recovery_error']=str(error) or type(error).__name__
                if not isinstance(error,Exception): fatal=error
        result['status']=('preflight-failed' if not journal.exists() else
                          'recovery-required' if not result['original_state_restored'] else
                          'test-failed-restored' if result.get('experiment_error') else 'cable-replug-restored')
        result['setting_commands']=sum(h['setting_commands'] for h in result.get('transport_health',[]))
        durable_json(root/'result.json',result)
    if fatal: raise fatal
    if result.get('experiment_error') or result.get('recovery_error'):
        raise ProtocolError(f'{result["status"]}: '+result.get('experiment_error',result.get('recovery_error','')))
    return result


def prepare(directory):
    base.prepare(directory)
    document=read_journal(directory/'prepared.json')
    document.update(purpose='cable-replug',power_cycle_requested=True,usb_route=route())
    validate(document)
    durable_json(directory/'prepared.json',document)
    print('Power/cable-cycle proposal: mouse OFF, unplug five seconds, mouse ON, reconnect same port after READY; wait for tap readiness, then side12. No write made.')


def run(directory):
    if base.socket_path().exists(): raise ProtocolError('Stop software control before the cable-replug experiment')
    prepared=read_journal(directory/'prepared.json');validate(prepared)
    root=directory/'run';root.mkdir(mode=0o700)
    def opening():
        device=base.selected()
        if device.usb_path!=prepared['usb_route']['usb_path']: raise ProtocolError('Wired route differs')
        return base.TestHID(backend.node(device),prepared,root/'binding.json')
    def observe_press():
        with base.WiredObserver(base.selected()) as observer:
            observer.arm()
            print('TAP READY: replug readback verified; tap/release wired V3 side12 once now.',flush=True)
            return observer.observe(lambda:False)
    def announce(stage):
        if stage=='awaiting-cable-replug':
            print('REPLUG READY: switch V3 OFF, unplug its USB cable, wait five seconds, switch V3 ON, reconnect the same port. Wait for TAP READY before pressing.',flush=True)
    return exercise(prepared,root,opening,route,observe_press,announce=announce)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('prepare','run','recover'))
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        def interrupted(*_): raise KeyboardInterrupt('Cable-replug experiment interrupted')
        signal.signal(signal.SIGTERM,interrupted)
        if args.operation=='prepare': prepare(args.directory)
        elif args.operation=='recover': base.run(args.directory,recover=True)
        else: run(args.directory)
    except (OSError,ValueError,KeyboardInterrupt) as error: parser.exit(1,str(error)+'\n')


if __name__=='__main__': main()
