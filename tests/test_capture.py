import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_capture import CAPTURE, load, validate, validate_blueprint


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.blueprint = load(CAPTURE)

    def test_complete_package_and_capture(self):
        self.assertEqual([], validate())

    def test_arbitrary_host_counts(self):
        original = self.blueprint['inputs']['esxi_captures']['default'][0]
        for count in (1,2,7):
            with self.subTest(count=count):
                hosts = [dict(copy.deepcopy(original), name=f'esx{i}', image=f'vmi-test{i}') for i in range(count)]
                self.blueprint['inputs']['esxi_captures']['default'] = hosts
                self.assertEqual([], validate_blueprint(self.blueprint))

    def test_duplicate_host_identity_rejected(self):
        hosts = self.blueprint['inputs']['esxi_captures']['default']
        hosts[1] = copy.deepcopy(hosts[0])
        self.assertTrue(validate_blueprint(self.blueprint))

    def test_guest_reconfiguration_rejected(self):
        self.blueprint['resources']['Installer_VM']['properties']['manifest']['spec']['bootstrap'] = {'vAppConfig':{}}
        self.assertTrue(any('customization' in error for error in validate_blueprint(self.blueprint)))

    def test_installation_custom_resource_rejected(self):
        self.blueprint['resources']['Bringup'] = {'type':'Custom.vcf','properties':{}}
        self.assertTrue(any('custom resources' in error for error in validate_blueprint(self.blueprint)))

    def test_old_pvc_not_replayed(self):
        self.blueprint['resources']['Disk'] = {'type':'CCI.Supervisor.Resource','properties':{'manifest':{'kind':'PersistentVolumeClaim'}}}
        self.assertTrue(any('inherit image disks' in error for error in validate_blueprint(self.blueprint)))

    def test_vm_readiness_wait_before_group_rejected(self):
        self.blueprint['resources']['VM_ESXs']['properties']['wait'] = {'conditions':[{'type':'Ready','status':'True'}]}
        self.assertTrue(any('deadlock' in error for error in validate_blueprint(self.blueprint)))


if __name__ == '__main__':
    unittest.main()
