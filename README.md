# Nested VCF Automation

This repository is a Build Tools for VMware Aria `vcfa-all-apps` project for
the **Full Stack VCF** blueprint. It is intended to be consumed as the
`components/vcf-automation` submodule of `nested-vcf-lab`.

## Functional changes in this revision

- Windows persistent routes run from Sysprep `guiRunOnce` during the first
  automatic Administrator logon. Route destinations are plain network
  addresses and use the Windows syntax `route /p add`.
- VyOS receives `127.0.0.1` through its `dns` vApp property. Its forwarding
  service listens on both loopback and the management address, while the
  `dns_forwarder` input remains the upstream resolver.
- The VCF Installer A record is part of `variable.vyos_config`, which is sent
  through the `config_base64` vApp property.
- Passwords and the VyOS REST key are encrypted request inputs rather than
  values committed to Git.

## Local validation

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
make test
```

## Build and publish

Build Tools for VMware Aria 4.25.0, Maven 3.9+, and Java 17 are required.

```bash
make package
make push PROFILE=lab
```

The Maven profile contains the VCF Automation endpoint and authentication. Keep
that profile in the user's Maven `settings.xml`; never add it to this repository.

## Create the component repository

```bash
cd ~/nested-vcf-automation
git init -b main
git add .
git commit -m "feat: add full-stack VCF Automation blueprint"
git remote add origin git@github.com:mtornblad/nested-vcf-automation.git
git push -u origin main
```

## Add the submodule

```bash
cd ~/nested-vcf-lab
git submodule add -b main \
  git@github.com:mtornblad/nested-vcf-automation.git \
  components/vcf-automation
git add .gitmodules components/vcf-automation
git diff --cached --submodule=log
git commit -m "chore: add VCF Automation blueprint submodule"
git push origin main
```

The current VM image IDs, region, namespace segment, storage policy, and zone
remain aligned with the supplied lab blueprint so this revision can be tested
without changing its placement contract.
