from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import validate_vcf_spec  # noqa: E402


def valid_spec() -> dict[str, object]:
    return {
        "version": "9.1.1.0",
        "vcfInstanceName": "vcf",
        "sddcId": "mgmt",
        "workflowType": "VCF",
        "dnsSpec": {
            "subdomain": "example.test",
            "nameservers": ["172.16.0.2"],
        },
        "ntpServers": ["172.16.0.2"],
        "hostSpecs": [
            {
                "hostname": "esx01.example.test",
                "credentials": {"username": "root", "password": "not-a-real-password"},
            },
            {
                "hostname": "esx02.example.test",
                "credentials": {"username": "root", "password": "not-a-real-password"},
            },
        ],
        "networkSpecs": [
            {
                "networkType": "MANAGEMENT",
                "subnet": "172.16.1.0/24",
                "gateway": "172.16.1.1",
                "vlanId": 1601,
            },
            {
                "networkType": "VMOTION",
                "subnet": "172.16.2.0/24",
                "gateway": "172.16.2.1",
                "vlanId": 1602,
                "includeIpAddressRanges": [
                    {"startIpAddress": "172.16.2.2", "endIpAddress": "172.16.2.100"}
                ],
            },
            {
                "networkType": "VSAN",
                "subnet": "172.16.3.0/24",
                "gateway": "172.16.3.1",
                "vlanId": 1603,
                "includeIpAddressRanges": [
                    {"startIpAddress": "172.16.3.2", "endIpAddress": "172.16.3.100"}
                ],
            },
        ],
        "vcenterSpec": {
            "vcenterHostname": "vc01.example.test",
            "rootVcenterPassword": "not-a-real-password",
        },
        "datastoreSpec": {"vsanSpec": {"vsanDedup": False}},
    }


