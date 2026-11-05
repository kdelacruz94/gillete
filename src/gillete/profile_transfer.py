"""Portable profile graphs and rule-aware copying, without service activation."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from uuid import uuid4

from .model import ConfigurationError, MODELS, Profile, object_fields
from .onboard import durable_json
from .profiles import Configuration, ProfileStore, Rule


def references(profile):
    return {action.target for layer in (profile.common, *profile.overrides.values())
            for action in (*layer.normal.values(), *layer.shifted.values()) if action.kind == 'profile'}


def fresh_id(occupied):
    for _ in range(128):
        identifier = uuid4().hex
        if identifier not in occupied:
            return identifier
    raise ConfigurationError('Could not allocate a new profile ID')


def available_name(name, suffix, used, *, force=False):
    if not force and name not in used:
        return name
    for number in range(1, 2002):
        tail = suffix + (f' {number}' if number > 1 else '')
        candidate = name[:256 - len(tail)] + tail
        if candidate not in used:
            return candidate
    raise ConfigurationError('Could not choose a distinct profile name')


def rewrite(profile, identifiers, name):
    result = Profile.parse(profile.json())
    result.id, result.name = identifiers[profile.id], name
    for layer in (result.common, *result.overrides.values()):
        for bindings in (layer.normal, layer.shifted):
            for control, action in bindings.items():
                if action.kind == 'profile' and action.target in identifiers:
                    bindings[control] = replace(action, target=identifiers[action.target])
    return result


def duplicate(config, identifier):
    config.validate()
    original = config.profiles[identifier]
    result = deepcopy(config)
    new_id = fresh_id(set(config.profiles))
    name = available_name(original.name, ' copy', {p.name for p in config.profiles.values()}, force=True)
    result.profiles[new_id] = rewrite(original, {identifier: new_id}, name)
    copied_rules = [replace(rule, profile=new_id, enabled=False) for rule in config.rules if rule.profile == identifier]
    result.rules.extend(copied_rules)
    result.validate()
    return result, new_id, copied_rules


def export_document(config, root):
    config.validate()
    if root not in config.profiles:
        raise ConfigurationError('Choose an existing profile to export')
    included, pending = set(), [root]
    while pending:
        identifier = pending.pop()
        if identifier in included:
            continue
        included.add(identifier)
        pending.extend(references(config.profiles[identifier]) - included)
    ordered = [root, *(identifier for identifier in config.profiles if identifier in included and identifier != root)]
    return {'version': 2, 'root': root, 'profiles': [config.profiles[identifier].json() for identifier in ordered],
            'rules': [asdict(rule) for rule in config.rules if rule.profile in included]}


def write_export(path, document):
    # An interrupted export must not truncate an earlier usable backup.
    if len((json.dumps(document, indent=2) + '\n').encode()) > ProfileStore.MAX_BYTES:
        raise ConfigurationError('Export exceeds the profile-file size limit')
    durable_json(path, document)


@dataclass
class Bundle:
    root: str
    profiles: dict[str, Profile]
    rules: tuple[Rule, ...] = ()
    legacy: bool = False


def parse_bundle(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int:
        raise ConfigurationError('Unsupported profile file')
    if data['version'] == 1:
        fields = object_fields(data, {'version', 'profile'}, 'legacy profile file')
        profile = Profile.parse(fields.get('profile'))
        return Bundle(profile.id, {profile.id: profile}, legacy=True)
    if data['version'] != 2:
        raise ConfigurationError('Unsupported profile version')
    fields = object_fields(data, {'version', 'root', 'profiles', 'rules'}, 'profile bundle')
    profiles, rules = fields.get('profiles'), fields.get('rules', [])
    if (not isinstance(profiles, list) or not 1 <= len(profiles) <= 1000
            or not isinstance(rules, list) or len(rules) > 1000):
        raise ConfigurationError('Invalid profile/rule count in bundle')
    parsed = [Profile.parse(value) for value in profiles]
    if len({p.id for p in parsed}) != len(parsed):
        raise ConfigurationError('Duplicate profile IDs in bundle')
    root = fields.get('root')
    if not isinstance(root, str) or root not in {p.id for p in parsed}:
        raise ConfigurationError('Bundle root is not an included profile')
    try:
        parsed_rules = [Rule(**object_fields(rule, set(Rule.__dataclass_fields__), 'rule')) for rule in rules]
    except TypeError as error:
        raise ConfigurationError('Malformed program rule in bundle') from error
    # Bundles must be closed graphs. A matching local ID must never hide a
    # missing exported dependency and silently bind an unrelated local profile.
    config = Configuration({p.id: p for p in parsed}, {model: root for model in MODELS}, rules=parsed_rules)
    config.validate()
    return Bundle(root, config.profiles, tuple(parsed_rules))


def read_bundle(path):
    with path.open('rb') as file:
        raw = file.read(ProfileStore.MAX_BYTES + 1)
    if len(raw) > ProfileStore.MAX_BYTES:
        raise ConfigurationError('Profile file is too large')
    try:
        return parse_bundle(json.loads(raw))
    except RecursionError as error:
        raise ConfigurationError('Profile file is nested too deeply') from error


@dataclass
class ImportPlan:
    base: Configuration
    root: str
    profiles: tuple[tuple[str, str, str], ...]  # Original name, imported name, new ID.
    rules: tuple[Rule, ...]
    existing_links: tuple[str, ...]

    def configuration(self, *, activate_rules=False):
        result = deepcopy(self.base)
        result.rules.extend(replace(rule, enabled=rule.enabled and activate_rules) for rule in self.rules)
        result.validate()
        return result


def plan_import(config, bundle):
    config.validate()
    if len(config.profiles) + len(bundle.profiles) > 1000:
        raise ConfigurationError('Import would exceed the profile limit')
    external = set().union(*(references(p) for p in bundle.profiles.values())) - bundle.profiles.keys()
    if external and (not bundle.legacy or not external <= config.profiles.keys()):
        raise ConfigurationError('This legacy export references profiles that are not included or available locally. '
                                 'Export it again as a bundle from a library containing its linked profiles.')
    occupied = set(config.profiles) | set(bundle.profiles)
    identifiers = {}
    for identifier in bundle.profiles:
        new_id = fresh_id(occupied) if identifier in config.profiles else identifier
        identifiers[identifier] = new_id
        occupied.add(new_id)
    result = deepcopy(config)
    used_names = {p.name for p in config.profiles.values()}
    choices = []
    for old_id, profile in bundle.profiles.items():
        name = available_name(profile.name, ' imported', used_names, force=old_id in config.profiles)
        used_names.add(name)
        rewritten = rewrite(profile, identifiers, name)
        result.profiles[rewritten.id] = rewritten
        choices.append((profile.name, name, rewritten.id))
    plan = ImportPlan(result, identifiers[bundle.root], tuple(choices),
                      tuple(replace(rule, profile=identifiers[rule.profile]) for rule in bundle.rules),
                      tuple(config.profiles[identifier].name for identifier in sorted(external)))
    plan.configuration()  # Validate the complete proposed save before review.
    return plan
