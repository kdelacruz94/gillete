from types import SimpleNamespace

import pytest

from gillete import devices as discovery
from gillete.devices import Device, PRODUCTS
from gillete.diagnostics import feature_validation, findings, label, transport_identity
from gillete.profiles import ProfileStore
from gillete.service import Daemon


def mouse(product=0xB4, port='/usb/1-2'):
    model, name, route = PRODUCTS[product]
    nodes = [{'kind': 'hidraw', 'number': f'{i:02}', 'path': f'/dev/hidraw{i}', 'readable': True, 'writable': True}
             for i in range(4 if product in (0xE7, 0xE8) else 3)]
    nodes.extend({'kind': 'input', 'number': f'{i:02}', 'path': f'/dev/input/event{i}', 'readable': True, 'writable': False}
                 for i in range(3))
    return Device(model, name, route, product, port, 'private-unit-serial', nodes)


def checks(device, **kwargs):
    return {row.name: row for row in findings(device, [device], **kwargs)}


def test_read_only_configuration_permission_is_not_mistaken_for_a_usable_feature_route():
    device = mouse()
    device.interfaces[0]['writable'] = False
    rows = checks(device, uinput_access=True)
    assert rows['Mouse configuration'].status == 'Access missing'
    assert rows['Software input'].status == 'Accessible'
    assert rows['Generated input'].status == 'Accessible'
    assert rows['Input ownership'].status == 'Not tested'
    assert 'Permission guidance' in rows
    assert 'private-unit-serial' not in str(rows) + label(device)


@pytest.mark.parametrize('problem,expected', [('missing-raw', 'Incomplete'), ('missing-events', 'Incomplete'),
                                          ('duplicate', 'Ambiguous'), ('permission', 'Access missing'), ('unknown', 'Unknown')])
def test_input_discovery_distinguishes_enumeration_ambiguity_and_access(problem, expected):
    device = mouse(0xE8)
    if problem == 'missing-raw': device.interfaces.pop(0)
    elif problem == 'missing-events': device.interfaces = device.interfaces[:4]
    elif problem == 'duplicate': device.interfaces.append(dict(device.interfaces[0]))
    elif problem == 'permission': device.interfaces[-1]['readable'] = False
    else: device.interfaces[-1].pop('readable')
    assert checks(device)['Software input'].status == expected


def test_accessible_wired_reads_do_not_enable_unverified_onboard_writes():
    device = mouse(0xE7)
    rows = checks(device, uinput_access=True)
    assert rows['Mouse configuration'].status == 'Accessible'
    assert rows['Software input'].status == 'Accessible'
    features = feature_validation(0xE7)
    assert [row.status for row in features] == ['Live reads passed', 'Captured on device', 'Complete suite passed', 'Unavailable']


def test_service_status_reports_exact_transport_without_serial_or_window(tmp_path):
    daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
    device = mouse(0xE8)
    daemon.requested.add(device.model)
    daemon.sessions[device.model] = SimpleNamespace(device=device, ready=True, engine=None)
    state = daemon.status()['devices'][device.model]
    assert state['transport'] == transport_identity(device)
    assert state['transport'] == {'product': 0xE8, 'usb_path': '/usb/1-2', 'transport': '2.4 GHz'}
    assert 'private-unit-serial' not in str(state)


def test_active_receiver_is_not_reported_as_ownership_of_the_wired_mouse(tmp_path):
    receiver, cable = mouse(0xE8), mouse(0xE7, '/usb/1-3')
    daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
    daemon.requested.add(receiver.model)
    daemon.sessions[receiver.model] = SimpleNamespace(device=receiver, ready=True, engine=None)
    state = daemon.status()
    own = {r.name: r for r in findings(receiver, [receiver, cable], service=state)}
    other = {r.name: r for r in findings(cable, [receiver, cable], service=state)}
    assert own['Transport selection'].status == 'Multiple connected'
    assert own['Software session'].status == 'Active' and own['Input ownership'].status == 'Held by Gillete'
    assert other['Software session'].status == 'Other transport' and other['Input ownership'].status == 'Not tested here'
    assert '00e8' in other['Software session'].detail


def test_old_service_status_cannot_prove_ownership_of_a_specific_unit(tmp_path):
    device = mouse()
    data = Daemon(ProfileStore(tmp_path / 'profiles.json')).status()
    data['devices'][device.model].update(active=True, requested=True)
    data['devices'][device.model].pop('transport')
    rows = checks(device, service=data)
    assert rows['Software session'].status == 'Active for model'
    assert rows['Input ownership'].status == 'Exact transport unknown'


