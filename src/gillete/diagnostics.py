"""Device readiness and validation evidence without opening any device node.

Permission bits and service reports are observations, not a trial input grab.
Historical feature tests never certify a newly connected unit or its mappings.
"""

from dataclasses import dataclass
from pathlib import Path

from .hid import CONFIG_INTERFACE


@dataclass(frozen=True)
class Finding:
    name: str
    status: str
    detail: str


def transport_identity(device):
    """A session's route, excluding its hardware serial and active window."""
    return {'product': device.product_id, 'usb_path': device.usb_path, 'transport': device.transport}


def device_key(device):
    return device.product_id, device.usb_path


def label(device):
    return f'{device.name} — {device.transport} — USB {Path(device.usb_path).name}'


def access(nodes, *, write=False):
    names = ('readable', 'writable') if write else ('readable',)
    if any(node.get(name) is False for node in nodes for name in names):
        return 'Access missing'
    if any(node.get(name) is not True for node in nodes for name in names):
        return 'Unknown'
    return 'Accessible'


def findings(device, devices, *, uinput_access=None, service=None, service_error=''):
    rows = [Finding('Connection', 'Detected',
                    f'{device.name}; {device.transport}; USB 1532:{device.product_id:04x}; '
                    f'port {Path(device.usb_path).name}. Detection does not establish that a wireless mouse is awake.')]
    matches = [d for d in devices if d.model == device.model]
    rows.append(Finding('Transport selection', 'One connected' if len(matches) == 1 else 'Multiple connected',
                        'Only one transport for this model is listed.' if len(matches) == 1 else
                        'New software activations wait for exactly one transport for this model. '
                        'Disconnect the extra receiver/cable or mouse before enabling.'))
    config_interface = CONFIG_INTERFACE.get(device.product_id)
    config_nodes = [n for n in device.interfaces if n['kind'] == 'hidraw' and n['number'] == config_interface]
    if config_interface is None:
        rows.append(Finding('Mouse configuration', 'Unavailable',
                            'This transport is not validated for ordinary mouse reads, saves or software activation. '
                            'A separate read-only wired diagnostic is available for development.'))
    elif len(config_nodes) != 1:
        rows.append(Finding('Mouse configuration', 'Missing' if not config_nodes else 'Ambiguous',
                            f'Expected one hidraw node on interface {config_interface}. Refresh after reconnecting.'))
    else:
        rows.append(Finding('Mouse configuration', access(config_nodes, write=True),
                            f"Interface {config_interface}: {config_nodes[0]['path']}. Read and write access are required "
                            'even for feature-query requests.'))
    raw = [n for n in device.interfaces if n['kind'] == 'hidraw' and n['number'] in ('00', '01', '02')]
    events = [n for n in device.interfaces if n['kind'] == 'input']
    numbers = [n['number'] for n in raw]
    if len(set(numbers)) != len(numbers):
        rows.append(Finding('Software input', 'Ambiguous', 'Multiple raw input nodes have the same interface number.'))
    elif set(numbers) != {'00', '01', '02'} or not events:
        rows.append(Finding('Software input', 'Incomplete',
                            'Raw input interfaces 00/01/02 and evdev input nodes must finish enumerating. Refresh after reconnecting.'))
    else:
        rows.append(Finding('Software input', access([*raw, *events]),
                            'Read access is required for the three raw input interfaces and all evdev nodes. '
                            'Readable nodes may still be owned by another remapper.'))
    rows.append(Finding('Generated input', 'Accessible' if uinput_access is True else 'Access missing' if uinput_access is False else 'Unknown',
                        '/dev/uinput must be writable for software mappings. No virtual keyboard or mouse was created by this check.'))
    if any(row.status == 'Access missing' for row in rows):
        rows.append(Finding('Permission guidance', 'Action needed',
                            'Use the scoped Gillete udev rule with an active desktop session, then refresh. '
                            'A disconnected node can also lose access. Run the editor as your normal user.'))

    if not service:
        rows.extend((Finding('Background service', 'Not reachable' if service_error else 'Not checked', service_error or 'No current service status is available.'),
                     Finding('Input ownership', 'Not tested',
                             'Diagnostics never attempts an exclusive input grab. Enable software control only after suspending another remapper for this mouse.')))
        return rows

    rows.append(Finding('Desktop monitoring', 'Ready' if service.get('focus_available') and not service.get('focus_pending') and service.get('suspend_monitor') and not service.get('suspended') else 'Waiting',
                        'Focus and suspend monitoring are available.' if service.get('focus_available') and not service.get('focus_pending') and service.get('suspend_monitor') and not service.get('suspended') else
                        'Software activation waits for current focus details, focus and suspend monitoring and an awake desktop. '
                        + (service.get('focus_error') or '')))
    state = service.get('devices', {}).get(device.model, {})
    route = state.get('transport')
    same = route is not None and (route.get('product'), route.get('usb_path')) == device_key(device)
    other = route is not None and not same
    if same:
        phase = 'Stopping' if not state.get('requested') else 'Active' if state.get('active') else 'Starting'
        ownership = ('Held by Gillete' if state.get('active') else 'Session changing')
        detail = 'The service reports this exact USB transport. Use Software control to disable it before direct mouse-memory operations.'
    elif other:
        phase, ownership = 'Other transport', 'Not tested here'
        detail = f"The service reports USB 1532:{route['product']:04x} on port {Path(route['usb_path']).name}; this selected transport is not its session."
    elif state.get('active'):
        phase, ownership = 'Active for model', 'Exact transport unknown'
        detail = 'The running service did not report its USB route. Restart it before relying on transport-specific ownership information.'
    elif state.get('requested'):
        retry = state.get('retry_in_ms', 0)
        phase, ownership = (f'Retry in {(retry + 999) // 1000}s' if retry else 'Waiting to start'), 'Not tested'
        detail = 'Software control is requested; the service has not reported an active transport.'
    else:
        phase, ownership = 'Disabled', 'Not tested'
        detail = 'Software control is disabled for this model. Other remappers may still own its input nodes.'
    rows.append(Finding('Software session', phase, detail))
    rows.append(Finding('Input ownership', ownership,
                        'Based on the existing service report; no ownership probe was performed. '
                        'Permission checks alone cannot identify an exclusive grab by another application.'))
    if state.get('error'):
        rows.append(Finding('Last service error for this model', 'Reported', state['error']))
    if same and state.get('action_error'):
        rows.append(Finding('Action error', 'Reported', state['action_error']))
    if service.get('configuration_error'):
        rows.append(Finding('Profile configuration', 'Error', service['configuration_error']))
    rows.append(Finding('Emergency shortcut', 'Installed' if service.get('emergency_shortcut') else 'Not installed',
                        service.get('emergency_shortcut') or
                        ('The service checks ' + service.get('emergency_shortcut_configured', 'the configured shortcut')
                         + ' before enabling a mouse.')))
    return rows


