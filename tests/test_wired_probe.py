import errno
import json
from pathlib import Path

import pytest

from gillete import wired_probe as wired
from gillete.compile_onboard import CONTROL_IDS
from gillete.descriptors import report_sizes
from gillete.devices import Device
from gillete.hid import CONFIG_INTERFACE
from gillete.model import MODELS
from gillete.protocol import Command, DeviceStatusError, DeviceUnavailable, ProtocolError


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/naga_v3_descriptors.json').read_text())


def test_public_descriptor_sizes_are_transport_specific_without_claiming_button_correlations():
    products = FIXTURE['products']
    wire, receiver = ({number: report_sizes(bytes.fromhex(raw)) for number, raw in products[product].items()}
                      for product in ('00e7', '00e8'))
    assert wire == wired.LAYOUTS
    assert wire['00'] == receiver['00'] and wire['02'] == receiver['02'] and wire['03'] == receiver['03']
    assert receiver['01']['input'] == {**wire['01']['input'], '8': 16, '9': 16, '10': 9}
    assert receiver['01']['output'] == {'1': 2} and not wire['01']['output']
    assert products['00e7']['02'] == products['00e8']['02']
    assert products['00e7']['03'] == products['00e8']['03']


def test_descriptor_bit_padding_global_stack_and_numbered_length():
    # 3+5 bits, then Push, a second report ID with 2*16 bits, Pop, 1*8 bits.
    raw = bytes.fromhex('a101850175019503810295058101a48502751095028106b4750895018102c0')
    assert report_sizes(raw) == {'input': {'1': 3, '2': 5}, 'output': {}, 'feature': {}}
    assert report_sizes(bytes.fromhex('a101750195019102c0'))['output'] == {'0': 1}


@pytest.mark.parametrize('raw', [b'', b'\xfe\0\0', b'\x76\x10', b'\xb4', b'\xc0',
                              bytes.fromhex('a1018500750895018102c0'),
                              bytes.fromhex('a1018102c0'), bytes.fromhex('a101750895018102'),
                              bytes.fromhex('a101750895018102850195018102c0'),
                              bytes.fromhex('a101754097001000008102c0'), b'\0' * 4097])
def test_malformed_or_unsupported_descriptors_are_not_interpreted_as_known_layouts(raw):
    with pytest.raises(ProtocolError): report_sizes(raw)


def fake_sysfs(tmp_path):
    sysfs = tmp_path / 'sys'
    usb = sysfs / 'devices/usb1/1-2'
    usb.mkdir(parents=True)
    (usb / 'idVendor').write_text('1532\n')
    (usb / 'idProduct').write_text('00e7\n')
    (usb / 'busnum').write_text('1\n')
    (usb / 'devnum').write_text('23\n')
    interfaces = []
    # USB listing order differs from bInterfaceNumber order on this product.
    for number in ('00', '02', '01', '03'):
        interface = usb / f'1-2:1.{int(number)}'
        hid = interface / f'0003:1532:00E7.000{number}'
        hid.mkdir(parents=True)
        (interface / 'bInterfaceNumber').write_text(number)
        (interface / 'driver').symlink_to(sysfs / 'bus/usb/drivers/usbhid')
        (hid / 'driver').symlink_to(sysfs / 'bus/hid/drivers/razermouse')
        (hid / 'report_descriptor').write_bytes(bytes.fromhex(FIXTURE['products']['00e7'][number]))
        node = f'hidraw{int(number) + 10}'
        entry = sysfs / 'class/hidraw' / node
        entry.mkdir(parents=True)
        (entry / 'device').symlink_to(hid)
        interfaces.append({'kind': 'hidraw', 'number': number, 'path': f'/dev/{node}'})
    device = Device(MODELS[1], 'Naga V3 Pro', 'USB wired', 0xE7, str(usb), '', interfaces)
    return sysfs, device