class VcfSpecTests(unittest.TestCase):
    def test_valid_specification(self) -> None:
        self.assertEqual([], validate_vcf_spec.validate_spec(valid_spec()))

    def test_rendered_null_hosts_and_duplicates_are_rejected(self) -> None:
        spec = valid_spec()
        spec["hostSpecs"][0]["hostname"] = "null.example.test"  # type: ignore[index]
        spec["hostSpecs"][1]["hostname"] = "null.example.test"  # type: ignore[index]

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertTrue(any("rendered null" in error for error in errors))
        self.assertTrue(any("unique" in error for error in errors))

    def test_unresolved_template_expressions_are_rejected(self) -> None:
        spec = valid_spec()
        spec["vcenterSpec"]["vcenterHostname"] = "${input.hostname}"  # type: ignore[index]

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertTrue(any("unresolved template" in error for error in errors))

    def test_secret_references_require_an_explicit_structural_mode(self) -> None:
        spec = valid_spec()
        spec["hostSpecs"][0]["credentials"]["password"] = (  # type: ignore[index]
            "((secret:v1:redacted))"
        )

        self.assertTrue(
            any("secret reference" in error for error in validate_vcf_spec.validate_spec(spec))
        )
        self.assertEqual(
            [],
            validate_vcf_spec.validate_spec(spec, allow_secret_references=True),
        )

    def test_ranges_must_be_inside_their_network(self) -> None:
        spec = copy.deepcopy(valid_spec())
        ranges = spec["networkSpecs"][1]["includeIpAddressRanges"]  # type: ignore[index]
        ranges[0]["endIpAddress"] = (
            "172.16.9.100"
        )

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertTrue(any("must be contained" in error for error in errors))

    def test_vlan_ids_must_be_json_integers(self) -> None:
        spec = valid_spec()
        spec["networkSpecs"][0]["vlanId"] = "1601"  # type: ignore[index]

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertTrue(any("JSON integer" in error for error in errors))

    def test_network_and_dvs_mtu_must_be_supported_json_integers(self) -> None:
        spec = valid_spec()
        spec["networkSpecs"][1]["mtu"] = "8000"  # type: ignore[index]
        spec["networkSpecs"][2]["mtu"] = 9001  # type: ignore[index]
        spec["dvsSpecs"] = [{"dvsName": "vds01", "mtu": 9191}]

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertIn("networkSpecs[1].mtu must be a JSON integer", errors)
        self.assertIn("networkSpecs[2].mtu must be between 1500 and 9000", errors)
        self.assertIn("dvsSpecs[0].mtu must be between 1500 and 9190", errors)

    def test_network_mtu_must_fit_its_dvs(self) -> None:
        spec = valid_spec()
        spec["networkSpecs"][0]["mtu"] = 1500  # type: ignore[index]
        spec["networkSpecs"][1]["mtu"] = 9000  # type: ignore[index]
        spec["dvsSpecs"] = [{"dvsName": "vds01", "mtu": 9190, "networks": ["VMOTION"]}]
        self.assertEqual([], validate_vcf_spec.validate_spec(spec))
        spec["dvsSpecs"][0]["mtu"] = 8000
        self.assertIn(
            "dvsSpecs[0].mtu must not be smaller than attached network MTUs",
            validate_vcf_spec.validate_spec(spec),
        )

    def test_hcl_disk_claim_accepts_both_booleans_but_rejects_strings(self) -> None:
        for value in (True, False, "true", 1):
            with self.subTest(value=value):
                spec = valid_spec()
                spec["datastoreSpec"]["vsanSpec"]["esaConfig"] = {  # type: ignore[index]
                    "enabled": True, "skipHclAutoDiskClaim": value,
                }
                errors = validate_vcf_spec.validate_spec(spec)
                if type(value) is bool:
                    self.assertEqual([], errors)
                else:
                    self.assertIn(
                        "datastoreSpec.vsanSpec.esaConfig.skipHclAutoDiskClaim must be a JSON boolean",
                        errors,
                    )

    def test_sddc_manager_hostname_must_be_an_fqdn(self) -> None:
        spec = valid_spec()
        spec["sddcManagerSpec"] = {"hostname": "sddc-manager"}

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertIn("sddcManagerSpec.hostname must be an FQDN", errors)

    def test_nsx_vlan_ids_must_be_json_integers(self) -> None:
        spec = valid_spec()
        spec["nsxtSpec"] = {
            "vipFqdn": "nsx.example.test",
            "nsxtManagers": [{"hostname": "nsx01.example.test"}],
            "transportVlanId": "1604",
            "vpcSpec": {
                "dtgwSpec": {
                    "vlan": "1605",
                    "gatewayCidr": "172.16.5.1/24",
                    "externalIpBlockCidr": "172.16.5.0/24",
                    "privateTgwIpBlockCidr": "172.31.0.0/16",
                }
            },
        }

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertIn("nsxtSpec.transportVlanId must be a JSON integer", errors)
        self.assertIn(
            "nsxtSpec.vpcSpec.dtgwSpec.vlan must be a JSON integer",
            errors,
        )

    def test_malformed_datastore_is_reported_without_crashing(self) -> None:
        spec = valid_spec()
        spec["datastoreSpec"] = "not-an-object"

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertIn("datastoreSpec must be an object", errors)

    def test_automation_pool_must_be_unique_and_in_management_network(self) -> None:
        spec = valid_spec()
        spec["vcfAutomationSpec"] = {
            "hostname": "auto.example.test",
            "platformFqdn": "platform.example.test",
            "adminUserPassword": "not-a-real-password",
            "internalClusterCidr": "198.18.0.0/15",
            "ipPool": ["172.16.1.20", "172.16.1.20", "172.16.9.21"],
        }

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertTrue(any("must be unique" in error for error in errors))
        self.assertTrue(any("MANAGEMENT subnet" in error for error in errors))

    def test_internal_cluster_networks_must_not_overlap(self) -> None:
        spec = valid_spec()
        spec["vspClusterSpec"] = {
            "platformFqdn": "services.example.test",
            "instanceFqdn": "instance.example.test",
            "systemUserPassword": "not-a-real-password",
            "ipv4Pool": {
                "ipRange": {
                    "startIpAddress": "172.16.1.110",
                    "endIpAddress": "172.16.1.125",
                }
            },
            "internalClusterCidrIpv4": "198.18.0.0/15",
        }
        spec["vcfAutomationSpec"] = {
            "hostname": "auto.example.test",
            "platformFqdn": "platform.example.test",
            "adminUserPassword": "not-a-real-password",
            "internalClusterCidr": "198.18.0.0/15",
            "ipPool": ["172.16.1.20", "172.16.1.21"],
        }

        errors = validate_vcf_spec.validate_spec(spec)

        self.assertTrue(any("must not overlap" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
