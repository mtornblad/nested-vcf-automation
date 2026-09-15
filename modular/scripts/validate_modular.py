#!/usr/bin/env python3
"""Validate modular blueprint references and the shared request contract offline."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load(path):
    return yaml.load(path.read_text(), Loader=UniqueLoader)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def check_references(blueprint):
    errors = []
    resources = blueprint["resources"]
    for name, resource in resources.items():
        for dependency in resource.get("dependsOn", []):
            if dependency not in resources:
                errors.append(f"{name} depends on an absent resource: {dependency}")
        if "wait" in resource.get("properties", {}).get("manifest", {}).get("spec", {}):
            errors.append(f"{name} has wait inside the guest manifest")
    for value in strings(blueprint):
        for prefix, key in re.findall(r"\b(resource|variable|input)\.([A-Za-z0-9_]+)", value):
            section = {"resource": "resources", "variable": "variables", "input": "inputs"}[prefix]
            if key not in blueprint.get(section, {}):
                errors.append(f"Unresolved {prefix}.{key}")
    return sorted(set(errors))


def validate():
    errors = []
    contract = json.loads((ROOT / "contracts/lab.schema.json").read_text())
    example = json.loads((ROOT / "contracts/lab-plan.example.json").read_text())
    jsonschema.Draft7Validator.check_schema(contract)
    jsonschema.validate(example, contract)
    descriptor = load(ROOT / "content.yaml")
    if len(descriptor["blueprint"]) != 4:
        errors.append("The modular package must select exactly four blueprints")
    for name in descriptor["blueprint"]:
        directory = ROOT / "src/main/resources/blueprints" / name
        blueprint = load(directory / "content.yaml")
        details = json.loads((directory / "details.json").read_text())
        if details["name"] != name:
            errors.append(f"{name}: metadata name differs")
        errors.extend(f"{name}: {issue}" for issue in check_references(blueprint))
        jsonschema.validate(example, blueprint["inputs"]["lab"])
        for key in ("lab_password", "vyos_rest_api_key"):
            if key in blueprint["inputs"] and "default" in blueprint["inputs"][key]:
                errors.append(f"{name}: credential default in {key}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-local", action="store_true")
    args = parser.parse_args()
    if args.clean_local:
        target = ROOT / "target"
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        return 0
    try:
        errors = validate()
    except (ValueError, OSError, yaml.YAMLError, jsonschema.ValidationError) as error:
        print(f"ERROR: {error}")
        return 1
    for error in errors:
        print(f"ERROR: {error}")
    if not errors:
        print("Four modular blueprints and the shared lab contract are valid.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
