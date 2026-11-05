"""Profile selection and atomic, revision-checked local persistence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .model import ConfigurationError, MODELS, Profile, integer, object_fields


@dataclass(frozen=True)
class Window:
    address: str = ""
    app_class: str = ""
    title: str = ""
    executable: str = ""


@dataclass(frozen=True)
class Rule:
    profile: str
    app_class: str = ""
    title: str = ""
    executable: str = ""
    model: str = ""
    priority: int = 0

    def __post_init__(self):
        for name in ("profile", "app_class", "title", "executable", "model"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 4096:
                raise ConfigurationError(f"Invalid rule {name}")
        if not self.profile or not any((self.app_class, self.title, self.executable)):
            raise ConfigurationError("Rules need a profile and at least one window condition")
        if self.model and self.model not in MODELS:
            raise ConfigurationError("Unknown rule device")
        integer(self.priority, "Rule priority", -10000, 10000)

    def matches(self, model: str, window: Window) -> bool:
        if not window.address or (self.model and self.model != model):
            return False
        return all(not pattern or fnmatchcase(getattr(window, name), pattern)
                   for name, pattern in (("app_class", self.app_class),
                                         ("title", self.title), ("executable", self.executable)))


@dataclass
class Configuration:
    profiles: dict[str, Profile] = field(default_factory=lambda: {"default": Profile("default", "Default")})
    defaults: dict[str, str] = field(default_factory=lambda: {m: "default" for m in MODELS})
    pinned: dict[str, str] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    revision: int = 0

    def validate(self):
        integer(self.revision, "Revision", 0, 2**53 - 1)
        if not 1 <= len(self.profiles) <= 1000 or len(self.rules) > 1000:
            raise ConfigurationError("Invalid profile or rule count")
        if set(self.defaults) != set(MODELS) or set(self.pinned) - set(MODELS):
            raise ConfigurationError("Every mouse model needs a default profile")
        references = [*self.defaults.values(), *self.pinned.values(), *(r.profile for r in self.rules)]
        for identifier, profile in self.profiles.items():
            # GUI edits mutate profiles; validate their current values as well
            # as values originally admitted by the import constructor.
            Profile.parse(profile.json())
            if identifier != profile.id:
                raise ConfigurationError("Profile identity mismatch")
            for layer in [profile.common, *profile.overrides.values()]:
                references.extend(a.target for a in [*layer.normal.values(), *layer.shifted.values()]
                                  if a.kind == "profile")
        if any(not isinstance(ref, str) or ref not in self.profiles for ref in references):
            raise ConfigurationError("A rule, pin, default, or action refers to a missing profile")

    def select(self, model: str, window: Window) -> Profile:
        if model not in MODELS:
            raise ConfigurationError("Unknown model")
        if model in self.pinned:
            return self.profiles[self.pinned[model]]
        for rule in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            if rule.matches(model, window):
                return self.profiles[rule.profile]
        return self.profiles[self.defaults[model]]

    def json(self) -> dict:
        from dataclasses import asdict
        self.validate()
        return {"version": 1, "revision": self.revision,
                "profiles": [p.json() for p in self.profiles.values()],
                "defaults": self.defaults, "pinned": self.pinned,
                "rules": [asdict(r) for r in self.rules]}

    @classmethod
    def parse(cls, data: Any) -> Configuration:
        fields = object_fields(data, {"version", "revision", "profiles", "defaults", "pinned", "rules"}, "configuration")
        if type(fields.get("version")) is not int or fields["version"] != 1:
            raise ConfigurationError("Unsupported configuration version")
        profiles, rules = fields.get("profiles"), fields.get("rules", [])
        if not isinstance(profiles, list) or not isinstance(rules, list):
            raise ConfigurationError("Profiles/rules must be arrays")
        if not 1 <= len(profiles) <= 1000 or len(rules) > 1000:
            raise ConfigurationError("Too many profiles/rules or no profiles")
        parsed = [Profile.parse(p) for p in profiles]
        if len({p.id for p in parsed}) != len(parsed):
            raise ConfigurationError("Duplicate profile ID")
        defaults, pinned = fields.get("defaults", {}), fields.get("pinned", {})
        if not isinstance(defaults, dict) or not isinstance(pinned, dict):
            raise ConfigurationError("Defaults/pins must be objects")
        result = cls({p.id: p for p in parsed}, defaults, pinned,
                     [Rule(**object_fields(r, set(Rule.__dataclass_fields__), "rule")) for r in rules],
                     fields.get("revision", 0))
        result.validate()
        return result


class ConflictError(ConfigurationError):
    pass


def default_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "gillete/profiles.json"


class ProfileStore:
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else default_path()

    def read(self) -> Configuration:
        try:
            with self.path.open("rb") as file:
                data = file.read(self.MAX_BYTES + 1)
        except FileNotFoundError:
            return Configuration()
        if len(data) > self.MAX_BYTES:
            raise ConfigurationError("Configuration exceeds size limit")
        try:
            return Configuration.parse(json.loads(data))
        except (TypeError, ValueError, KeyError) as e:
            raise ConfigurationError(f"Cannot load {self.path}: {e}") from e

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def save(self, config: Configuration, *, expected_revision: int) -> None:
        config.validate()
        with self._lock():
            if self.read().revision != expected_revision:
                raise ConflictError("Profiles changed elsewhere. Reload before saving.")
            data = config.json()
            data["revision"] = expected_revision + 1
            encoded = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
            if len(encoded) > self.MAX_BYTES:
                raise ConfigurationError("Configuration exceeds size limit")
            fd, name = tempfile.mkstemp(prefix=".profiles-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(encoded)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(name).unlink(missing_ok=True)
            config.revision = data["revision"]