def test_current_service_failures_and_backoff_are_visible_without_classifying_error_text(tmp_path):
    device = mouse()
    data = Daemon(ProfileStore(tmp_path / 'profiles.json')).status()
    data['devices'][device.model].update(requested=True, retry_in_ms=4200, error='Another application owns a mouse interface')
    rows = checks(device, service=data)
    assert rows['Software session'].status == 'Retry in 5s'
    assert rows['Input ownership'].status == 'Not tested'
    assert rows['Last service error for this model'].detail == data['devices'][device.model]['error']
    assert rows['Desktop monitoring'].status == 'Waiting'
    unavailable = checks(device, service=None, service_error='Service uses a different profile file')
    assert unavailable['Background service'].detail == 'Service uses a different profile file'


def test_connected_monitor_with_pending_focus_is_not_reported_ready(tmp_path):
    device = mouse()
    daemon = Daemon(ProfileStore(tmp_path / 'profiles.json'))
    data = daemon.status()
    data.update(focus_available=True, focus_pending=True, suspend_monitor=True)
    rows = checks(device, service=data)
    assert rows['Desktop monitoring'].status == 'Waiting'
    assert 'current focus details' in rows['Desktop monitoring'].detail
    data['focus_pending'] = False
    assert checks(device, service=data)['Desktop monitoring'].status == 'Ready'


def test_development_validation_remains_distinct_from_implemented_or_pending_work():
    v2, v3 = ({r.name: r for r in feature_validation(product)} for product in (0xB4, 0xE8))
    assert v2['Program profiles, macros and turbo'].status == 'Live test pending'
    assert v3['Program profiles, macros and turbo'].status == 'Live examples passed'
    for rows in (v2, v3):
        assert rows['Saved mappings and held HyperShift'].status == 'Partially verified'
        assert 'replug' in rows['Saved mappings and held HyperShift'].detail
        assert rows['Per-program hardware DPI'].status == 'Unavailable'
        assert rows['DPI stages and polling rate'].status == 'Live write test pending'
    assert v2['Every-control software mapping'].status == 'Live test passed'
    assert 'All 42 normal' in v2['Every-control software mapping'].detail
    assert 'macro/turbo' in v2['Program profiles, macros and turbo'].detail
    assert v3['Every-control software mapping'].status == 'Live test passed'
    assert 'All 50 normal' in v3['Every-control software mapping'].detail
    assert 'restoration verified' in v3['Every-control software mapping'].detail
    assert v2['Native onboard macros and turbo'].status == 'Unavailable'
    assert 'references do not' in v2['Native onboard macros and turbo'].detail
    assert v3['Native onboard macros and turbo'].status == 'Partially verified'
    assert 'firmware1.1' in v3['Native onboard macros and turbo'].detail
    assert 'once-only keyboard sequences and counted single-key' in v3['Native onboard macros and turbo'].detail
    assert 'F13–F23' in v3['Native onboard macros and turbo'].detail
    assert v3['Scalar sensitivity'].status == 'Live examples passed'
    assert 'receiver replug' in v3['Scalar sensitivity'].detail
    assert v2['Scalar sensitivity'].status == 'Live write test pending'
    assert v3['High-speed polling'].status == 'Diagnostic prepared'
    assert 'measured rates remain unverified' in v3['High-speed polling'].detail
    assert v2['High-speed polling'].status == 'Unavailable'
    assert v3['Native storage compaction'].status == 'Unavailable'
    assert 'omits settings and opaque data' in v3['Native storage compaction'].detail


def test_sysfs_discovery_reports_nearest_hid_driver_without_opening_input(tmp_path, monkeypatch):
    sysfs, dev = tmp_path / 'sys', tmp_path / 'dev'
    usb = sysfs / 'bus/usb/devices/1-2'
    hid = usb / '1-2:1.0/0003:1532:00B4.0001'
    input_device = hid / 'input/input0'
    input_device.mkdir(parents=True)
    (usb / 'idVendor').write_text('1532')
    (usb / 'idProduct').write_text('00b4')
    (usb / 'serial').write_text('private-unit-serial')
    (hid.parent / 'bInterfaceNumber').write_text('00')
    (hid / 'driver').symlink_to(sysfs / 'bus/hid/drivers/razermouse')
    (hid.parent / 'driver').symlink_to(sysfs / 'bus/usb/drivers/usbhid')
    for kind, name, target in [('hidraw', 'hidraw0', hid), ('input', 'event0', input_device)]:
        entry = sysfs / 'class' / kind / name
        entry.mkdir(parents=True)
        (entry / 'device').symlink_to(target)
    monkeypatch.setattr(discovery.os, 'access', lambda *_: True)
    found = discovery.discover(sysfs, dev)
    assert len(found) == 1 and len(found[0].interfaces) == 2
    assert {n['driver'] for n in found[0].interfaces} == {'razermouse'}
    assert {n['number'] for n in found[0].interfaces} == {'00'}
