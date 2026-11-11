import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from gillete import guided_service as guided
from gillete.control_validation import ALTERNATE, validate_results
from gillete.hardware import read_journal
from gillete.model import MODELS
from gillete.onboard import durable_json
from gillete.profiles import ProfileStore, Window
from test_control_validation import Clock, complete_report
from test_guided_service import Child, snapshot


def prepared(tmp_path, monkeypatch, model=MODELS[0]):
    before = snapshot(model)
    device = SimpleNamespace(product_id=before.product, model=model, usb_path='/usb/test', transport='2.4 GHz')
    monkeypatch.setattr(guided, 'socket_path', lambda: tmp_path / 'absent.sock')
    monkeypatch.setattr(guided, 'connected', lambda product: device)
    monkeypatch.setattr(guided, 'inspect', lambda *args: deepcopy(before))
    directory = tmp_path / 'coverage'
    guided.prepare(before.product, directory, suite='controls')
    return directory, before, device


@pytest.mark.parametrize('model', MODELS)
def test_prepare_reviews_every_layer_and_run_rejects_a_changed_recipe_without_activation(tmp_path, monkeypatch, capsys, model):
    directory, before, device = prepared(tmp_path, monkeypatch, model)
    output = capsys.readouterr().out
    assert 'private-test-identity' not in output and 'no live test has started' in output
    original = read_journal(directory / 'prepared.json')
    assert original['suite'] == 'controls' and len(original['overrides']) == len(original['coverage']['steps'])
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'prepared.json').stat().st_mode & 0o777 == 0o600
    original['coverage']['steps'].pop()
    durable_json(directory / 'prepared.json', original)
    def forbidden(*args): raise AssertionError('Changed recipe must fail before querying a mouse')
    monkeypatch.setattr(guided, 'connected', forbidden)
    with pytest.raises(ValueError, match='recipe changed'):
        asyncio.run(guided.run(directory, 30))
    assert not (directory / 'run').exists()


