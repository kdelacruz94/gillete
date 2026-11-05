import pytest

from gillete.macro_inspection import MAX_BYTES, RECORD_SIZES, inspect
from gillete.protocol import ProtocolError


def test_keyboard_combo_keeps_usages_order_and_actual_releases_without_becoming_actions():
    raw = bytes.fromhex('01e0010e020e02e0115001100210')  # Ctrl+K, 80 ms, M.
    result = inspect(raw)
    assert result['status'] == 'decoded' and result['unparsed'] is None
    assert result['consumed_bytes'] == len(raw)
    assert [record['kind'] for record in result['records']] == ['key'] * 4 + ['delay', 'key', 'key']
    assert [(r['hid_usage'], r['pressed']) for r in result['records'] if r['kind'] == 'key'] == [
        (224, True), (14, True), (14, False), (224, False), (16, True), (16, False)]
    assert result['records'][4]['milliseconds'] == 80
    assert result['held_at_boundary'] == {'keys': [], 'mouse_buttons': []}
    assert not result['warnings'] and result['firmware_playback_verified'] is False
    assert b''.join(bytes.fromhex(r['raw']) for r in result['records']) == raw


@pytest.mark.parametrize('opcode,value', [(17, 0), (17, 255), (18, 256), (18, 65535),
                                        (19, 65536), (19, 16777215), (20, 16777216),
                                        (20, 2147483648), (20, 4294967295)])
def test_delays_keep_width_unsigned_bits_and_flag_synapse_signed_decode_ambiguity(opcode, value):
    raw = bytes((opcode,)) + value.to_bytes(RECORD_SIZES[opcode] - 1, 'big')
    result = inspect(raw)
    assert result['records'][0]['milliseconds'] == value
    assert bool(result['warnings']) == (value >= 2147483648)
    assert result['records'][0]['raw'] == raw.hex()


def test_mouse_records_are_full_state_masks_and_keep_all_simultaneous_changes():
    result = inspect(bytes.fromhex('0803081c0800'))
    assert [(r['mask'], r['pressed'], r['released']) for r in result['records']] == [
        (3, [1, 2], []), (28, [3, 4, 5], [1, 2]), (0, [], [3, 4, 5])]
    assert result['held_at_boundary']['mouse_buttons'] == []


def test_wheel_notches_and_cursor_raw_coordinates_do_not_guess_coordinate_mode():
    result = inspect(bytes.fromhex('0a010aff15ffff8000'))
    assert [r['notches'] for r in result['records'][:2]] == [1, -1]
    assert result['records'][2] == {'offset': 4, 'raw': '15ffff8000', 'kind': 'cursor',
                                    'x_raw': 65535, 'y_raw': 32768, 'coordinate_mode': 'unverified'}


def test_held_keys_and_buttons_are_reported_without_synthetic_release_or_missing_key_repair():
    raw = bytes.fromhex('0104010402050803')
    result = inspect(raw)
    assert len(result['records']) == 4
    assert result['held_at_boundary'] == {'keys': [4], 'mouse_buttons': [1, 2]}
    assert [w['reason'] for w in result['warnings']] == ['duplicate-key-press', 'key-release-without-press']
    assert b''.join(bytes.fromhex(r['raw']) for r in result['records']) == raw


@pytest.mark.parametrize('raw,reason', [(b'\x08\x20', 'unsupported-button-mask'),
                                      (b'\x0a\x02', 'unsupported-wheel-value'),
                                      (b'\x03\x00\x01\x04', 'unknown-opcode'),
                                      (b'\x15\x00\x00\x00', 'truncated-record')])
def test_uncertain_record_stops_at_its_boundary_and_keeps_the_entire_remaining_stream(raw, reason):
    prefix = bytes.fromhex('01040204')
    result = inspect(prefix + raw)
    assert result['status'] == 'partial' and result['consumed_bytes'] == len(prefix)
    assert result['unparsed'] == {'offset': len(prefix), 'raw': raw.hex(), 'reason': reason}
    assert b''.join(bytes.fromhex(r['raw']) for r in result['records']) + bytes.fromhex(result['unparsed']['raw']) == prefix + raw


def test_every_truncated_record_and_unknown_opcode_is_bounded_and_never_resynchronized():
    for opcode, size in RECORD_SIZES.items():
        for length in range(1, size):
            raw = bytes((opcode,)) + bytes(length - 1)
            result = inspect(raw)
            assert result['unparsed'] == {'offset': 0, 'raw': raw.hex(), 'reason': 'truncated-record'}
            assert result['records'] == []
    for opcode in set(range(256)) - RECORD_SIZES.keys():
        result = inspect(bytes((opcode, 1, 4)))
        assert result['unparsed']['reason'] == 'unknown-opcode' and result['consumed_bytes'] == 0


def test_size_limit_empty_stream_and_maximum_record_count():
    assert inspect(b'')['records'] == []
    result = inspect(bytes.fromhex('1100') * (MAX_BYTES // 2))
    assert len(result['records']) == MAX_BYTES // 2 and result['status'] == 'decoded'
    for data in (bytes(MAX_BYTES + 1), bytearray(b'\x01\x04'), '0104', None):
        with pytest.raises(ProtocolError):
            inspect(data)
