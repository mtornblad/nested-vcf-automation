# Full Stack VCF - Capture

This blueprint deploys the configured images from the supplied capture into a
new namespace and VPC. It follows Full Stack's infrastructure layout: external
IP, DNAT for SSH/RDP/Installer HTTPS, uplink, disconnected trunk, VLAN subnets
and trunk bindings. Guests start with the configuration stored in their images.

The ordinary Maven project now includes Full Stack, the four modular blueprints
and Capture. There is no separate `modular/` project. Blueprint names and IDs
remain stable; Capture has its own ID.

## Captured images

The source filename, checksum and image inventory are recorded in
[capture-source.json](../contracts/capture-source.json).

| Guest | Default captured image |
| --- | --- |
| mtvyos01-41685da4f2 | `vmi-c8b12519f897bad54` |
| mtesx01 | `vmi-c6ae4fa03dc1d6bcf` |
| mtesx02 | `vmi-35a76cfef06e32f15` |
| mtesx03 | `vmi-77bfd8a6ecc8a5990` |
| mtesx04 | `vmi-b891f5819d5031403` |
| mtvcf-installer | `vmi-33774f3a24d58a384` |
| mtjump01 | `vmi-fc88b8589e14087c4` |

These IDs must refer to complete configured images available to the **new**
namespace. An image visible only in the source namespace will not suffice;
publish it to a Content Library associated with the destination and update the
image inputs if its ID changes. The blueprint does not create image captures.

## Inputs and configuration

| Setting | Location | Meaning |
| --- | --- | --- |
| Lab name | `inputs.lab_name` | Prefix for newly generated namespace/VPC names |
| Region, zone, namespace class, segment | Placement inputs | Destination Supervisor placement |
| Storage policy | `inputs.storage_policy` | Destination storage class |
| VyOS, Installer, Jumphost images/classes | Role inputs | Captured images and destination VM classes |
| ESXi class | `inputs.esxi_class` | Class with nested virtualization enabled |
| Captured ESXi list | `inputs.esxi_captures` | One object with name, image and interfaces per host |
| Namespace quota/class bindings | `variables.namespace_settings` | Capacity limits and allowed VM classes |
| VPC/VLAN layout | `variables.vpc_settings` and `variables.netlayout` | Must match the topology baked into the captures |
| Captured role networks | Role variables | Addresses, network names and MAC associations from the capture |

If selecting a new VM class, include it in `namespace_settings.vm_classes`.
The captured list controls both VM count and VM-group membership. More or fewer
hosts can be supplied; every entry must refer to the matching captured host.
This changes which outer VMs are deployed. It does **not** expand or shrink a
VCF/vSAN cluster already configured inside the images.

`lab_name` does not rename the guests. Their original hostnames, static IPs,
credentials and nested appliance configuration are retained. The source has
VyOS at `172.16.0.2`, Installer at `172.16.1.10`, and Jumphost at `172.16.0.4`.
The source network attachments, including the Installer's `/32` address and
captured MAC addresses, are preserved. Adjust these only together with the
corresponding guest capture. Keep each restored lab in its own isolated VPC.

## Guest and disk lifecycle

Guest customization is explicitly disabled: Linux guests keep
`linuxPrep.customizeAtNextPowerOn: false`; Windows keeps the equivalent Sysprep
flag. There are no vApp properties, generated passwords, bootstrap scripts,
certificate-import resources, `Custom.vcf` resources or generated installation
JSON in this blueprint.

The VM group orders VyOS first, the selected ESXi hosts second, and Installer
and Jumphost third. The blueprint waits on the group's Ready condition after
declaring all VMs. It does not wait for each guest to power on before creating
the group, which would create a dependency cycle. This is power ordering, not
a health check of DNS, vSAN or nested VCF services.

The exported PVCs contain `dataSourceRef` references back to their VMs. These
are registrations of image disks, not snapshot-clone sources. Capture omits
those PVC objects, old PVC names, explicit volume mappings and source BIOS
UUIDs. VM Operator deploys the image disks and registers their PVCs in the new
namespace. See the upstream [VM disk lifecycle documentation](https://github.com/vmware-tanzu/vm-operator/blob/main/docs/concepts/workloads/vm.md#image-disk-conversion).

The ESXi images must include the intended vSAN capacity disks and their data.
The source manifest alone cannot prove that the image export contains them;
its capacity disks were `IndependentPersistent`. Verify the actual image
disks and capture consistency before relying on a restored nested cluster.
This blueprint deliberately does not add blank capacity disks to a captured
cluster. Use [Full Stack](../README.md) for a fresh installation with new disks.

## Build and test

From the component root, with the normal Build Tools prerequisites installed:

```bash
python3 -m pip install -r requirements-dev.txt
make test
make push PROFILE=lab
```

Or from the umbrella:

```bash
./orchestration/run_automation.py test
./orchestration/run_automation.py upload
```

Upload and pull handle all six blueprints and the shared custom-resource
definitions. Existing `--variant modular` commands are compatibility aliases
for this combined package, not a content filter. Publish the vRO package first
if the shared custom-resource workflow IDs are not already installed.

Release **Full Stack VCF - Capture** and request it directly from the catalog.
Check image visibility, restored disk contents, MAC-to-NIC mapping, DNS,
routes, NTP and nested cluster health on the first deployment. Offline tests
validate source contracts; VCFA expression rendering and restore behavior need
the target platform. No existing deployment is changed by editing this source.

[Component overview](../README.md) · [Modular workflow blueprints](modular.md)