@pytest.mark.parametrize('failure', ['none', 'closed-after-coverage', 'incomplete', 'tampered', 'changed-session', 'wrong-route', 'ready-disk-full'])
def test_control_runner_attests_the_session_recomputes_taps_and_always_restores(tmp_path, monkeypatch, failure, capsys):
    directory, before, device = prepared(tmp_path, monkeypatch)
    clock = Clock()
    monkeypatch.setattr(guided, 'time', SimpleNamespace(monotonic=clock))
    sample = complete_report()
    pad, daemon = Child(101), Child(102)
    config_path = directory / 'run/profiles.json'
    run_path = directory / 'run'
    enabled, calls = False, []
    trace_epoch = sample['passed'][0]['epoch']
    def completed():
        doc = deepcopy(sample)
        doc['nonce'] = pad.nonce
        for result in doc['passed']: result['final_packet']['nonce'] = pad.nonce
        clock.t = doc['passed'][-1]['final_packet']['t'] + .1
        return doc
    def write(path, doc):
        if path.name == 'ready.json':
            assert (run_path / 'control-state.json').exists() and doc['nonce'] == pad.nonce
            if failure == 'ready-disk-full': raise OSError('Disk full')
        durable_json(path, doc)
        if path.name == 'ready.json' and failure == 'closed-after-coverage':
            durable_json(run_path / 'coverage.json', completed())
            pad.returncode = 0
    monkeypatch.setattr(guided, 'durable_json', write)
    async def spawn(*args, **kwargs):
        if 'gillete.control_pad' in args:
            pad.title = args[args.index('--title') + 1]
            pad.nonce = args[args.index('--nonce') + 1]
            return pad
        assert '--trace-controls' in args and str(config_path) in args
        assert kwargs['env']['XDG_STATE_HOME'] == str(run_path / 'state')
        return daemon
    async def clients():
        return [{'pid': pad.pid, 'class': 'coverage[?]*', 'title': pad.title, 'address': '0x1'}]
    async def request(command, **kwargs):
        nonlocal enabled
        assert kwargs['config_path'] == config_path
        calls.append(command)
        if command == 'shutdown':
            daemon.returncode = 0
            return {}
        if command == 'enable':
            enabled = True
            return {}
        ready = (run_path / 'ready.json').exists()
        if ready:
            doc = completed()
            trace = deepcopy(doc['passed'][-1]['final_packet']['trace'])
            trace['entries'] = doc['passed'][-1]['physical']
            if failure == 'tampered': doc['passed'][0]['physical'].clear()
            elif failure == 'incomplete':
                doc['status'] = 'incomplete'
                pad.returncode = 0
            elif failure == 'changed-session': trace['epoch'] = 'b' * 32
            durable_json(run_path / 'coverage.json', doc)
        else:
            trace = deepcopy(sample['passed'][0]['final_packet']['trace'])
            trace.update(sequence=0, entries=[], epoch=trace_epoch, profile='validation', generation=0, t=clock())
        route = {'product': before.product, 'usb_path': device.usb_path, 'transport': device.transport}
        if ready and failure == 'wrong-route': route['usb_path'] = '/usb/other'
        return {'focus_available': True, 'focus_pending': False, 'suspend_monitor': True, 'suspended': False,
            'focus': {'address': '0x1'}, 'devices': {before.model: {'active': enabled, 'requested': enabled,
                'profile': ALTERNATE if ready else 'validation', 'active_macros': 0, 'error': '',
                'transport': route, 'input_trace': trace}}}
    monkeypatch.setattr(guided.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(guided, 'clients', clients)
    monkeypatch.setattr(guided, 'request', request)
    if failure in ('none', 'closed-after-coverage'):
        asyncio.run(guided.run(directory, 30))
        result = read_journal(run_path / 'coverage.json')
        assert validate_results(result, before.model, pad.nonce, epoch=trace_epoch, started_at=10, finished_by=clock())
    else:
        with pytest.raises((RuntimeError, ValueError, OSError), match='incomplete|Unverified|restarted|transport|Disk full'):
            asyncio.run(guided.run(directory, 30))
    assert pad.returncode is not None and daemon.returncode is not None and 'shutdown' in calls
    assert read_journal(run_path / 'restoration.json')['stored_state_unchanged']
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in run_path.glob('*.json'))
    config = ProfileStore(config_path).read()
    assert config.select(before.model, Window('0x1', 'coverage[?]*', pad.title)).id == 'validation'
    assert config.select(before.model, Window('0x2', 'elsewhere', pad.title)).id == 'default'
    output = capsys.readouterr().out
    assert ('CONTROL COVERAGE VERIFIED' in output) == (failure in ('none', 'closed-after-coverage'))


def test_controller_rejects_report_from_a_different_live_trace_or_test_interval():
    result = complete_report()
    for options in ({'epoch': 'b' * 32}, {'started_at': 11}, {'finished_by': 10}):
        with pytest.raises(ValueError, match='Unverified'):
            validate_results(result, MODELS[0], result['nonce'], **options)


def test_delayed_status_reply_does_not_refresh_the_source_observation_time(monkeypatch):
    result = complete_report()['passed'][0]
    trace = deepcopy(result['final_packet']['trace'])
    trace['entries'] = []
    device = SimpleNamespace(product_id=0xB4, usb_path='/usb/test', transport='2.4 GHz')
    status = {'focus': {'address': '0x1'}, 'devices': {MODELS[0]: {
        'active': True, 'profile': trace['profile'], 'input_trace': trace,
        'transport': {'product': 0xB4, 'usb_path': device.usb_path, 'transport': device.transport}}}}
    monkeypatch.setattr(guided, 'time', SimpleNamespace(monotonic=lambda: 9999))
    observed = guided.control_packet(status, MODELS[0], device, 'nonce', '0x1')
    assert observed['t'] == trace['t'] and observed['t'] != 9999


def test_run_cannot_override_the_reviewed_suite_on_the_command_line(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        guided.main(['run', '--directory', str(tmp_path), '--suite', 'controls'])
    assert error.value.code == 2 and 'reviewed saved plan' in capsys.readouterr().err
