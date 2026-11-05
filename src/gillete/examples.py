"""User-requested examples, available for explicit import; never auto-activated."""

from .model import Action, Layers, MODELS, Profile, sequence


def example_profiles() -> list[Profile]:
    # VS Code's standard language-mode chord is Ctrl+K, M. These are editable
    # examples: the user's application keymap remains authoritative.
    definitions = [
        ("excel-example", "Excel sequence", sequence(("KEY_LEFTALT", "KEY_H"), ("KEY_O",), ("KEY_A",))),
        ("vscode-example", "VS Code sequence", sequence(("KEY_LEFTCTRL", "KEY_K"), ("KEY_M",))),
        ("herdr-example", "Herdr sequence", sequence(("KEY_LEFTCTRL", "KEY_B"), ("KEY_LEFTALT", "KEY_S"))),
        ("wow-example", "WoW toggle 1", Action("turbo", keys=("KEY_1",), playback="toggle",
                                               interval_ms=100, press_ms=30)),
    ]
    return [Profile(identifier, name, Layers(normal={"side_1": action}),
                    {MODELS[0]: Layers(normal={"dpi_up": Action("hypershift", playback="held")}),
                     MODELS[1]: Layers(normal={"ring_finger": Action("hypershift", playback="held")})})
            for identifier, name, action in definitions]
