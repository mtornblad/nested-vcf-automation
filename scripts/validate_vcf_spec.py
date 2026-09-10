#!/usr/bin/env python3
"""Validate a rendered VCF Installer deployment specification offline."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator


WORKFLOW_TYPES = {"VCF", "VCF_COMPLETE", "VCF_EXTEND", "VVF", "VCF_BOOTSTRAP"}
REQUIRED_NETWORK_TYPES = {"MANAGEMENT", "VMOTION", "VSAN"}
SECRET_REFERENCE_PREFIX = "((secret:"
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
NETWORK_TEAMING_POLICIES = {
    "loadbalance_ip",
    "loadbalance_srcmac",
    "loadbalance_srcid",
    "failover_explicit",
    "loadbalance_loadbased",
}
VSP_INTERNAL_CLUSTER_CIDRS = {
    "198.18.0.0/15",
    "240.0.0.0/15",
    "250.0.0.0/15",
}


def walk_strings(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_strings(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_strings(child, path + (str(index),))
    elif isinstance(value, str):
        yield path, value


def is_fqdn(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 253:
        return False
    labels = value.rstrip(".").split(".")
    return len(labels) >= 2 and all(DNS_LABEL.fullmatch(label) for label in labels)


def parse_network(value: object, path: str, errors: list[str]) -> ipaddress.IPv4Network | None:
    try:
        network = ipaddress.ip_network(str(value), strict=True)
    except ValueError:
        errors.append(f"{path} must be a canonical IP network")
        return None
    if not isinstance(network, ipaddress.IPv4Network):
        errors.append(f"{path} must be an IPv4 network")
        return None
    return network


def parse_address(value: object, path: str, errors: list[str]) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        errors.append(f"{path} must be an IP address")
        return None
    if not isinstance(address, ipaddress.IPv4Address):
        errors.append(f"{path} must be an IPv4 address")
        return None
    return address


def parse_interface(
    value: object,
    path: str,
    errors: list[str],
) -> ipaddress.IPv4Interface | None:
    try:
        interface = ipaddress.ip_interface(str(value))
    except ValueError:
        errors.append(f"{path} must be an IP address with a prefix length")
        return None
    if not isinstance(interface, ipaddress.IPv4Interface):
        errors.append(f"{path} must be an IPv4 address with a prefix length")
        return None
    return interface


def validate_vlan_id(value: object, path: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path} must be a JSON integer")
    elif not 0 <= value <= 4094:
        errors.append(f"{path} must be between 0 and 4094")


def validate_mtu(
    value: object, path: str, errors: list[str], *, maximum: int = 9000
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path} must be a JSON integer")
    elif not 1500 <= value <= maximum:
        errors.append(f"{path} must be between 1500 and {maximum}")


def validate_password_minimum(
    value: object,
    path: str,
    minimum: int,
    errors: list[str],
    *,
    allow_secret_references: bool,
) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path} is required")
    elif value.startswith(SECRET_REFERENCE_PREFIX) and allow_secret_references:
        return
    elif len(value) < minimum:
        errors.append(f"{path} must contain at least {minimum} characters")


def validate_range(
    value: object,
    path: str,
    network: ipaddress.IPv4Network | None,
    errors: list[str],
    *,
    start_key: str,
    end_key: str,
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    start = parse_address(value.get(start_key), f"{path}.{start_key}", errors)
    end = parse_address(value.get(end_key), f"{path}.{end_key}", errors)
    if start is None or end is None:
        return
    if start > end:
        errors.append(f"{path} starts after it ends")
    if network is not None and (start not in network or end not in network):
        errors.append(f"{path} must be contained by {network}")


def validate_spec(
    spec: object,
    *,
    allow_secret_references: bool = False,
) -> list[str]:
    """Return operator-facing validation errors without exposing credentials."""

    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["the document root must be a JSON object"]

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(isinstance(spec.get("version"), str) and bool(spec["version"]), "version is required")
    require(spec.get("workflowType") in WORKFLOW_TYPES, "workflowType is not supported")

    sddc_id = spec.get("sddcId")
    require(
        isinstance(sddc_id, str)
        and 3 <= len(sddc_id) <= 20
        and re.fullmatch(r"[A-Za-z0-9-]+", sddc_id) is not None,
        "sddcId must be 3-20 letters, digits, or hyphens",
    )
    instance_name = spec.get("vcfInstanceName")
    require(
        isinstance(instance_name, str)
        and bool(instance_name.strip())
        and len(instance_name) <= 300,
        "vcfInstanceName must contain 1-300 characters",
    )

    dns_spec = spec.get("dnsSpec")
    if not isinstance(dns_spec, dict):
        errors.append("dnsSpec must be an object")
    else:
        require(is_fqdn(dns_spec.get("subdomain")), "dnsSpec.subdomain must be a DNS domain")
        nameservers = dns_spec.get("nameservers")
        if not isinstance(nameservers, list) or not nameservers:
            errors.append("dnsSpec.nameservers must be a non-empty array")
        else:
            for index, nameserver in enumerate(nameservers):
                parse_address(nameserver, f"dnsSpec.nameservers[{index}]", errors)

    ntp_servers = spec.get("ntpServers")
    require(
        isinstance(ntp_servers, list)
        and bool(ntp_servers)
        and all(isinstance(item, str) and bool(item.strip()) for item in ntp_servers),
        "ntpServers must be a non-empty string array",
    )

    hosts = spec.get("hostSpecs")
    if not isinstance(hosts, list) or not hosts:
        errors.append("hostSpecs must be a non-empty array")
    else:
        hostnames: list[str] = []
        for index, host in enumerate(hosts):
            path = f"hostSpecs[{index}]"
            if not isinstance(host, dict):
                errors.append(f"{path} must be an object")
                continue
            hostname = host.get("hostname")
            if not is_fqdn(hostname):
                errors.append(f"{path}.hostname must be an FQDN")
            else:
                hostnames.append(str(hostname).lower())
                if str(hostname).split(".", 1)[0].lower() == "null":
                    errors.append(f"{path}.hostname contains a rendered null host name")
            credentials = host.get("credentials")
            if not isinstance(credentials, dict):
                errors.append(f"{path}.credentials must be an object")
            else:
                require(
                    isinstance(credentials.get("username"), str)
                    and bool(credentials["username"].strip()),
                    f"{path}.credentials.username is required",
                )
                require(
                    isinstance(credentials.get("password"), str)
                    and bool(credentials["password"]),
                    f"{path}.credentials.password is required",
                )
        require(len(hostnames) == len(set(hostnames)), "hostSpecs hostnames must be unique")

    networks = spec.get("networkSpecs")
    management_network: ipaddress.IPv4Network | None = None
    if not isinstance(networks, list) or not networks:
        errors.append("networkSpecs must be a non-empty array")
    else:
        seen_network_types: set[str] = set()
        for index, network_spec in enumerate(networks):
            path = f"networkSpecs[{index}]"
            if not isinstance(network_spec, dict):
                errors.append(f"{path} must be an object")
                continue
            network_type = network_spec.get("networkType")
            require(isinstance(network_type, str), f"{path}.networkType is required")
            if isinstance(network_type, str):
                seen_network_types.add(network_type)
            network = parse_network(network_spec.get("subnet"), f"{path}.subnet", errors)
            gateway = parse_address(network_spec.get("gateway"), f"{path}.gateway", errors)
            if network is not None and gateway is not None and gateway not in network:
                errors.append(f"{path}.gateway must be contained by {network}")
            if network_type == "MANAGEMENT":
                management_network = network
            validate_vlan_id(network_spec.get("vlanId"), f"{path}.vlanId", errors)
            if "mtu" in network_spec:
                validate_mtu(network_spec.get("mtu"), f"{path}.mtu", errors)
            teaming_policy = network_spec.get("teamingPolicy")
            if teaming_policy is not None:
                require(
                    teaming_policy in NETWORK_TEAMING_POLICIES,
                    f"{path}.teamingPolicy is not supported",
                )
            ranges = network_spec.get("includeIpAddressRanges", [])
            if not isinstance(ranges, list):
                errors.append(f"{path}.includeIpAddressRanges must be an array")
            else:
                for range_index, ip_range in enumerate(ranges):
                    validate_range(
                        ip_range,
                        f"{path}.includeIpAddressRanges[{range_index}]",
                        network,
                        errors,
                        start_key="startIpAddress",
                        end_key="endIpAddress",
                    )
        require(
            REQUIRED_NETWORK_TYPES.issubset(seen_network_types),
            "networkSpecs must include MANAGEMENT, VMOTION, and VSAN",
        )
        require(
            len(seen_network_types) == len(networks),
            "networkSpecs network types must be unique",
        )

    vcenter = spec.get("vcenterSpec")
    require(isinstance(vcenter, dict), "vcenterSpec must be an object")
    if isinstance(vcenter, dict):
        require(
            is_fqdn(vcenter.get("vcenterHostname")),
            "vcenterSpec.vcenterHostname must be an FQDN",
        )

    sddc_manager = spec.get("sddcManagerSpec")
    if sddc_manager is not None:
        if not isinstance(sddc_manager, dict):
            errors.append("sddcManagerSpec must be an object")
        else:
            require(
                is_fqdn(sddc_manager.get("hostname")),
                "sddcManagerSpec.hostname must be an FQDN",
            )

    dvs_specs = spec.get("dvsSpecs")
    if dvs_specs is not None:
        if not isinstance(dvs_specs, list) or not dvs_specs:
            errors.append("dvsSpecs must be a non-empty array")
        else:
            for index, dvs_spec in enumerate(dvs_specs):
                path = f"dvsSpecs[{index}]"
                if not isinstance(dvs_spec, dict):
                    errors.append(f"{path} must be an object")
                    continue
                if "mtu" in dvs_spec:
                    validate_mtu(dvs_spec.get("mtu"), f"{path}.mtu", errors, maximum=9190)
                    dvs_mtu = dvs_spec.get("mtu")
                    attached = dvs_spec.get("networks", [])
                    if type(dvs_mtu) is int and isinstance(attached, list) and isinstance(networks, list):
                        for network in networks:
                            if not isinstance(network, dict):
                                continue
                            network_mtu = network.get("mtu")
                            if network.get("networkType") in attached and type(network_mtu) is int:
                                require(
                                    network_mtu <= dvs_mtu,
                                    f"{path}.mtu must not be smaller than attached network MTUs",
                                )

    datastore = spec.get("datastoreSpec")
    if not isinstance(datastore, dict):
        errors.append("datastoreSpec must be an object")
    else:
        require(
            isinstance(datastore.get("vsanSpec"), dict),
            "datastoreSpec.vsanSpec is required",
        )
        vsan = datastore.get("vsanSpec")
        if isinstance(vsan, dict) and "esaConfig" in vsan:
            esa = vsan.get("esaConfig")
            if not isinstance(esa, dict):
                errors.append("datastoreSpec.vsanSpec.esaConfig must be an object")
            else:
                for field in ("enabled", "skipHclAutoDiskClaim"):
                    if field in esa:
                        require(
                            type(esa[field]) is bool,
                            f"datastoreSpec.vsanSpec.esaConfig.{field} must be a JSON boolean",
                        )

    vsp_internal_network: ipaddress.IPv4Network | None = None
    vsp = spec.get("vspClusterSpec")
    if vsp is not None:
        if not isinstance(vsp, dict):
            errors.append("vspClusterSpec must be an object")
        else:
            for field in ("platformFqdn", "instanceFqdn"):
                require(
                    is_fqdn(vsp.get(field)),
                    f"vspClusterSpec.{field} must be an FQDN",
                )
            fleet_fqdn = vsp.get("fleetFqdn")
            if fleet_fqdn is not None:
                require(
                    is_fqdn(fleet_fqdn),
                    "vspClusterSpec.fleetFqdn must be an FQDN",
                )
            validate_password_minimum(
                vsp.get("systemUserPassword"),
                "vspClusterSpec.systemUserPassword",
                15,
                errors,
                allow_secret_references=allow_secret_references,
            )

            ipv4_pool = vsp.get("ipv4Pool")
            if not isinstance(ipv4_pool, dict):
                errors.append("vspClusterSpec.ipv4Pool must be an object")
            elif "ipRange" in ipv4_pool:
                validate_range(
                    ipv4_pool.get("ipRange"),
                    "vspClusterSpec.ipv4Pool.ipRange",
                    management_network,
                    errors,
                    start_key="startIpAddress",
                    end_key="endIpAddress",
                )
            elif "cidr" in ipv4_pool:
                pool_network = parse_network(
                    ipv4_pool.get("cidr"),
                    "vspClusterSpec.ipv4Pool.cidr",
                    errors,
                )
                if (
                    pool_network is not None
                    and management_network is not None
                    and not pool_network.subnet_of(management_network)
                ):
                    errors.append(
                        "vspClusterSpec.ipv4Pool.cidr must be inside the MANAGEMENT subnet"
                    )
            elif "addresses" in ipv4_pool:
                addresses = ipv4_pool.get("addresses")
                if not isinstance(addresses, list) or not addresses:
                    errors.append(
                        "vspClusterSpec.ipv4Pool.addresses must be a non-empty array"
                    )
                else:
                    parsed_addresses = [
                        parse_address(
                            address,
                            f"vspClusterSpec.ipv4Pool.addresses[{index}]",
                            errors,
                        )
                        for index, address in enumerate(addresses)
                    ]
                    if management_network is not None and any(
                        address is not None and address not in management_network
                        for address in parsed_addresses
                    ):
                        errors.append(
                            "vspClusterSpec.ipv4Pool.addresses must be inside the MANAGEMENT subnet"
                        )
            else:
                errors.append(
                    "vspClusterSpec.ipv4Pool must define ipRange, cidr, or addresses"
                )

            internal_cidr = vsp.get("internalClusterCidrIpv4")
            vsp_internal_network = parse_network(
                internal_cidr,
                "vspClusterSpec.internalClusterCidrIpv4",
                errors,
            )
            if internal_cidr not in VSP_INTERNAL_CLUSTER_CIDRS:
                errors.append(
                    "vspClusterSpec.internalClusterCidrIpv4 is not a supported VCF Services CIDR"
                )

    nsxt = spec.get("nsxtSpec")
    if nsxt is not None:
        if not isinstance(nsxt, dict):
            errors.append("nsxtSpec must be an object")
        else:
            require(is_fqdn(nsxt.get("vipFqdn")), "nsxtSpec.vipFqdn must be an FQDN")
            if "transportVlanId" in nsxt:
                validate_vlan_id(
                    nsxt.get("transportVlanId"),
                    "nsxtSpec.transportVlanId",
                    errors,
                )
            managers = nsxt.get("nsxtManagers")
            if not isinstance(managers, list) or not managers:
                errors.append("nsxtSpec.nsxtManagers must be a non-empty array")
            else:
                for index, manager in enumerate(managers):
                    require(
                        isinstance(manager, dict)
                        and is_fqdn(manager.get("hostname")),
                        f"nsxtSpec.nsxtManagers[{index}].hostname must be an FQDN",
                    )

            pool = nsxt.get("ipAddressPoolSpec")
            if pool is not None:
                if not isinstance(pool, dict):
                    errors.append("nsxtSpec.ipAddressPoolSpec must be an object")
                else:
                    subnets = pool.get("subnets")
                    if not isinstance(subnets, list) or not subnets:
                        errors.append(
                            "nsxtSpec.ipAddressPoolSpec.subnets must be a non-empty array"
                        )
                    else:
                        for index, subnet in enumerate(subnets):
                            path = f"nsxtSpec.ipAddressPoolSpec.subnets[{index}]"
                            if not isinstance(subnet, dict):
                                errors.append(f"{path} must be an object")
                                continue
                            network = parse_network(
                                subnet.get("cidr"), f"{path}.cidr", errors
                            )
                            gateway = parse_address(
                                subnet.get("gateway"), f"{path}.gateway", errors
                            )
                            if (
                                network is not None
                                and gateway is not None
                                and gateway not in network
                            ):
                                errors.append(f"{path}.gateway must be contained by {network}")
                            ranges = subnet.get("ipAddressPoolRanges")
                            if not isinstance(ranges, list) or not ranges:
                                errors.append(
                                    f"{path}.ipAddressPoolRanges must be a non-empty array"
                                )
                            else:
                                for range_index, ip_range in enumerate(ranges):
                                    validate_range(
                                        ip_range,
                                        f"{path}.ipAddressPoolRanges[{range_index}]",
                                        network,
                                        errors,
                                        start_key="start",
                                        end_key="end",
                                    )

            vpc = nsxt.get("vpcSpec")
            if isinstance(vpc, dict) and "dtgwSpec" in vpc:
                dtgw = vpc.get("dtgwSpec")
                if not isinstance(dtgw, dict):
                    errors.append("nsxtSpec.vpcSpec.dtgwSpec must be an object")
                else:
                    validate_vlan_id(
                        dtgw.get("vlan"),
                        "nsxtSpec.vpcSpec.dtgwSpec.vlan",
                        errors,
                    )
                    gateway = parse_interface(
                        dtgw.get("gatewayCidr"),
                        "nsxtSpec.vpcSpec.dtgwSpec.gatewayCidr",
                        errors,
                    )
                    external_network = parse_network(
                        dtgw.get("externalIpBlockCidr"),
                        "nsxtSpec.vpcSpec.dtgwSpec.externalIpBlockCidr",
                        errors,
                    )
                    if (
                        gateway is not None
                        and external_network is not None
                        and gateway.ip not in external_network
                    ):
                        errors.append(
                            "nsxtSpec.vpcSpec.dtgwSpec.gatewayCidr must be inside "
                            "externalIpBlockCidr"
                        )
                    private_cidr = dtgw.get("privateTgwIpBlockCidr")
                    if private_cidr is not None:
                        parse_network(
                            private_cidr,
                            "nsxtSpec.vpcSpec.dtgwSpec.privateTgwIpBlockCidr",
                            errors,
                        )

    automation = spec.get("vcfAutomationSpec")
    if automation is not None:
        if not isinstance(automation, dict):
            errors.append("vcfAutomationSpec must be an object")
        else:
            require(
                is_fqdn(automation.get("hostname")),
                "vcfAutomationSpec.hostname must be an FQDN",
            )
            require(
                is_fqdn(automation.get("platformFqdn")),
                "vcfAutomationSpec.platformFqdn must be an FQDN",
            )
            validate_password_minimum(
                automation.get("adminUserPassword"),
                "vcfAutomationSpec.adminUserPassword",
                15,
                errors,
                allow_secret_references=allow_secret_references,
            )
            automation_internal_network = parse_network(
                automation.get("internalClusterCidr"),
                "vcfAutomationSpec.internalClusterCidr",
                errors,
            )
            if (
                vsp_internal_network is not None
                and automation_internal_network is not None
                and vsp_internal_network.overlaps(automation_internal_network)
            ):
                errors.append(
                    "VCF Services and VCF Automation internal cluster CIDRs must not overlap"
                )
            pool = automation.get("ipPool")
            if not isinstance(pool, list) or not pool:
                errors.append("vcfAutomationSpec.ipPool must be a non-empty array")
            else:
                addresses: list[ipaddress.IPv4Address] = []
                for index, value in enumerate(pool):
                    address = parse_address(
                        value, f"vcfAutomationSpec.ipPool[{index}]", errors
                    )
                    if address is not None:
                        addresses.append(address)
                require(
                    len(addresses) == len(set(addresses)),
                    "vcfAutomationSpec.ipPool must be unique",
                )
                if management_network is not None and any(
                    address not in management_network for address in addresses
                ):
                    errors.append("vcfAutomationSpec.ipPool must be inside the MANAGEMENT subnet")

    for path, value in walk_strings(spec):
        rendered_path = ".".join(path)
        if "${" in value or "%{" in value:
            errors.append(f"{rendered_path} contains an unresolved template expression")
        if path and "password" in path[-1].lower():
            if not value:
                errors.append(f"{rendered_path} must not be empty")
            elif value.startswith(SECRET_REFERENCE_PREFIX) and not allow_secret_references:
                errors.append(
                    f"{rendered_path} contains an unresolved VCF Automation secret reference"
                )

    return errors


def load_spec(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"file does not exist: {path}") from error
    except OSError as error:
        raise ValueError(f"unable to read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="Raw JSON copied from vcf_deployment_json")
    parser.add_argument(
        "--allow-secret-references",
        action="store_true",
        help="Validate structure before encrypted output references have been materialized",
    )
    args = parser.parse_args()

    try:
        spec = load_spec(args.spec.expanduser().resolve())
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    errors = validate_spec(spec, allow_secret_references=args.allow_secret_references)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    secret_references = sum(
        value.startswith(SECRET_REFERENCE_PREFIX) for _, value in walk_strings(spec)
    )
    if secret_references:
        print(
            "WARNING: structure is valid, but encrypted secret references must be replaced "
            "before submission to VCF Installer.",
            file=sys.stderr,
        )
    host_count = len(spec.get("hostSpecs", [])) if isinstance(spec, dict) else 0
    network_count = len(spec.get("networkSpecs", [])) if isinstance(spec, dict) else 0
    print(
        f"VCF deployment specification is valid ({host_count} host(s), "
        f"{network_count} network(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
