import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_modular import check_references, load, validate


class ModularContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blueprints = {
            role: load(ROOT / "src/main/resources/blueprints" / ("Nested VCF Modular - " + title) / "content.yaml")
            for role, title in [("foundation", "Foundation"), ("esxi", "ESXi"), ("installer", "Installer"), ("jumphost", "Jumphost")]
        }
        cls.original = load(ROOT.parent / "src/main/resources/blueprints/Full Stack VCF/content.yaml")

    def test_all_sources_validate(self):
        self.assertEqual([], validate())

    def test_cross_deployment_reference_is_detected(self):
        blueprint = copy.deepcopy(self.blueprints["esxi"])
        blueprint["resources"]["VM_ESXs"]["dependsOn"].append("VyOS_Machine")
        self.assertTrue(any("VyOS_Machine" in error for error in check_references(blueprint)))

    def test_foundation_is_the_only_namespace_and_vpc_owner(self):
        for role, blueprint in self.blueprints.items():
            namespace = blueprint["resources"]["Namespace"]["properties"]
            self.assertEqual(role != "foundation", namespace["existing"])
            self.assertEqual(role == "foundation", "VPC_Main" in blueprint["resources"])
            if role != "foundation":
                self.assertEqual("${input.namespace_name}", namespace["name"])
                self.assertNotIn("generateName", namespace)

    def test_each_stage_has_its_own_secret(self):
        names = [b["variables"]["bootstrap_secret_name"] for b in self.blueprints.values()]
        self.assertEqual(4, len(set(names)))
        for role, blueprint in self.blueprints.items():
            data = blueprint["resources"]["Bootstrap_Secrets"]["properties"]["manifest"]["stringData"]
            self.assertEqual(role == "foundation", "vyos-rest-api-key" in data)

    def test_tested_vapp_keys_are_preserved_verbatim(self):
        for role, names in [("foundation", ["VyOS_Machine"]), ("esxi", ["VM_ESXs", "VM_ESXs_Boot_Only"]), ("installer", ["Installer_VM"])]:
            for name in names:
                def keys(resource):
                    return [item["key"] for item in resource["properties"]["manifest"]["spec"]["bootstrap"]["vAppConfig"]["properties"]]
                self.assertEqual(keys(self.original["resources"][name]), keys(self.blueprints[role]["resources"][name]))

    def test_esxi_count_and_nvme_mapping_follow_current_code(self):
        resources = self.blueprints["esxi"]["resources"]
        for name in ["ESXi_VSAN_Disks", "VM_ESXs", "VM_ESXs_Boot_Only"]:
            self.assertIn("length(variable.esx_settings.servers)", resources[name]["properties"]["count"])
        spec = resources["VM_ESXs"]["properties"]["manifest"]["spec"]
        self.assertEqual(self.original["resources"]["VM_ESXs"]["properties"]["manifest"]["spec"]["hardware"], spec["hardware"])
        self.assertEqual(1, spec["volumes"][0]["controllerBusNumber"])

    def test_planned_installer_and_jump_addresses_drive_reverse_dns(self):
        script = self.blueprints["foundation"]["variables"]["vyos_config"]
        self.assertIn("records ptr ${split(variable.installer_settings.ip, '.')[3]}", script)
        self.assertIn("records ptr ${split(variable.jumphost_settings.ip, '.')[3]}", script)
        self.assertIn("%{for host in variable.esx_settings.servers}", script)
        self.assertIn("ignore-hosts-file", script)

    def test_windows_routing_is_preserved(self):
        def commands(blueprint):
            return blueprint["resources"]["Jumphost_VM"]["properties"]["manifest"]["spec"]["bootstrap"]["sysprep"]["sysprep"]["guiRunOnce"]["commands"]
        self.assertEqual(commands(self.original), commands(self.blueprints["jumphost"]))

    def test_installer_consumes_serialized_json_and_bringup_is_optional(self):
        blueprint = self.blueprints["installer"]
        self.assertFalse(blueprint["inputs"]["run_vcf_installation"]["default"])
        self.assertEqual("${input.vcf_spec_json}", blueprint["resources"]["Custom_vcf_1"]["properties"]["sddcSpec"])
        self.assertEqual("${input.run_vcf_installation ? 1 : 0}", blueprint["resources"]["Custom_vcf_1"]["properties"]["count"])


if __name__ == "__main__":
    unittest.main()
