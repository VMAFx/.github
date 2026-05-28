# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in VMAFx, please report it privately via [GitHub Security Advisories](https://github.com/VMAFx/vmafx/security/advisories/new) on the affected repository.

**Do not** open a public issue for security reports.

We'll acknowledge receipt within 7 days and aim to provide an initial assessment within 14 days.

## Supported Versions

VMAFx follows the `vmafx-N.M.P-lusoris.X` version scheme. Security fixes target the latest `master` tag. Older versions are not supported.

## Scope

In scope:

- The main `vmafx` repository (library + tooling + Helm chart + production Dockerfile)
- The Helm chart and k8s manifests
- Published container images (`ghcr.io/vmafx/vmafx*`)

Out of scope:

- Bugs in upstream Netflix/vmaf code that we mirror (report those at https://github.com/Netflix/vmaf)
- Bugs in third-party dependencies (report those upstream)