def feature_validation(product):
    """Evidence for the development hardware, not a current-unit test result."""
    if product not in (0xB4, 0xE8):
        return [Finding('Wired read-only inspection', 'Diagnostic prepared',
                        'Descriptor and candidate-route checks are implemented; physical cable validation is pending.'),
                Finding('Wired controls and HyperShift', 'Unverified',
                        'Receiver captures and similar descriptor sizes do not prove wired button behavior.'),
                Finding('Wired saves and software control', 'Unavailable',
                        'Normal application activation and writes remain gated until wired testing passes.')]
    count = 21 if product == 0xB4 else 25
    return [Finding('Physical controls', 'Captured on device',
                    f'All {count} controls were identified on the development receiver. Full mapping acceptance is still pending.'),
            Finding('Every-control software mapping', 'Guided test prepared',
                    f'A separate {count * 2}-tap receiver test checks every normal/HyperShift assignment, '
                    'including the trigger through an alternate trigger. Mouse edges and desktop keys must both match. '
                    'The complete physical run is pending.'),
            Finding('Saved mappings and held HyperShift', 'Partially verified',
                    'Side 12 F24/F23 tests survived a mouse power cycle. Receiver replug and broader assignment tests remain pending.'),
            Finding('Program profiles, macros and turbo', 'Live examples passed' if product == 0xE8 else 'Live test pending',
                    'V3 examples passed F24/F23, Ctrl+K then M, toggle-1 and focus cancellation. Full lifecycle acceptance remains pending.'
                    if product == 0xE8 else 'Software actions are implemented and tested in simulation; the V2 live software test is pending.'),
            Finding('Macro recording and program launches', 'Implemented',
                    'Linux service features; full desktop acceptance is pending.'),
            Finding('DPI stages and polling rate', 'Live write test pending',
                    'Editing, journaling and restoration are implemented; saved-stage and polling-rate write acceptance is pending.'),
            Finding('High-speed polling', 'Diagnostic prepared' if product == 0xE8 else 'Unavailable',
                    'An opt-in receiver diagnostic compares profile/high-speed getter codes without setters. '
                    'Synapse selects these paths conditionally; effective routing and measured rates remain unverified. '
                    'The settings editor still offers only 125, 500 and 1000 Hz.' if product == 0xE8 else
                    'V3 source encodings do not establish V2 high-speed polling support.'),
            Finding('Scalar sensitivity', 'Live examples passed' if product == 0xE8 else 'Live write test pending',
                    'The development V3 accepted 1200 DPI in normal and temporary driver mode. '
                    'Readback retained it across the reported off/on cycle and an observed receiver replug. '
                    'Original state was restored; this does not prove which memory technology stores the value.'
                    if product == 0xE8 else 'V3 sensitivity results do not establish the V2 setter or retention behavior.'),
            Finding('Per-program hardware DPI', 'Unavailable',
                    'Automatic focus-driven DPI changes remain disabled. V3 scalar sensitivity tests passed, '
                    'but the value survives off/on and receiver replug; service integration and restoration need acceptance.'
                    if product == 0xE8 else
                    'V2 sensitivity writes and service integration need acceptance before focus switching can change DPI.'),
            Finding('Native onboard macros and turbo', 'Partially verified' if product == 0xE8 else 'Unavailable',
                    'The development V3 receiver firmware1.1 passed once-only native keyboard playback, '
                    'shared objects, HyperShift and a reported off/on retention test. Native save admits only '
                    'once-only keyboard sequences and counted single-key macros. The combined Ctrl+K then M, '
                    'three-count F24, retention and zero-setting-write reuse test passed. Held/toggle/turbo, '
                    'counted multi-key sequences and native '
                    'F13–F23 desktop mapping still need acceptance. Full software actions use the Linux service.'
                    if product == 0xE8 else
                    'The V2 Synapse model disables onboard macro storage; its saved macro references do not '
                    'establish standalone playback. Use the Linux service for macros and turbo.'),
            Finding('Onboard slots', 'One slot' if product == 0xB4 else 'Inventory only',
                    'V2 exposes one stored slot; the active mirror is not another saved profile.' if product == 0xB4 else
                    'V3 advertises up to five slots. Read the mouse for its assigned slots; '
                    'new-slot initialization, lossless restoration and native selection remain unverified.'),
            Finding('Native storage compaction', 'Unavailable',
                    'Managed unused macro deletion is implemented for the development V3 firmware1.1, with live acceptance pending. '
                    'Deletion may leave recyclable bytes. The traced Synapse format/rebuild omits settings and opaque data; '
                    'it cannot yet preserve arbitrary mouse state.' if product == 0xE8 else
                    'V2 onboard macro storage is not admitted; V3 reclamation paths do not establish V2 support.')]
