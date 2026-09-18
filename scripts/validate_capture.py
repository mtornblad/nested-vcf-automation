#!/usr/bin/env python3
"""Offline contracts for the captured Full Stack blueprint and package inventory."""
from __future__ import annotations

import json
from pathlib import Path
import jsonschema
from validate_modular import check_references, load, strings

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / 'src/main/resources/blueprints/Full Stack VCF - Capture/content.yaml'


def validate_blueprint(blueprint):
    errors = check_references(blueprint)
    resources = blueprint['resources']
    def require(ok, message):
        if not ok:
            errors.append(message)
    namespace = resources['Namespace']['properties']
    require(namespace.get('existing') is False, 'Capture must create its own namespace')
    require('VPC_Main' in resources, 'Capture must create its own VPC')
    require('VPC_Attachment' in resources['Namespace'].get('dependsOn', []), 'Namespace must follow VPC attachment')
    for key, resource in resources.items():
        manifest = resource.get('properties', {}).get('manifest', {})
        require(not resource['type'].startswith('Custom.'), f'{key}: captured labs must not run installation custom resources')
        require(manifest.get('kind') not in ('Secret', 'PersistentVolumeClaim'), f'{key}: capture must inherit image disks and credentials')
        if manifest.get('kind') == 'VirtualMachine':
            spec = manifest['spec']
            require('biosUUID' not in spec and 'volumes' not in spec, f'{key}: exported runtime identity or volumes must not be replayed')
            bootstrap = spec.get('bootstrap', {})
            require(len(bootstrap) == 1 and next(iter(bootstrap), '') in ('linuxPrep','sysprep') and next(iter(bootstrap.values()), {}) == {'customizeAtNextPowerOn':False}, f'{key}: guest customization must stay disabled')
            require(spec.get('groupName') == '${variable.vm_group_name}', f'{key}: VM group link missing')
            require('wait' not in resource['properties'], f'{key}: waiting for power-on before group creation can deadlock')
    esxi = resources['VM_ESXs']['properties']
    require(esxi.get('count') == '${length(variable.esx_settings.servers)}', 'ESXi count must follow capture list')
    require(esxi['manifest']['spec']['imageName'] == '${variable.esx_settings.servers[count.index].image}', 'Each ESXi must use its own captured image')
    group = resources['VM_Group']['properties']['manifest']['spec']
    require('map_by(variable.esx_settings.servers' in group['bootOrder'][1]['members'], 'VM group membership must follow ESXi list')
    require(set(resources['VM_Group']['dependsOn']) == {'VyOS_Machine','VM_ESXs','Installer_VM','Jumphost_VM'}, 'Group must follow all VM declarations')
    require('vcf_deployment_json' not in blueprint.get('outputs', {}), 'Capture must not generate a fresh installation specification')
    schema = blueprint['inputs']['esxi_captures']
    try:
        jsonschema.Draft7Validator.check_schema(schema)
        jsonschema.validate(schema['default'], schema)
    except (jsonschema.ValidationError, jsonschema.SchemaError) as error:
        errors.append('Invalid ESXi capture input: ' + error.message)
    for key in ('name','image'):
        values = [host.get(key) for host in schema['default']]
        require(len(values) == len(set(values)), f'Captured ESXi {key} values must be unique')
    classes = blueprint['variables']['namespace_settings']['vm_classes']
    require(len(classes) == len({item['name'] for item in classes}), 'Namespace VM class bindings must be unique')
    return errors


def validate():
    errors = validate_blueprint(load(CAPTURE))
    names = load(ROOT / 'content.yaml')['blueprint']
    expected = {'Full Stack VCF', 'Full Stack VCF - Capture'} | {'Nested VCF Modular - ' + role for role in ('Foundation','ESXi','Installer','Jumphost')}
    if set(names) != expected or len(names) != len(expected):
        errors.append('One package must select all six blueprints exactly once')
    ids = []
    for name in names:
        details = json.loads((ROOT / 'src/main/resources/blueprints' / name / 'details.json').read_text())
        if details['name'] != name:
            errors.append(f'{name}: metadata name mismatch')
        ids.append(details['id'])
    if len(ids) != len(set(ids)):
        errors.append('Blueprint IDs must be unique')
    return errors


if __name__ == '__main__':
    issues = validate()
    for issue in issues:
        print('ERROR: ' + issue)
    if not issues:
        print('Capture blueprint and six-blueprint package inventory are valid.')
    raise SystemExit(bool(issues))