def test_sysfs_capture_uses_usb_ancestor_and_interface_numbers_not_order(tmp_path):
    sysfs, device = fake_sysfs(tmp_path)
    entries = wired.descriptors(device, sysfs)
    assert list(entries) == ['00', '01', '02', '03']
    assert [entry['bytes'] for entry in entries.values()] == [79, 159, 61, 22]
    assert all(entry['matches_reference_sizes'] and len(entry['sha256']) == 64 for entry in entries.values())
    assert all(entry['hid_driver'] == 'razermouse' and entry['usb_driver'] == 'usbhid' for entry in entries.values())


@pytest.mark.parametrize('problem', ['identity', 'missing', 'duplicate', 'wrong-interface', 'moved', 'huge'])
def test_changed_sysfs_identity_or_interfaces_abort_before_any_query(tmp_path, problem):
    sysfs, device = fake_sysfs(tmp_path)
    if problem == 'identity': (Path(device.usb_path) / 'idProduct').write_text('00e8')
    elif problem == 'missing': device.interfaces.pop()
    elif problem == 'duplicate': device.interfaces.append(dict(device.interfaces[0]))
    elif problem == 'wrong-interface': device.interfaces[0]['number'] = '03'
    else:
        link = sysfs / 'class/hidraw/hidraw10/device'
        if problem == 'moved':
            link.unlink()
            link.symlink_to(tmp_path)
        else: (link / 'report_descriptor').write_bytes(bytes(4097))
    with pytest.raises(ProtocolError): wired.descriptors(device, sysfs)


class Mouse(wired.WiredQueryHID):
    def __init__(self, *, fail_first=None, mode=bytes(2), drift=False, preflight_error=False, verification_error=False):
        super().__init__('/dev/hidraw-test')
        self.fail_first, self.mode, self.drift = fail_first, mode, drift
        self.preflight_error, self.verification_error = preflight_error, verification_error
        self.commands, self.mode_queries = [], 0
        known = set(CONTROL_IDS[MODELS[1]].values())
        self.controls = sorted(known | set(sorted(set(range(1, 256)) - known)[:8]))

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def _exchange(self, command):
        self.commands.append(command)
        if self.fail_first and len(self.commands) == 1:
            raise self.fail_first
        pair, data = (command.category, command.operation), command.payload
        if pair == (0, 0x81): return bytes.fromhex('01010000')
        if pair == (0, 0x84):
            self.mode_queries += 1
            if self.verification_error and self.mode_queries == 3: raise DeviceUnavailable('Unplugged')
            return self.mode
        if pair == (0, 0x85): return b'\1'
        if pair == (0, 0x82): return b'wired-test' + bytes(12)
        if pair == (5, 0x80):
            if self.preflight_error: raise DeviceStatusError(3)
            return b'\1'
        if pair == (5, 0x81): return b'\5\1'
        if pair == (5, 0x84): return b'\1'
        if pair == (2, 0x84): return bytes((len(self.controls), *self.controls))[:len(data)]
        if pair == (2, 0x8C):
            function = bytes.fromhex('05020000000000')
            if self.drift and self.mode_queries == 3: function = bytes.fromhex('0202001e000000')
            return data[:2] + b'\1' + function
        if pair == (4, 0x85): return bytes.fromhex('01032003200000')
        if pair == (4, 0x86): return bytes.fromhex('01010101032003200000') + bytes(28)
        raise AssertionError('Unexpected read or any setter')


def document():
    return {'descriptors': {number: {'node': f'/dev/hidraw{number}', 'matches_reference_sizes': True} for number in wired.LAYOUTS},
            'routes': [], 'read_only_route': None}


def test_first_successful_query_route_is_recorded_without_sweeping_or_enabling_support():
    result, mouse, opened = document(), Mouse(), []
    def open_hid(path):
        opened.append(path)
        return mouse
    wired.query_routes(result, open_hid)
    assert result['status'] == 'read-only-state-verified' and result['read_only_route'] == '00'
    assert opened == ['/dev/hidraw00'] and len(result['routes']) == 1
    route = result['routes'][0]
    assert route['state_unchanged'] and route['before'] == route['after']
    assert len(route['before']['records']) == 100 and len(route['before']['controls']) == 33
    assert 0xE7 not in CONFIG_INTERFACE
    assert all(c.operation >= 0x80 for c in mouse.commands)


