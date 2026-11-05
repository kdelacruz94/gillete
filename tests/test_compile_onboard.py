import pytest

from gillete.compile_onboard import CONTROL_IDS, SoftwareOnly, compile_profile, encode_action
from gillete.model import Action, Layers, MODELS, Profile, sequence
from gillete.onboard import Location


def baseline(model):
    return {Location(1, code, layer): bytes.fromhex("0202001e000000")
            for code in CONTROL_IDS[model].values() for layer in (0, 1)}


def test_keyboard_chord_modifiers_mouse_media_and_scroll_encoding():
    assert encode_action(Action("keys", keys=("KEY_LEFTALT", "KEY_H")), MODELS[0]) == bytes.fromhex("0202040b000000")
    assert encode_action(Action("keys", keys=("KEY_F24",)), MODELS[1]) == bytes.fromhex("02020073000000")
    assert encode_action(Action("keys", keys=("KEY_LEFTCTRL",)), MODELS[0]) == bytes.fromhex("020200e0000000")
    assert encode_action(Action("keys", keys=("BTN_RIGHT",)), MODELS[0]) == bytes.fromhex("01010200000000")
    assert encode_action(Action("scroll", value=-1), MODELS[0]) == bytes.fromhex("01010a00000000")


def test_macro_and_turbo_are_not_silently_dropped_from_onboard_plan():
    p = Profile("p", "P", Layers(normal={"side_1": sequence(("KEY_LEFTALT", "KEY_H"), ("KEY_O",))}))
    plan = compile_profile(p, MODELS[0], 1, baseline(MODELS[0]))
    assert not plan.writable and any("side_1" in issue and "service" in issue for issue in plan.issues)
    with pytest.raises(SoftwareOnly):
        encode_action(Action("turbo", keys=("KEY_1",), playback="toggle"), MODELS[0])


def test_all_physical_ids_and_per_device_shift_trigger():
    p = Profile("p", "P", Layers(normal={"side_1": Action("keys", keys=("KEY_A",))}), {
        MODELS[0]: Layers(normal={"dpi_up": Action("hypershift", playback="held")}),
        MODELS[1]: Layers(normal={"ring_finger": Action("hypershift", playback="held")}),
    })
    for model, count, trigger in ((MODELS[0], 42, 0x0B), (MODELS[1], 50, 0x39)):
        plan = compile_profile(p, model, 1, baseline(model))
        assert plan.writable and len(plan.targets) == count
        assert plan.targets[Location(1, trigger, 0)][0] == 0x0C
        assert plan.targets[Location(1, 0x40, 1)] == plan.targets[Location(1, 0x40, 0)]
        assert {w.control for w in plan.targets} >= {9, 10, 0x34, 0x35}


def test_missing_snapshot_is_rejected_before_compilation():
    with pytest.raises(ValueError):
        compile_profile(Profile("p", "P"), MODELS[0], 1, {})


def test_keep_stored_preserves_existing_synapse_hypershift_actions():
    values = baseline(MODELS[0])
    values[Location(1, 0x0B, 0)] = bytes.fromhex('0c010100000000')
    values[Location(1, 0x0B, 1)] = values[Location(1, 0x0B, 0)]
    values[Location(1, 0x40, 1)] = bytes.fromhex('05020000000000')
    values[Location(1, 0x34, 0)] = bytes.fromhex('0d04004b008e00')
    values[Location(1, 0x34, 1)] = bytes.fromhex('0202004a000000')
    plan = compile_profile(Profile('p', 'P'), MODELS[0], 1, values)
    assert plan.writable and plan.targets == values
    edited = Profile('p', 'P', Layers(normal={'side_1': Action('keys', keys=('KEY_F24',))}))
    plan = compile_profile(edited, MODELS[0], 1, values)
    assert plan.targets[Location(1, 0x40, 1)] == bytes.fromhex('02020073000000')
    assert plan.targets[Location(1, 0x34, 1)] == values[Location(1, 0x34, 1)]
