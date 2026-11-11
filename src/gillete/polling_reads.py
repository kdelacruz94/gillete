"""Candidate V3 polling getters, isolated from production settings.

Codes are from retained Synapse factory32135/84816. A recognized code is not a
measured report rate or proof that Synapse selects this route on this receiver.
See docs/remaining-native-protocols.md for source identities and dispatch gaps.
"""

from .protocol import Command, DeviceStatusError, ProtocolError


OPERATIONS = {'profile': 0x8E, 'high-speed': 0xC0}
INTERVALS = {1: 1000, 2: 500, 3: 333, 4: 250, 5: 200, 8: 125, 10: 100}
HIGH_SPEED = {1: 8000, 2: 4000, 4: 2000, 8: 1000, 16: 500, 32: 250, 64: 125}


def validate_request(product, command):
    if (type(product) is not int or product != 0xE8
            or command.category != 0 or command.operation not in OPERATIONS.values()
            or command.transaction != 0x1F or len(command.payload) != 2
            or not 1 <= command.payload[0] <= 5 or command.payload[1] != 0):
        raise ProtocolError('Polling diagnostics permit only V3 receiver profile/high-speed getters with a bounded profile selector')


def query(route, profile):
    if route not in OPERATIONS or type(profile) is not int or not 1 <= profile <= 5:
        raise ProtocolError('Unknown polling route or profile selector')
    return Command(0, OPERATIONS[route], bytes((profile, 0)))


def decode(route, profile, raw):
    query(route, profile)
    if not isinstance(raw, bytes) or len(raw) != 2 or raw[0] != profile:
        raise ProtocolError('Polling response did not echo the requested profile selector')
    rate = (HIGH_SPEED if route == 'high-speed' else INTERVALS).get(raw[1])
    return {'raw': raw.hex(), 'code': raw[1], 'nominal_hz': rate,
            'status': 'recognized-code' if rate is not None else 'unknown-code'}


def _read(io, route, profile):
    entry = {'route': route, 'profile': profile}
    try:
        raw = io.execute(query(route, profile))
        # Keep malformed/unknown bytes as evidence even when parsing rejects
        # the selector. An unfamiliar high-speed code must never become 8 kHz.
        entry['raw'] = raw.hex()
        entry.update(decode(route, profile, raw))
    except (OSError, ProtocolError) as error:
        entry.update(status='query-failed', error=str(error))
        if isinstance(error, DeviceStatusError):
            entry['device_status'] = error.status
    return entry


def observe(io, assigned):
    assigned = tuple(assigned)
    if (io.product != 0xE8 or not 1 <= len(assigned) <= 5
            or any(type(value) is not int or not 1 <= value <= 5 for value in assigned)
            or len(set(assigned)) != len(assigned)):
        raise ProtocolError('Polling diagnostics require the V3 receiver and its current assigned profile IDs')
    result = {'status': 'queries-completed', 'before': [], 'after': [], 'values_unchanged': None,
              'dispatch_verified': False, 'cadence_verified': False, 'writes_verified': False,
              'note': 'Nominal codes do not establish the effective route, measured rate or write support.'}
    for route in OPERATIONS:
        for profile in assigned:
            entry = _read(io, route, profile)
            result['before'].append(entry)
            if entry['status'] == 'query-failed':
                if entry.get('device_status') in (3, 5):
                    # A clean rejection ends this family, not all unrelated
                    # queries. It says nothing about other transports/firmware.
                    result['status'] = 'partially-queried'
                    break
                result['status'] = 'stopped'
                return result
    return result


def recheck(io, result):
    """Repeat only completed, well-formed reads; never retry a failed request."""
    if result['status'] == 'stopped':
        return
    for original in result['before']:
        if original['status'] not in ('recognized-code', 'unknown-code'):
            continue
        entry = _read(io, original['route'], original['profile'])
        result['after'].append(entry)
        if entry['status'] == 'query-failed':
            result['status'] = 'verification-unavailable'
            return
        if entry['raw'] != original['raw']:
            result.update(status='values-changed', values_unchanged=False)
            return
    if result['after']:
        result['values_unchanged'] = True
