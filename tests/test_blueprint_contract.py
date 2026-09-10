from __future__ import annotations

import copy
import re
import sys
import unittest
from unittest import mock
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import validate_blueprint  # noqa: E402


class BlueprintContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.blueprint, cls.descriptor, cls.details, cls.raw = (
            validate_blueprint.load_sources()
        )
        cls.resources = cls.blueprint["resources"]

    def test_complete_validator(self) -> None:
        self.assertEqual([], validate_blueprint.validate())

    def test_build_tools_descriptor_owns_only_the_blueprint(self) -> None:
        self.assertEqual(["Full Stack VCF"], self.descriptor["blueprint"])
        self.assertEqual([], self.descriptor["workflow"])
        self.assertEqual([], self.descriptor["subscription"])

    def test_makefile_defines_a_guarded_vcfa_pull(self) -> None:
        makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("vcfa-all-apps:pull -P$(PROFILE)", makefile)
        self.assertIn("git status --porcelain", makefile)
        self.assertIn('"$(FORCE)" != "true"', makefile)
        self.assertIn("download: pull", makefile)

    def test_vyos_resolves_through_its_own_forwarder(self) -> None:
        properties = validate_blueprint.property_map(self.resources["VyOS_Machine"])
        self.assertEqual(
            "${to_string(variable.vyos_settings.dns.local_resolver)}",
            properties["dns"]["value"],
        )
        config = self.blueprint["variables"]["vyos_config"]
        self.assertIn("listen-address ${variable.vyos_settings.dns.local_resolver}", config)
        self.assertIn("allow-from 127.0.0.0/8", config)
        self.assertIn("set service dns forwarding ignore-hosts-file", config)

    def test_installer_record_is_inside_the_base64_configuration(self) -> None:
        config = self.blueprint["variables"]["vyos_config"]
        self.assertIn(
            "records a ${variable.installer_settings.hostname} address "
            "${variable.installer_settings.ip}",
            config,
        )
        self.assertIn(
            "records ptr 10 target ${variable.installer_settings.fqdn}",
            config,
        )
        self.assertNotIn("${input.dns_prefix}sddcm", config)
        self.assertIn("${base64_encode(variable.vyos_config)}", self.raw)

    def test_installer_vapp_keys_match_the_tested_image_contract(self) -> None:
        expected = {
            "ROOT_PASSWORD",
            "LOCAL_USER_PASSWORD",
            "vami.hostname",
            "guestinfo.ntp",
            "ip_address_version",
            "ip0",
            "netmask0",
            "gateway",
            "domain",
            "searchpath",
            "DNS",
        }
        properties = validate_blueprint.property_map(self.resources["Installer_VM"])

        self.assertEqual(expected, set(properties))
        self.assertFalse(any("SDDC-Manager" in key for key in properties))
        for key in ("ROOT_PASSWORD", "LOCAL_USER_PASSWORD"):
            self.assertEqual(
                {
                    "name": "${resource.Bootstrap_Secrets.manifest.metadata.name}",
                    "key": "lab-password",
                },
                properties[key]["from"],
            )
        self.assertEqual(
            "${variable.installer_settings.fqdn}",
            properties["vami.hostname"]["value"],
        )
        self.assertEqual("IPv4", properties["ip_address_version"]["value"])
        self.assertEqual(
            "${to_string(variable.installer_settings.ip)}",
            properties["ip0"]["value"],
        )
        self.assertEqual("255.255.255.0", properties["netmask0"]["value"])
        self.assertEqual(
            "${to_string(variable.netlayout.mgmt.defaultgw)}",
            properties["gateway"]["value"],
        )
        for key in ("domain", "searchpath"):
            self.assertEqual("${to_string(input.domain_name)}", properties[key]["value"])
        self.assertEqual(
            "${to_string(variable.vyos_settings.mgmt_ip)}",
            properties["DNS"]["value"],
        )
        self.assertEqual(
            "${to_string(variable.vyos_settings.fqdn)}",
            properties["guestinfo.ntp"]["value"],
        )

    def test_windows_routes_are_persistent_first_logon_commands(self) -> None:
        spec = self.resources["Jumphost_VM"]["properties"]["manifest"]["spec"]
        sysprep = spec["bootstrap"]["sysprep"]["sysprep"]
        commands = sysprep["guiRunOnce"]["commands"]
        self.assertEqual(6, len(commands))
        self.assertNotIn("commands", sysprep["guiUnattended"])
        for command in commands:
            self.assertTrue(command.startswith("route /p add "))
            self.assertIn("split(", command)

    def test_credentials_are_request_inputs_without_defaults(self) -> None:
        for name in ("lab_password", "vyos_rest_api_key"):
            definition = self.blueprint["inputs"][name]
            self.assertFalse(definition["encrypted"])
            self.assertNotIn("default", definition)
        self.assertEqual(15, self.blueprint["inputs"]["lab_password"]["minLength"])

    def test_esxi_vapp_keys_match_the_ovf_image_contract(self) -> None:
        expected = {
            "guestinfo.hostname",
            "guestinfo.password",
            "guestinfo.ipaddress",
            "guestinfo.netmask",
            "guestinfo.gateway",
            "guestinfo.dns",
            "guestinfo.domain",
            "guestinfo.ntp",
            "guestinfo.vlan",
            "guestinfo.ssh",
        }
        for resource_name in ("VM_ESXs", "VM_ESXs_Boot_Only"):
            keys = validate_blueprint.property_keys(self.resources[resource_name])
            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual(expected, set(keys))
            self.assertTrue(all(key.startswith("guestinfo.") for key in keys))
            properties = validate_blueprint.property_map(self.resources[resource_name])
            self.assertEqual(
                "${to_string(variable.vyos_settings.fqdn)}",
                properties["guestinfo.ntp"]["value"],
            )

    def test_canonical_dns_and_ntp_identities_are_consistent(self) -> None:
        variables = self.blueprint["variables"]
        self.assertEqual(
            "${input.dns_prefix}vyos01.${input.domain_name}",
            variables["vyos_settings"]["fqdn"],
        )
        self.assertEqual(
            "${input.dns_prefix}vcf-installer.${input.domain_name}",
            variables["installer_settings"]["fqdn"],
        )
        template = self.blueprint["outputs"]["vcf_deployment_json"]["value"]
        self.assertRegex(
            template,
            r'"ntpServers":\s*\[\s*"\$\{variable\.vyos_settings\.fqdn\}"\s*\]',
        )
        self.assertIn(
            '"hostname": "${variable.vcf_settings.sddc_manager.fqdn}"',
            template,
        )

    def test_new_sddc_manager_must_not_reuse_installer_identity(self) -> None:
        changed = copy.deepcopy(self.blueprint)
        settings = changed["variables"]
        settings["vcf_settings"]["sddc_manager"]["fqdn"] = settings["installer_settings"]["fqdn"]
        with mock.patch.object(
            validate_blueprint, "load_sources",
            return_value=(changed, self.descriptor, self.details, self.raw),
        ):
            self.assertIn(
                "new SDDC Manager deployment must have its own FQDN and IP",
                validate_blueprint.validate(),
            )

    def test_vis_record_is_rendered_into_the_dns_payload(self) -> None:
        records = self.blueprint["variables"]["vyos_settings"]["dns"]["additional_a_records"]
        record = next(item for item in records if item["name"] == "vis-appliance")
        config = self.blueprint["variables"]["vyos_config"]
        line = next(line for line in config.splitlines() if "${record.zone}" in line)
        for key, value in record.items():
            line = line.replace("${record." + key + "}", value)
        self.assertEqual(
            "set service dns forwarding authoritative-domain dclab.se "
            "records a vis-appliance address 10.114.10.9",
            line.strip(),
        )

    def test_fabric_mtu_is_applied_end_to_end(self) -> None:
        definition = self.blueprint["inputs"]["fabric_mtu"]
        self.assertEqual("integer", definition["type"])
        self.assertEqual(9000, definition["default"])
        self.assertEqual(1600, definition["minimum"])
        self.assertEqual(9000, definition["maximum"])

        variables = self.blueprint["variables"]
        self.assertEqual("${input.fabric_mtu}", variables["netlayout"]["trunk"]["mtu"])
        self.assertEqual(
            6,
            variables["vyos_config"].count("mtu ${variable.netlayout.trunk.mtu}"),
        )
        template = self.blueprint["outputs"]["vcf_deployment_json"]["value"]
        self.assertEqual(
            3,
            template.count('"mtu": ${variable.netlayout.trunk.mtu}'),
        )

    def test_optional_vsan_capacity_disk_uses_per_host_nvme_block_storage(self) -> None:
        inputs = self.blueprint["inputs"]
        self.assertTrue(inputs["esx_vsan_disk_enabled"]["default"])
        self.assertEqual(1, inputs["esx_vsan_disk_size_gib"]["minimum"])

        disk_resource = self.resources["ESXi_VSAN_Disks"]
        self.assertTrue(disk_resource["allocatePerInstance"])
        self.assertEqual(
            "${variable.esx_settings.vsan_disk.enabled == true ? "
            "length(variable.esx_settings.servers) : 0}",
            disk_resource["properties"]["count"],
        )
        disk_spec = disk_resource["properties"]["manifest"]["spec"]
        self.assertEqual("Block", disk_spec["volumeMode"])

        esxi = self.resources["VM_ESXs"]["properties"]["manifest"]
        self.assertEqual("vmoperator.vmware.com/v1alpha5", esxi["apiVersion"])
        self.assertEqual(
            [{"busNumber": 0, "sharingMode": "None"}],
            esxi["spec"]["hardware"]["nvmeControllers"],
        )
        volume = esxi["spec"]["volumes"][0]
        self.assertEqual("NVME", volume["controllerType"])
        self.assertEqual(0, volume["controllerBusNumber"])
        self.assertEqual(0, volume["unitNumber"])

        boot_only = self.resources["VM_ESXs_Boot_Only"]["properties"]
        self.assertEqual(
            "${variable.esx_settings.vsan_disk.enabled == true ? 0 : "
            "length(variable.esx_settings.servers)}",
            boot_only["count"],
        )
        self.assertNotIn("volumes", boot_only["manifest"]["spec"])

    def test_generated_json_uses_single_iterator_template_loops(self) -> None:
        self.assertIsNone(
            re.search(r"%\{\s*for\s+\w+\s*,\s*\w+\s+in\s+", self.raw)
        )

        template = self.blueprint["outputs"]["vcf_deployment_json"]["value"]
        self.assertIn(
            "%{for host in variable.esx_settings.servers}",
            template,
        )
        self.assertIn(
            "%{if host.name != variable.esx_settings.servers[0].name},%{endif}",
            template,
        )
        self.assertIn(
            "%{for address in variable.vcf_settings.automation.ip_pool}",
            template,
        )
        self.assertIn(
            "%{if address != variable.vcf_settings.automation.ip_pool[0]},%{endif}",
            template,
        )

    def test_vcf_vlan_ids_render_as_json_numbers(self) -> None:
        template = self.blueprint["outputs"]["vcf_deployment_json"]["value"]
        for expression in (
            '"vlanId": ${variable.netlayout.mgmt.vlanid}',
            '"vlanId": ${variable.netlayout.vmotion.vlanid}',
            '"vlanId": ${variable.netlayout.vsan.vlanid}',
            '"transportVlanId": ${variable.netlayout.tep.vlanid}',
            '"vlan": ${variable.netlayout.vpc.vlanid}',
        ):
            self.assertIn(expression, template)
            self.assertNotIn(expression.replace(": $", ': "$') + '"', template)

    def test_internal_cluster_networks_are_distinct_and_configurable(self) -> None:
        settings = self.blueprint["variables"]["vcf_settings"]
        vsp_cidr = settings["vsp"]["internal_cluster_cidr"]
        automation_cidr = settings["automation"]["internal_cluster_cidr"]
        self.assertNotEqual(vsp_cidr, automation_cidr)

        template = self.blueprint["outputs"]["vcf_deployment_json"]["value"]
        self.assertIn(
            '"internalClusterCidrIpv4": '
            '"${variable.vcf_settings.vsp.internal_cluster_cidr}"',
            template,
        )
        self.assertIn(
            '"internalClusterCidr": '
            '"${variable.vcf_settings.automation.internal_cluster_cidr}"',
            template,
        )


if __name__ == "__main__":
    unittest.main()