@pytest.mark.parametrize('failure', [OSError(errno.EPIPE, 'Unsupported interface'), DeviceUnavailable('No reply'), DeviceStatusError(0)])
def test_descriptor_route_is_tried_once_after_driver_candidate_fails(failure):
    result = document()
    mice = [Mouse(fail_first=failure), Mouse()]
    opened = []
    def open_hid(path):
        opened.append(path)
        return mice[len(opened) - 1]
    wired.query_routes(result, open_hid)
    assert result['status'] == 'read-only-state-verified' and result['read_only_route'] == '03'
    assert opened == ['/dev/hidraw00', '/dev/hidraw03']
    assert len(mice[0].commands) == 1 and mice[0].commands[0].payload == bytes(4)
    assert len(result['routes'][0]['queries']) == 1


@pytest.mark.parametrize('case,status', [('mode', 'normal-mode-required'), ('preflight', 'read-preflight-failed'),
                                      ('drift', 'state-difference-observed'), ('verification', 'verification-unavailable')])
def test_working_route_does_not_sweep_after_a_state_or_inventory_problem(case, status):
    result, opened = document(), []
    mouse = Mouse(mode=b'\3\0' if case == 'mode' else bytes(2), drift=case == 'drift',
                  preflight_error=case == 'preflight', verification_error=case == 'verification')
    def open_hid(path):
        opened.append(path)
        return mouse
    wired.query_routes(result, open_hid)
    assert result['status'] == status and result['read_only_route'] is None
    assert opened == ['/dev/hidraw00']
    if case == 'mode': assert len(mouse.commands) == 2


def test_unknown_descriptor_sizes_prevent_route_queries():
    result = document()
    result['descriptors']['01']['matches_reference_sizes'] = False
    def forbidden(_): raise AssertionError('Must not query an unknown descriptor layout')
    wired.query_routes(result, forbidden)
    assert result['status'] == 'descriptor-difference; query skipped' and not result['routes']


@pytest.mark.parametrize('command', [Command(0, 4, b'\3\0'), Command(4, 5, b'\0' + bytes(6)),
                                   Command(2, 0x0C, bytes(10)), Command(6, 0x80, bytes(2)),
                                   Command(0, 0x81, bytes(2)), Command(4, 0x85, bytes(7)),
                                   Command(2, 0x8C, b'\6\x40\0' + bytes(7)),
                                   Command(0, 0x84, bytes(2), transaction=0x3F)])
def test_wired_transport_rejects_mutations_unrelated_getters_and_unverified_packet_shapes(command):
    mouse = Mouse()
    with pytest.raises(ProtocolError): mouse.execute(command)
    assert not mouse.commands


def test_public_firmware_reply_requires_four_byte_framing():
    raw = bytes.fromhex(FIXTURE['wired_firmware_reply'])
    assert wired.BOOTSTRAP['firmware'].decode(raw) == bytes.fromhex('01010000')
    with pytest.raises(ProtocolError): Command(0, 0x81, bytes(2)).decode(raw)
    echo = bytearray(wired.BOOTSTRAP['firmware'].encode())
    with pytest.raises(DeviceStatusError): wired.BOOTSTRAP['firmware'].decode(echo)


