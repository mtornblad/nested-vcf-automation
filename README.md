# Nested VCF Automation

This repository is a VMware Aria Build Tools `vcfa-all-apps` project for the
**Full Stack VCF** blueprint. It is consumed as the
`components/vcf-automation` submodule of
[nested-vcf-lab](https://github.com/mtornblad/nested-vcf-lab).

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
- encrypted request inputs for the shared lab password and VyOS REST key;
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
- VPC, subnet, VLAN, address-pool, DNS, and NTP settings;
- VyOS, Windows, VCF Installer, and nested ESXi image IDs and VM classes; and
- the ESXi server list and optional VCF Automation deployment flag.

The encrypted shared lab password has a 15-character minimum because VCF
Services and VCF Automation impose the strictest minimum among the consumers.

## Nested ESXi vSAN capacity

`esx_vsan_disk_enabled` defaults to `true`. When enabled, the blueprint creates
one namespace-scoped raw-block PVC per entry in `esx_settings.servers` and
attaches it to that host through NVMe controller 0. The default size is 100 GiB
and can be changed with `esx_vsan_disk_size_gib` at request time. The PVC uses
the namespace storage policy and is attached as `IndependentPersistent`.

Set `esx_vsan_disk_enabled` to `false` when testing an ESXi image without vSAN.
The mutually exclusive ESXi resources ensure that the boot-only and
vSAN-capable variants never create the same VM together. The target Supervisor
must expose VM Operator `v1alpha5` and the selected VM class must permit the
requested hardware. See the
[VM Operator workload documentation](https://vm-operator.readthedocs.io/en/docs-stable/concepts/workloads/vm/)
for the PVC volume and controller contract.

The ESXi image advertises unqualified OVF keys such as `hostname`, `password`,
and `ipaddress`. Those exact keys belong in `spec.bootstrap.vAppConfig`;
VM Operator exposes them inside the guest with the `guestinfo.` prefix.

The tested VCF Installer 9.1 image contract uses `vami.ip0`,
`vami.netmask0`, `vami.gateway`, `vami.domain`, `vami.searchpath`, and
uppercase `vami.DNS`. Do not append `.SDDC-Manager` to these VM Operator
bootstrap keys. Passwords use `ROOT_PASSWORD` and `LOCAL_USER_PASSWORD`, while
hostname and NTP use `vami.hostname` and `guestinfo.ntp` respectively.

The image IDs must identify `ClusterVirtualMachineImage` objects available to
the target namespace. The nested ESXi VM Class must expose hardware-assisted
virtualization.

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

Encrypted VCF Automation outputs can display values such as
`((secret:v1:...))`. That is expected UI protection, but it is not a password
that VCF Installer can consume. To check only structure before materializing
credentials, use:

```bash
python3 scripts/validate_vcf_spec.py \
  --allow-secret-references "$VCF_SPEC"
```

Replace the protected references in a local `0600` copy, then run the validator
again without the flag. Do not weaken the blueprint inputs to expose plaintext
credentials in the deployment UI. The authoritative platform validation is
the VCF Installer
[`POST /v1/sddcs/validations`](https://developer.broadcom.com/xapis/vcf-installer-api/latest/v1/sddcs/validations/post/)
API or the equivalent import step in its UI.

## Umbrella integration

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
