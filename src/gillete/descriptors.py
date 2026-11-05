"""Bounded HID report-size inspection; never infers physical button meanings.

Lengths include a report-ID byte only for numbered reports. HID feature ioctls
also require a leading zero for unnumbered reports, outside this descriptor size.
See USB HID 1.11 sections 6.2.2 and 8. This is deliberately a size inspector,
not a generic HID input decoder; unsupported descriptor constructs are rejected.
"""

from .protocol import ProtocolError


def report_sizes(descriptor: bytes) -> dict:
    if not isinstance(descriptor, bytes) or not 1 <= len(descriptor) <= 4096:
        raise ProtocolError('HID descriptor must contain 1–4096 bytes')
    state = {'size': 0, 'count': 0, 'id': 0}
    stack, collections = [], 0
    bits = {'input': {}, 'output': {}, 'feature': {}}
    offset = 0
    while offset < len(descriptor):
        prefix = descriptor[offset]
        if prefix == 0xFE:
            raise ProtocolError('Long HID items need separate descriptor review')
        length = (0, 1, 2, 4)[prefix & 3]
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        end = offset + 1 + length
        if end > len(descriptor):
            raise ProtocolError('Truncated HID descriptor item')
        value = int.from_bytes(descriptor[offset + 1:end], 'little')
        offset = end
        if kind == 1:  # Globals persist across main items and collections.
            if tag in (7, 8, 9):
                if not length:
                    raise ProtocolError('Missing HID report size/count/ID value')
                name = {7: 'size', 8: 'id', 9: 'count'}[tag]
                maximum = {'size': 64, 'id': 255, 'count': 4096}[name]
                if not 1 <= value <= maximum:
                    raise ProtocolError('Unsupported HID report size/count/ID')
                state[name] = value
            elif tag == 10:
                if length or len(stack) >= 32:
                    raise ProtocolError('Invalid or excessive HID global Push')
                stack.append(dict(state))
            elif tag == 11:
                if length or not stack:
                    raise ProtocolError('Unmatched HID global Pop')
                state = stack.pop()
            elif tag > 11:
                raise ProtocolError('Unknown HID global item')
        elif kind == 0:
            if tag == 10:
                if length != 1 or collections >= 32:
                    raise ProtocolError('Invalid or excessive HID collection')
                collections += 1
            elif tag == 12:
                if length or not collections:
                    raise ProtocolError('Unmatched HID End Collection')
                collections -= 1
            elif tag in (8, 9, 11):
                if not collections or not length or not state['size'] or not state['count']:
                    raise ProtocolError('Incomplete HID report fields')
                reports = bits[{8: 'input', 9: 'output', 11: 'feature'}[tag]]
                identifier = str(state['id'])
                reports[identifier] = reports.get(identifier, 0) + state['size'] * state['count']
                if reports[identifier] > 32768:
                    raise ProtocolError('HID report exceeds inspection size limit')
            else:
                raise ProtocolError('Unknown HID main item')
        elif kind != 2 or tag not in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10):
            raise ProtocolError('Unknown HID descriptor item')
    if collections or stack or not any(bits.values()):
        raise ProtocolError('Incomplete HID descriptor')
    identifiers = {identifier for reports in bits.values() for identifier in reports}
    if '0' in identifiers and len(identifiers) > 1:
        raise ProtocolError('Mixed numbered and unnumbered HID reports need review')
    return {kind: {identifier: (size + 7) // 8 + (identifier != '0')
                   for identifier, size in sorted(reports.items(), key=lambda item: int(item[0]))}
            for kind, reports in bits.items()}
