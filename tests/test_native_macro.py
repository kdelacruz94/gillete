import pytest

from gillete.compile_onboard import SoftwareOnly
from gillete.model import Action, Step
from gillete.native_macro import compile_macro, delay, metadata
from gillete import macro_memory as memory
from gillete.protocol import ProtocolError


def test_once_macro_vector_and_mixed_endian_metadata():
    compiled = compile_macro(Action('macro', steps=(Step('down', 'KEY_F24'),
                             Step('wait', milliseconds=80), Step('up', 'KEY_F24'))))
    assert compiled.data.hex() == '017311500273'
    assert compiled.items == 3 and compiled.allocation_bytes == 512
    assert compiled.binding(0x1234).hex() == '03031234010000'
    raw = metadata(compiled, '00112233-4455-6677-8899-aabbccddeeff', 'Gillete test')
    assert len(raw) == 250
    assert raw[:20].hex() == '33221100554477668899aabbccddeeff03000000'
    assert raw[20:33] == b'Gillete test\0' and raw[120:] == bytes(130)


def test_chords_repetition_and_turbo_preserve_order_and_explicit_trailing_gap():
    action = Action('macro', steps=(Step('down', 'KEY_LEFTCTRL'), Step('down', 'KEY_K'),
                                   Step('up', 'KEY_K'), Step('up', 'KEY_LEFTCTRL'),
                                   Step('down', 'KEY_M'), Step('up', 'KEY_M')),
                    playback='count', count=4, interval_ms=300)
    compiled = compile_macro(action)
    assert compiled.data.hex() == '01e0010e020e02e00110021012012c'
    assert compiled.trailing_gap_ms == 300 and compiled.items == 7
    assert compiled.binding(7).hex() == '03030007040000'
    for mode, prefix in [('held', '0402'), ('toggle', '0502')]:
        turbo = compile_macro(Action('turbo', keys=('KEY_LEFTCTRL', 'KEY_1'), playback=mode,
                                     interval_ms=140, press_ms=20))
        assert turbo.data.hex() == '01e0011e1114021e02e01178'
        assert turbo.binding(32767).hex() == prefix + '7fff000000'


def test_mouse_state_and_each_wheel_notch_are_serialized():
    action = Action('macro', steps=(Step('down', 'BTN_LEFT'), Step('down', 'BTN_EXTRA'),
                                   Step('up', 'BTN_LEFT'), Step('up', 'BTN_EXTRA'),
                                   Step('relative', axis='REL_WHEEL', value=-3)))
    compiled = compile_macro(action)
    assert compiled.data.hex() == '08010811081008000aff0aff0aff'
    assert compiled.items == 7


@pytest.mark.parametrize('value,hexed', [(0, '1100'), (255, '11ff'), (256, '120100'),
                                      (65536, '13010000'), (16777216, '1401000000')])
def test_delay_width(value, hexed):
    assert delay(value).hex() == hexed


@pytest.mark.parametrize('value', [-1, True, 2**31])
def test_ambiguous_delay_rejected(value):
    with pytest.raises(SoftwareOnly): delay(value)


def test_unsupported_movement_media_oversize_and_count_stay_software_only():
    cases = [Action('disabled'), Action('macro', steps=(Step('relative', axis='REL_X', value=1),)),
             Action('macro', steps=(Step('relative', axis='REL_HWHEEL', value=1),)),
             Action('macro', steps=(Step('down', 'KEY_PLAYPAUSE'), Step('up', 'KEY_PLAYPAUSE'))),
             Action('macro', steps=(Step('relative', axis='REL_WHEEL', value=2049),)),
             Action('macro', steps=(Step('wait', milliseconds=1),) * 2049),
             Action('macro', steps=(Step('wait', milliseconds=1),), playback='count', count=256)]
    for action in cases:
        with pytest.raises(SoftwareOnly): compile_macro(action)


def test_packet_shapes_use_actual_data_length_and_bounded_chunks():
    assert memory.allocate(7, 6).payload.hex() == '000700000006'
    assert memory.memory_chunk(7, 72, b'ab').payload.hex() == '000700000048026162'
    assert memory.name_chunk(7, 192, b'ab').payload.hex() == '000700c000fa6162'
    assert memory.delete(7).payload == b'\0\7'
    for identifier in (0, True, 32768):
        with pytest.raises(ProtocolError): memory.allocate(identifier, 6)
    for call in (lambda: memory.allocate(1, 4097), lambda: memory.memory_chunk(1, 4095, b'ab'),
                 lambda: memory.memory_chunk(1, 0, bytes(73)),
                 lambda: memory.name_chunk(1, 249, b'ab'), lambda: memory.name_chunk(1, 0, bytes(65))):
        with pytest.raises(ProtocolError): call()


class MetadataDevice:
    def __init__(self): self.commands = []
    def execute(self, command):
        self.commands.append(command)
        offset = int.from_bytes(command.payload[2:4], 'big')
        amount = len(command.payload) - 6
        return command.payload[:4] + b'\x12\x34' + bytes(range(250))[offset:offset + amount]


def test_metadata_reads_exact_chunks_preserving_unknown_size_field_and_echo():
    io = MetadataDevice()
    assert memory.read_name(io, 7) == bytes(range(250))
    assert [len(c.payload) for c in io.commands] == [70, 70, 70, 64]
    assert [int.from_bytes(c.payload[2:4], 'big') for c in io.commands] == [0, 64, 128, 192]
    from test_macro_reads import response
    command = io.commands[0]
    assert not command.matches(response(command, b'\0\7\0\1' + bytes(66)))
