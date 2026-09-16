# Nested VCF Automation

This repository is a VMware Aria Build Tools `vcfa-all-apps` project for the
**Full Stack VCF** blueprint. It is consumed as the
`components/vcf-automation` submodule of
[nested-vcf-lab](https://github.com/mtornblad/nested-vcf-lab).

The [modular variant](modular/README.md) is a separate Maven package in this
repository. It contains Foundation, ESXi, Installer, and Jumphost blueprints
for the vRO deployment flow. Run its commands from `modular/` or select
`--variant modular` through the umbrella adapter.

## Scope

The blueprint provisions a dedicated VPC and namespace, disconnected VLAN
subnets and trunk bindings, a VyOS router, a Windows jump host, a VCF Installer,
and a data-driven set of nested ESXi hosts. It also generates the VCF Installer
deployment specification from the same network, host, and credential model.

Current runtime behavior includes:

- persistent Windows routes installed during the first automatic logon;
- VyOS using its local forwarding service for its own name resolution;
- authoritative forward and reverse DNS records generated in the VyOS
  `config_base64` payload;
- explicit plaintext request inputs for the disposable lab password and VyOS
  REST key, with no committed defaults;
- dynamic ESXi resource count and VCF `hostSpecs` from one server list;
- an optional, size-controlled NVMe capacity disk per nested ESXi host; and
- source checks for secret defaults, vApp property contracts, networking, and
  block-template syntax.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/main/resources/blueprints/Full Stack VCF/content.yaml` | Full blueprint source and deployment outputs |
| `src/main/resources/blueprints/Full Stack VCF/details.json` | Blueprint metadata |
| `content.yaml` | Build Tools content descriptor |
| `scripts/validate_blueprint.py` | Source contract validator |
| `scripts/validate_vcf_spec.py` | Offline validator for the rendered VCF Installer JSON |
| `tests/test_blueprint_contract.py` | Regression tests |
| `pom.xml` | Build Tools package and push lifecycle |

## Local validation

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
make test
```

## Pull, package, and publish

Build Tools for VMware Aria 4.25.0, Maven 3.9 or newer, and Java 17 are
required.

```bash
make pull PROFILE=lab
make package
make push PROFILE=lab
```

`pull` (also available as the `download` alias) exports the objects named in
`content.yaml` from VCF Automation and overwrites their local source files.
The target refuses to run in a dirty Git checkout by default. Commit or stash
local work first; use `FORCE=true` only when discarding those changes is
intentional. Source validation runs after a successful pull.

The Maven profile contains the VCF Automation endpoint and authentication.
Keep it in the user's Maven `settings.xml`; never add it to this repository.

When this repository is used as a submodule, the umbrella runner supplies the
profile from `configuration/lab.local.json` and permits an explicit override:

```bash
./orchestration/run_automation.py pull
./orchestration/run_automation.py build
./orchestration/run_automation.py upload
./orchestration/run_automation.py upload --profile another-lab
```

## Environment review

Before publishing to another environment, review all structured variables in
the blueprint, especially:

- region, zone, namespace class, storage policy, and quotas;
- VPC, subnet, VLAN, address-pool, DNS, NTP, and end-to-end MTU settings;
- VyOS, Windows, VCF Installer, and nested ESXi image IDs and VM classes; and
- the ESXi server list and optional VCF Automation deployment flag.

The plaintext shared lab password has a 15-character minimum because VCF
Services and VCF Automation impose the strictest minimum among the consumers.
It is intentionally convenient for this disposable lab: the request and
rendered output expose it. Do not reuse this credential model for production.

`fabric_mtu` defaults to 9000 and is applied to the VyOS trunk and all five
tagged interfaces, the vMotion and vSAN network specifications, and the VCF
distributed switch. Override it only with a value verified end to end; the
accepted range is 1600 through 9000.

This is the nested IP MTU. The outer Supervisor/NSX transport must carry those
packets plus its tunnel headers. Changing this input does not configure the
outer vDS, TEP interfaces, Edge nodes, or physical switches. See the
[MTU troubleshooting guide](https://github.com/mtornblad/nested-vcf-lab/blob/main/docs/networking.md#mtu).

## Nested ESXi vSAN capacity

`esx_vsan_disk_enabled` defaults to `true`. When enabled, the blueprint creates
one namespace-scoped raw-block PVC per entry in `esx_settings.servers` and
attaches it to that host through NVMe controller 0. The default size is 100 GiB
and can be changed with `esx_vsan_disk_size_gib` at request time. The PVC uses
the namespace storage policy and is attached as `IndependentPersistent`.

`vsan_allow_hcl_incompatible_disks` exposes **Allow auto claim of HCL
incompatible disks** and defaults to `true` for the nested lab. It is stored
under `vcf_settings.vsan.allow_hcl_incompatible_disks` and renders as the JSON
boolean `datastoreSpec.vsanSpec.esaConfig.skipHclAutoDiskClaim`. Set the input
to `false` to keep HCL-based claiming. This flag controls disk claiming; it does
not add a disk or remove other hardware eligibility checks. The API field is
documented in
[VsanEsaConfig](https://developer.broadcom.com/xapis/vcf-installer-api/latest/data-structures/VsanEsaConfig/).

Set `esx_vsan_disk_enabled` to `false` when testing an ESXi image without vSAN.
The mutually exclusive ESXi resources ensure that the boot-only and
vSAN-capable variants never create the same VM together. The target Supervisor
must expose VM Operator `v1alpha5` and the selected VM class must permit the
requested hardware. See the
[VM Operator workload documentation](https://vm-operator.readthedocs.io/en/docs-stable/concepts/workloads/vm/)
for the PVC volume and controller contract.

The tested nested ESXi image expects these exact VM Operator bootstrap keys:
`guestinfo.hostname`, `guestinfo.password`, `guestinfo.ipaddress`,
`guestinfo.netmask`, `guestinfo.gateway`, `guestinfo.dns`, `guestinfo.domain`,
`guestinfo.ntp`, `guestinfo.vlan`, and `guestinfo.ssh`. Preserve the prefixes;
they are part of the working image contract.

The tested VCF Installer 9.1 image uses the mixed key set `ROOT_PASSWORD`,
`LOCAL_USER_PASSWORD`, `vami.hostname`, `guestinfo.ntp`,
`ip_address_version`, `ip0`, `netmask0`, `gateway`, `domain`, `searchpath`, and
uppercase `DNS`. Do not add `vami.` to the final seven keys and do not append
`.SDDC-Manager` to any key.

The image IDs must identify `ClusterVirtualMachineImage` objects available to
the target namespace. The nested ESXi VM Class must expose hardware-assisted
virtualization.

## Installer, SDDC Manager, and external DNS records

The blueprint provisions the installer outside the nested cluster and requests
a **new** SDDC Manager (`useExistingDeployment: false`). They therefore have
separate identities in the reference lab:

| Appliance | Variable | FQDN | Address |
| --- | --- | --- | --- |
| VCF Installer | `installer_settings` | `mtvcf-installer.dclab.se` | `172.16.1.10` |
| SDDC Manager | `vcf_settings.sddc_manager` | `mtsddcm01.dclab.se` | `172.16.1.207` |

Both identities have forward and reverse records in the VyOS payload. Only
`sddcManagerSpec.hostname` targets the SDDC Manager identity; installer vApp
properties continue to target the installer. Reusing an appliance is a
different workflow involving `useExistingDeployment: true` and trust settings;
do not create a DNS alias that makes a new deployment target the installer.
See the
[SDDC Manager API contract](https://developer.broadcom.com/xapis/vcf-installer-api/latest/data-structures/SddcManagerSpec/).

`vyos_settings.dns.additional_a_records` adds the external VIS entry
`vis-appliance.dclab.se` -> `10.114.10.9`. Each entry specifies `zone`, `name`,
and `address`, so the external name does not change with the nested lab's DNS
prefix. The zone is authoritative in VyOS: include any other required names in
that zone explicitly. Do not add VIS only to `/etc/hosts`, because the DNS
forwarder intentionally ignores that file.

## Validate generated JSON

Save the raw value of `vcf_deployment_json` to a protected, ignored file and
validate it before submitting it to VCF Installer:

```bash
umask 077
VCF_SPEC="$(mktemp)"
${EDITOR:-vi} "$VCF_SPEC"
python3 scripts/validate_vcf_spec.py "$VCF_SPEC"
```

Paste the copied output into the editor and remove the temporary file after
the deployment handoff is complete.

The platform block-template renderer uses one loop iterator. A declaration
such as `index, host` can render the host as null and suppress JSON commas; the
source validator rejects that form. The rendered-spec validator also rejects
invalid JSON, `null.<domain>` host names, duplicate hosts, invalid network
ranges, unresolved template expressions, and unresolved secret references.
It also enforces numeric JSON types for VCF VLAN fields. VCF Services and VCF
Automation use separate configurable internal cluster CIDRs so the two
embedded platform networks do not overlap (`240.0.0.0/15` and
`198.18.0.0/15`, respectively, in the reference lab).

The lab blueprint deliberately emits plaintext password values, so its output
can be validated and handed directly to VCF Installer. Protect the file with
mode `0600`, do not commit it, and remove it after use.

If the inputs are changed back to encrypted values later, VCF Automation may
emit references such as `((secret:v1:...))`. Those references are not passwords
that VCF Installer can consume. The compatibility flag below checks structure
only while such references are still present:

```bash
python3 scripts/validate_vcf_spec.py \
  --allow-secret-references "$VCF_SPEC"
```

Replace the protected references, then run the validator again without the
flag. The authoritative platform validation is the VCF Installer
[`POST /v1/sddcs/validations`](https://developer.broadcom.com/xapis/vcf-installer-api/latest/v1/sddcs/validations/post/)
API or the equivalent import step in its UI.

## Umbrella integration

The existing VCF and certificate custom-resource workflows are versioned in
the [Orchestrator component](https://github.com/mtornblad/nested-vcf-orchestrator/blob/main/docs/custom-resources.md).
Publish its package before these definitions. Both Full Stack and modular
`Custom.vcf` create descriptors include the exported workflow's `sddcSpec`
string input so that the generated JSON reaches Installer. Validate the
cross-repository interfaces from the umbrella root with:

```bash
python3 components/vro-typescript/scripts/validate_native.py \
  --automation components/vcf-automation
```

After committing and pushing a component change, advance the parent gitlink:

```bash
cd ../..
git add components/vcf-automation
git diff --cached --submodule=log
git commit -m "chore: update VCF Automation blueprint submodule"
```

Architecture, image acquisition, deployment, security, and troubleshooting
guides live in the
[umbrella documentation](https://github.com/mtornblad/nested-vcf-lab/tree/main/docs).
