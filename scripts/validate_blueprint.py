#!/usr/bin/env python3
"""Validate source-level contracts for the Full Stack VCF blueprint."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_PATH = (
    PROJECT_ROOT
    / "src"
    / "main"
    / "resources"
    / "blueprints"
    / "Full Stack VCF"
    / "content.yaml"
)
DETAILS_PATH = BLUEPRINT_PATH.with_name("details.json")
DESCRIPTOR_PATH = PROJECT_ROOT / "content.yaml"


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.load(handle, Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def load_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    blueprint = load_yaml(BLUEPRINT_PATH)
    descriptor = load_yaml(DESCRIPTOR_PATH)
    details = json.loads(DETAILS_PATH.read_text(encoding="utf-8"))
    raw = BLUEPRINT_PATH.read_text(encoding="utf-8")
    return blueprint, descriptor, details, raw


def property_map(resource: dict[str, Any]) -> dict[str, dict[str, Any]]:
    properties = resource["properties"]["manifest"]["spec"]["bootstrap"][
        "vAppConfig"
    ]["properties"]
    return {item["key"]: item.get("value", {}) for item in properties}


def property_keys(resource: dict[str, Any]) -> list[str]:
    """Return vApp keys without hiding duplicates through dictionary coercion."""

    return [
        item["key"]
        for item in resource["properties"]["manifest"]["spec"]["bootstrap"][
            "vAppConfig"
        ]["properties"]
    ]


def _sensitive_values(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (str(key),)
            if re.search(r"(?:password|api_key|token)$", str(key), re.IGNORECASE):
                found.append((".".join(child_path), child))
            found.extend(_sensitive_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_sensitive_values(child, path + (str(index),)))
    return found


def validate() -> list[str]:
    errors: list[str] = []
    try:
        blueprint, descriptor, details, raw = load_sources()
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        return [str(error)]

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(blueprint.get("formatVersion") == 2, "formatVersion must be 2")
    require(
        descriptor.get("blueprint") == ["Full Stack VCF"],
        "descriptor must select only Full Stack VCF",
    )
    require(details.get("name") == "Full Stack VCF", "details.json name mismatch")

    inputs = blueprint.get("inputs", {})
    for name in ("lab_password", "vyos_rest_api_key"):
        definition = inputs.get(name, {})
        require(definition.get("encrypted") is True, f"{name} must be encrypted")
        require("default" not in definition, f"{name} must not have a default")
    require(
        inputs.get("lab_password", {}).get("minLength") == 15,
        "lab_password must satisfy the 15-character VCF service minimum",
    )

    variables = blueprint.get("variables", {})
    allowed = {"${input.lab_password}", "${input.vyos_rest_api_key}"}
    for path, value in _sensitive_values(variables):
        require(value in allowed, f"{path} contains a committed credential")

    resources = blueprint.get("resources", {})
    secret = resources.get("Bootstrap_Secrets", {})
    secret_manifest = secret.get("properties", {}).get("manifest", {})
    require(secret_manifest.get("kind") == "Secret", "bootstrap Secret missing")

    vyos_settings = variables.get("vyos_settings", {})
    require(
        vyos_settings.get("dns", {}).get("local_resolver") == "127.0.0.1",
        "VyOS local resolver must be 127.0.0.1",
    )
    vyos_properties = property_map(resources.get("VyOS_Machine", {}))
    require(
        vyos_properties.get("dns", {}).get("value")
        == "${to_string(variable.vyos_settings.dns.local_resolver)}",
        "VyOS dns vApp property must reference the local resolver",
    )

    vyos_config = variables.get("vyos_config", "")
    required_dns_lines = (
        "set service dns forwarding listen-address "
        "${variable.vyos_settings.dns.local_resolver}",
        "set service dns forwarding listen-address "
        "${variable.vyos_settings.mgmt_ip}",
        "set service dns forwarding allow-from 127.0.0.0/8",
        "set service dns forwarding name-server "
        "${variable.vyos_settings.dns.forwarder}",
        "records a ${variable.installer_settings.hostname} address "
        "${variable.installer_settings.ip}",
    )
    for line in required_dns_lines:
        require(line in vyos_config, f"missing VyOS DNS configuration: {line}")
    require(
        "value: ${base64_encode(variable.vyos_config)}" in raw,
        "vyos_config must be transported through config_base64",
    )

    windows = resources.get("Jumphost_VM", {})
    windows_spec = windows.get("properties", {}).get("manifest", {}).get("spec", {})
    sysprep = windows_spec.get("bootstrap", {}).get("sysprep", {}).get("sysprep", {})
    commands = sysprep.get("guiRunOnce", {}).get("commands", [])
    require(len(commands) == 6, "Windows must install six persistent routes")
    require(
        "commands" not in sysprep.get("guiUnattended", {}),
        "route commands must be under guiRunOnce",
    )
    for command in commands:
        require(command.startswith("route /p add "), f"invalid route: {command}")
        require("split(" in command, f"route does not strip CIDR: {command}")
        require(" mask 255.255.255.0 " in command, f"route mask missing: {command}")
    require(
        sysprep.get("guiUnattended", {}).get("autoLogonCount") == 1,
        "one automatic logon is required for guiRunOnce",
    )
    require(
        windows_spec.get("network", {}).get("nameservers")
        == ["${variable.vyos_settings.mgmt_ip}"],
        "Windows must use VyOS for DNS",
    )

    installer_properties = property_map(resources.get("Installer_VM", {}))
    require(
        "vami.DNS.SDDC-Manager" in installer_properties,
        "VCF Installer must use its qualified DNS property",
    )

    # VM Operator prefixes vApp property keys with guestinfo when it exposes
    # them to the guest. The blueprint key must therefore match the OVF image
    # property exactly and must not carry a second guestinfo prefix.
    esxi_ovf_keys = {
        "hostname",
        "password",
        "ipaddress",
        "netmask",
        "gateway",
        "dns",
        "domain",
        "ntp",
        "vlan",
        "ssh",
    }
    for resource_name in ("VM_ESXs", "VM_ESXs_Boot_Only"):
        resource = resources.get(resource_name, {})
        keys = property_keys(resource)
        require(len(keys) == len(set(keys)), f"{resource_name} has duplicate vApp keys")
        require(set(keys) == esxi_ovf_keys, f"{resource_name} vApp keys do not match the ESXi OVF")
        require(
            all(not key.startswith("guestinfo.") for key in keys),
            f"{resource_name} must use unqualified OVF keys",
        )

    vsan_enabled = inputs.get("esx_vsan_disk_enabled", {})
    vsan_size = inputs.get("esx_vsan_disk_size_gib", {})
    require(vsan_enabled.get("type") == "boolean", "vSAN disk enable input must be boolean")
    require(
        vsan_enabled.get("default") is True,
        "vSAN capacity disk must be enabled by default",
    )
    require(vsan_size.get("type") == "integer", "vSAN disk size input must be an integer")
    require(vsan_size.get("minimum") == 1, "vSAN disk size must be at least 1 GiB")

    disk_resource = resources.get("ESXi_VSAN_Disks", {})
    disk_properties = disk_resource.get("properties", {})
    disk_manifest = disk_properties.get("manifest", {})
    disk_spec = disk_manifest.get("spec", {})
    require(
        disk_resource.get("allocatePerInstance") is True,
        "vSAN PVCs must allocate per ESXi",
    )
    require(
        disk_manifest.get("kind") == "PersistentVolumeClaim",
        "vSAN disk PVC resource missing",
    )
    require(disk_spec.get("volumeMode") == "Block", "vSAN PVCs must use raw block volumes")
    require(
        disk_properties.get("count")
        == (
            "${variable.esx_settings.vsan_disk.enabled == true ? "
            "length(variable.esx_settings.servers) : 0}"
        ),
        "vSAN PVC count must follow the ESXi server list and enable flag",
    )

    with_vsan = resources.get("VM_ESXs", {}).get("properties", {})
    without_vsan = resources.get("VM_ESXs_Boot_Only", {}).get("properties", {})
    with_vsan_spec = with_vsan.get("manifest", {}).get("spec", {})
    require(
        with_vsan.get("count")
        == (
            "${variable.esx_settings.vsan_disk.enabled == true ? "
            "length(variable.esx_settings.servers) : 0}"
        ),
        "vSAN-enabled ESXi count must follow the server list and enable flag",
    )
    require(
        without_vsan.get("count")
        == (
            "${variable.esx_settings.vsan_disk.enabled == true ? 0 : "
            "length(variable.esx_settings.servers)}"
        ),
        "boot-only ESXi count must be the inverse of the enable flag",
    )
    require(
        with_vsan.get("manifest", {}).get("apiVersion")
        == "vmoperator.vmware.com/v1alpha5",
        "vSAN-enabled ESXi must use VM Operator v1alpha5",
    )
    require(
        without_vsan.get("manifest", {}).get("apiVersion")
        == "vmoperator.vmware.com/v1alpha5",
        "boot-only ESXi must use VM Operator v1alpha5",
    )
    nvme_controllers = with_vsan_spec.get("hardware", {}).get("nvmeControllers", [])
    require(
        nvme_controllers == [{"busNumber": 0, "sharingMode": "None"}],
        "vSAN-enabled ESXi must define NVMe controller 0",
    )
    volumes = with_vsan_spec.get("volumes", [])
    require(
        len(volumes) == 1,
        "vSAN-enabled ESXi must attach exactly one capacity volume",
    )
    if len(volumes) == 1:
        volume = volumes[0]
        require(
            volume.get("controllerType") == "NVME",
            "vSAN capacity volume must use NVMe",
        )
        require(
            volume.get("controllerBusNumber") == 0,
            "vSAN capacity volume must use bus 0",
        )
        require(volume.get("unitNumber") == 0, "vSAN capacity volume must use unit 0")
        require(
            volume.get("persistentVolumeClaim", {}).get("claimName")
            == (
                "${variable.esx_settings.servers[count.index].name}-"
                "${variable.esx_settings.vsan_disk.claim_suffix}"
            ),
            "vSAN capacity volume must reference its per-host PVC",
        )
    require(
        "volumes" not in without_vsan.get("manifest", {}).get("spec", {}),
        "boot-only ESXi must not attach the optional vSAN volume",
    )

    # VCF Automation's block-template renderer supports a single iterator in
    # these loops. A Terraform-style ``index, value`` declaration silently
    # renders the value as null and also breaks comma insertion.
    require(
        re.search(r"%\{\s*for\s+\w+\s*,\s*\w+\s+in\s+", raw) is None,
        "block templates must not use two-variable for loops",
    )
    deployment_json = (
        blueprint.get("outputs", {}).get("vcf_deployment_json", {}).get("value", "")
    )
    require(
        "%{for host in variable.esx_settings.servers}" in deployment_json,
        "hostSpecs must iterate directly over ESXi hosts",
    )
    require(
        "%{if host.name != variable.esx_settings.servers[0].name},%{endif}"
        in deployment_json,
        "hostSpecs must delimit every host after the first",
    )
    require(
        "%{for address in variable.vcf_settings.automation.ip_pool}"
        in deployment_json,
        "vcfAutomationSpec.ipPool must iterate directly over addresses",
    )
    require(
        "%{if address != variable.vcf_settings.automation.ip_pool[0]},%{endif}"
        in deployment_json,
        "vcfAutomationSpec.ipPool must delimit every address after the first",
    )
    numeric_vlan_expressions = (
        '"vlanId": ${variable.netlayout.mgmt.vlanid}',
        '"vlanId": ${variable.netlayout.vmotion.vlanid}',
        '"vlanId": ${variable.netlayout.vsan.vlanid}',
        '"transportVlanId": ${variable.netlayout.tep.vlanid}',
        '"vlan": ${variable.netlayout.vpc.vlanid}',
    )
    for expression in numeric_vlan_expressions:
        require(
            expression in deployment_json,
            f"VCF Installer VLAN expression must render as an integer: {expression}",
        )
    vcf_settings = variables.get("vcf_settings", {})
    vsp_internal_cidr = vcf_settings.get("vsp", {}).get("internal_cluster_cidr")
    automation_internal_cidr = vcf_settings.get("automation", {}).get(
        "internal_cluster_cidr"
    )
    require(
        isinstance(vsp_internal_cidr, str) and bool(vsp_internal_cidr),
        "VCF Services internal cluster CIDR must be configured",
    )
    require(
        isinstance(automation_internal_cidr, str) and bool(automation_internal_cidr),
        "VCF Automation internal cluster CIDR must be configured",
    )
    require(
        vsp_internal_cidr != automation_internal_cidr,
        "VCF Services and VCF Automation internal cluster CIDRs must differ",
    )
    require(
        '"internalClusterCidrIpv4": '
        '"${variable.vcf_settings.vsp.internal_cluster_cidr}"'
        in deployment_json,
        "vspClusterSpec must use its configured internal cluster CIDR",
    )
    require(
        '"internalClusterCidr": '
        '"${variable.vcf_settings.automation.internal_cluster_cidr}"'
        in deployment_json,
        "vcfAutomationSpec must use its configured internal cluster CIDR",
    )

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Blueprint validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
