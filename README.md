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
- dynamic ESXi resource count and VCF `hostSpecs` from one server list; and
- source checks for secret defaults, vApp property contracts, networking, and
  block-template syntax.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/main/resources/blueprints/Full Stack VCF/content.yaml` | Full blueprint source and deployment outputs |
| `src/main/resources/blueprints/Full Stack VCF/details.json` | Blueprint metadata |
| `content.yaml` | Build Tools content descriptor |
| `scripts/validate_blueprint.py` | Source contract validator |
| `tests/test_blueprint_contract.py` | Regression tests |
| `pom.xml` | Build Tools package and push lifecycle |

## Local validation

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
make test
```

## Package and publish

Build Tools for VMware Aria 4.25.0, Maven 3.9 or newer, and Java 17 are
required.

```bash
make package
make push PROFILE=lab
```

The Maven profile contains the VCF Automation endpoint and authentication.
Keep it in the user's Maven `settings.xml`; never add it to this repository.

## Environment review

Before publishing to another environment, review all structured variables in
the blueprint, especially:

- region, zone, namespace class, storage policy, and quotas;
- VPC, subnet, VLAN, address-pool, DNS, and NTP settings;
- VyOS, Windows, VCF Installer, and nested ESXi image IDs and VM classes; and
- the ESXi server list and optional VCF Automation deployment flag.

The image IDs must identify `ClusterVirtualMachineImage` objects available to
the target namespace. The nested ESXi VM Class must expose hardware-assisted
virtualization.

## Validate generated JSON

`vcf_deployment_json` contains resolved credentials. Save it only to a
protected, ignored file and validate it before submitting it to VCF Installer:

```bash
umask 077
VCF_SPEC="$(mktemp)"
${EDITOR:-vi} "$VCF_SPEC"
jq empty "$VCF_SPEC"
jq -r '.hostSpecs[].hostname' "$VCF_SPEC"
jq -r '.vcfAutomationSpec.ipPool[]?' "$VCF_SPEC"
```

Paste the copied output into the editor and remove the temporary file after
the deployment handoff is complete.

The platform block-template renderer uses one loop iterator. A declaration
such as `index, host` can render the host as null and suppress JSON commas; the
validator rejects that form.

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
