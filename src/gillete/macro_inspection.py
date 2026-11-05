"""Bounded, inert inspection of Synapse protocol-25 macro data.

Source-derived record shapes are documented in docs/synapse-macro-turbo-research.md.
This is not an executable Action decoder and does not establish Naga playback.
"""

from .protocol import ProtocolError


MAX_BYTES = 4096
MAX_RECORDS = MAX_BYTES // 2
RECORD_SIZES = {1: 2, 2: 2, 8: 2, 10: 2, 17: 2, 18: 3, 19: 4, 20: 5, 21: 5}


def inspect(data: bytes) -> dict:
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ProtocolError('Macro inspection requires at most 4096 raw bytes')
    records, warnings = [], []
    offset, held_mouse = 0, 0
    held_keys = set()
    reason = None
    while offset < len(data) and len(records) < MAX_RECORDS:
        opcode = data[offset]
        size = RECORD_SIZES.get(opcode, 0)
        if not size:
            reason = 'unknown-opcode'
            break
        if offset + size > len(data):
            reason = 'truncated-record'
            break
        raw = data[offset:offset + size]
        record = {'offset': offset, 'raw': raw.hex()}
        if opcode in (1, 2):
            usage, pressed = raw[1], opcode == 1
            record.update(kind='key', hid_usage=usage, pressed=pressed)
            if not usage:
                warnings.append({'offset': offset, 'reason': 'zero-key-usage'})
            if pressed:
                if usage in held_keys:
                    warnings.append({'offset': offset, 'reason': 'duplicate-key-press', 'hid_usage': usage})
                held_keys.add(usage)
            elif usage not in held_keys:
                warnings.append({'offset': offset, 'reason': 'key-release-without-press', 'hid_usage': usage})
            else:
                held_keys.remove(usage)
        elif opcode == 8:
            mask = raw[1]
            if mask & ~31:
                reason = 'unsupported-button-mask'
                break
            record.update(kind='mouse_buttons', mask=mask,
                          pressed=[button + 1 for button in range(5) if mask & (1 << button) and not held_mouse & (1 << button)],
                          released=[button + 1 for button in range(5) if held_mouse & (1 << button) and not mask & (1 << button)])
            held_mouse = mask
        elif opcode == 10:
            if raw[1] not in (1, 255):
                reason = 'unsupported-wheel-value'
                break
            record.update(kind='wheel', notches=1 if raw[1] == 1 else -1)
        elif 17 <= opcode <= 20:
            record.update(kind='delay', milliseconds=int.from_bytes(raw[1:], 'big'))
            if opcode == 20 and raw[1] & 128:
                warnings.append({'offset': offset, 'reason': 'synapse-signed-delay-ambiguity'})
        else:
            record.update(kind='cursor', x_raw=int.from_bytes(raw[1:3], 'big'),
                          y_raw=int.from_bytes(raw[3:5], 'big'), coordinate_mode='unverified')
        records.append(record)
        offset += size
    if offset < len(data) and reason is None:
        reason = 'record-limit'
    return {'format': 'synapse-protocol25-source', 'status': 'partial' if reason else 'decoded',
            'records': records, 'consumed_bytes': offset,
            'unparsed': {'offset': offset, 'raw': data[offset:].hex(), 'reason': reason} if reason else None,
            'held_at_boundary': {'keys': sorted(held_keys),
                                 'mouse_buttons': [button + 1 for button in range(5) if held_mouse & (1 << button)]},
            'warnings': warnings, 'firmware_playback_verified': False}