def test_descriptor_only_command_never_opens_a_device_and_keeps_a_connected_receiver_distinct(tmp_path, monkeypatch):
    sysfs, device = fake_sysfs(tmp_path)
    receiver = Device(MODELS[1], 'Naga V3 Pro', '2.4 GHz', 0xE8, '/receiver', 'same-identity')
    monkeypatch.setattr(wired, 'discover', lambda _: [device, receiver])
    def forbidden(*_): raise AssertionError('Descriptor-only collection must not open a hidraw device')
    monkeypatch.setattr(wired, 'query_routes', forbidden)
    path = tmp_path / 'private/report.json'
    result = wired.run(path, sysfs=sysfs)
    assert result['status'] == 'descriptors-captured' and result['receiver_present']
    assert result['usb_path'] == device.usb_path and not result['routes']
    assert not result['writes_enabled'] and not result['software_activation_enabled']
    assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text()) == result
    with pytest.raises(FileExistsError): wired.run(path, sysfs=sysfs)


def test_full_cli_read_path_records_route_without_mutating_application_capabilities(tmp_path, monkeypatch):
    sysfs, device = fake_sysfs(tmp_path)
    monkeypatch.setattr(wired, 'discover', lambda _: [device])
    real_query = wired.query_routes
    monkeypatch.setattr(wired, 'query_routes', lambda document, **kwargs: real_query(document, lambda _: Mouse(), **kwargs))
    path = tmp_path / 'report.json'
    result = wired.run(path, query=True, sysfs=sysfs)
    assert result['status'] == 'read-only-state-verified'
    assert not result['writes_enabled'] and not result['software_activation_enabled']
    assert 0xE7 not in CONFIG_INTERFACE


@pytest.mark.parametrize('when', ['before-open', 'after-open', 'after-query'])
def test_topology_changes_abort_the_whole_probe_without_trying_another_route(when):
    result, mouse, opened = document(), Mouse(), []
    checks = 0
    def verify():
        nonlocal checks
        checks += 1
        if checks == {'before-open': 1, 'after-open': 2, 'after-query': 3}[when]:
            raise wired.RouteIdentityChanged('Device node was reused')
    def open_hid(path):
        opened.append(path)
        return mouse
    wired.query_routes(result, open_hid, verify)
    assert result['status'] == 'identity-changed' and result['read_only_route'] is None
    assert len(result['routes']) == 1
    if when != 'after-query': assert not mouse.commands
    if when == 'before-open': assert not opened


@pytest.mark.parametrize('change', ['product', 'enumeration', 'hid-instance'])
def test_descriptor_change_during_full_inspection_rejects_the_route_result(tmp_path, monkeypatch, change):
    sysfs, device = fake_sysfs(tmp_path)
    monkeypatch.setattr(wired, 'discover', lambda _: [device])
    class Replacement(Mouse):
        def __exit__(self, *_): pass
        def _exchange(self, command):
            reply = super()._exchange(command)
            if len(self.commands) == 3:
                if change == 'product':
                    (Path(device.usb_path) / 'idProduct').write_text('00e8')
                elif change == 'enumeration':
                    (Path(device.usb_path) / 'devnum').write_text('24')
                else:
                    link = sysfs / 'class/hidraw/hidraw10/device'
                    old = link.resolve()
                    new = old.with_name(old.name + '-replacement')
                    old.rename(new)
                    link.unlink()
                    link.symlink_to(new)
            return reply
    monkeypatch.setattr(wired, 'WiredQueryHID', lambda _: Replacement())
    result = wired.run(tmp_path / 'changed.json', query=True, sysfs=sysfs)
    assert result['status'] == 'identity-changed' and result['read_only_route'] is None
    assert len(result['routes']) == 1


def test_missing_device_and_incomplete_descriptor_failure_never_claim_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(wired, 'discover', lambda _: [])
    with pytest.raises(ProtocolError): wired.run(tmp_path / 'absent.json')
    assert not (tmp_path / 'absent.json').exists()
    sysfs, device = fake_sysfs(tmp_path)
    device.interfaces.pop()
    monkeypatch.setattr(wired, 'discover', lambda _: [device])
    result = wired.run(tmp_path / 'incomplete.json', query=True, sysfs=sysfs)
    assert result['status'] == 'inspection-failed' and not result['routes']
