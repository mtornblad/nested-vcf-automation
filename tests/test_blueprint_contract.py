from __future__ import annotations

import sys
import unittest
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

    def test_vyos_resolves_through_its_own_forwarder(self) -> None:
        properties = validate_blueprint.property_map(self.resources["VyOS_Machine"])
        self.assertEqual(
            "${to_string(variable.vyos_settings.dns.local_resolver)}",
            properties["dns"]["value"],
        )
        config = self.blueprint["variables"]["vyos_config"]
        self.assertIn("listen-address ${variable.vyos_settings.dns.local_resolver}", config)
        self.assertIn("allow-from 127.0.0.0/8", config)

    def test_installer_record_is_inside_the_base64_configuration(self) -> None:
        config = self.blueprint["variables"]["vyos_config"]
        self.assertIn(
            "records a ${variable.installer_settings.hostname} address "
            "${variable.installer_settings.ip}",
            config,
        )
        self.assertIn("${base64_encode(variable.vyos_config)}", self.raw)

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
            self.assertTrue(definition["encrypted"])
            self.assertNotIn("default", definition)


if __name__ == "__main__":
    unittest.main()
