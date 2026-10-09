<div align="center">

# VMAFx

**Perceptual video quality assessment that gives the same score on every device.**

[![Latest release](https://img.shields.io/github/v/release/VMAFx/vmafx?include_prereleases&sort=semver&label=latest%20release)](https://github.com/VMAFx/vmafx/releases)
[![Tests](https://img.shields.io/github/actions/workflow/status/VMAFx/vmafx/tests-and-quality-gates.yml?branch=master&event=push&label=tests)](https://github.com/VMAFx/vmafx/actions/workflows/tests-and-quality-gates.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/VMAFx/vmafx/badge)](https://scorecard.dev/viewer/?uri=github.com/VMAFx/vmafx)
[![OpenSSF Best Practices](https://img.shields.io/cii/level/14549?label=OpenSSF%20best%20practices)](https://www.bestpractices.dev/projects/14549)
[![Discussions](https://img.shields.io/github/discussions/VMAFx/vmafx?label=discussions)](https://github.com/VMAFx/vmafx/discussions)
[![Last commit](https://img.shields.io/github/last-commit/VMAFx/vmafx/master?label=last%20commit)](https://github.com/VMAFx/vmafx/commits/master)

**[📖 Docs](https://vmafx.github.io/vmafx/)** · **[🗺️ Roadmap](https://vmafx.github.io/vmafx/roadmap/)** · **[🚀 First score](https://vmafx.github.io/vmafx/getting-started/first-score/)** · **[💬 Discussions](https://github.com/VMAFx/vmafx/discussions)**

</div>

VMAFx is a fork of [Netflix/vmaf](https://github.com/Netflix/vmaf). Netflix's own reference tests run on every change, so the CPU scores stay the reference scores. On top of that, VMAFx scores on GPUs from every major vendor and holds each GPU version of a metric to the CPU's result **bit for bit**, with the evidence published.

## Repositories

| Repository | What it is |
| --- | --- |
| [**vmafx**](https://github.com/VMAFx/vmafx) | The scoring library, CLI, FFmpeg integration, server and tooling: CUDA, SYCL, HIP and Metal backends, SIMD paths, containers and Helm. |
| [**pelorus**](https://github.com/VMAFx/pelorus) | Encoder-side companion: a GPU pre-encode pipeline and the interop VMAFx reads (side data, QP reports, encoder parameters). |
| [**netflix-vmaf-contributions**](https://github.com/VMAFx/netflix-vmaf-contributions) | Our fork of Netflix/vmaf, used to contribute fixes back upstream. |

## What we hold ourselves to

- **Correct before fast.** The reference scores don't move. A faster path that changes a score is a bug, not a trade-off.
- **Every vendor, same answer.** NVIDIA, Intel, AMD and Apple GPUs, and the CPU's SIMD paths, all return the reference result, and published tables show where that is proven.
- **Reproducible and verifiable.** Signed releases, build provenance, SBOMs, and scores that can carry a record of exactly how they were produced.
- **Upstream-friendly.** We port Netflix's changes and keep the classic `libvmaf` API working for existing users.

## Where things stand

The release badge above, the [roadmap](https://vmafx.github.io/vmafx/roadmap/) and the [milestones](https://github.com/VMAFx/vmafx/milestones) are always current. This page doesn't repeat them, so it can't go stale.

## Get involved

- 📟 **Have a GPU or Mac we haven't tested?** Run the [tester kit](https://vmafx.github.io/vmafx/usage/tester-image/); see the [hardware we need](https://vmafx.github.io/vmafx/usage/hardware-we-need/).
- 🙋 **Questions and ideas:** [Discussions](https://github.com/VMAFx/vmafx/discussions).
- 🧑‍💻 **First contribution:** [good first issues](https://github.com/VMAFx/vmafx/issues?q=is%3Aopen+label%3A%22good+first+issue%22) and [help wanted](https://github.com/VMAFx/vmafx/issues?q=is%3Aopen+label%3A%22help+wanted%22); start with [CONTRIBUTING](https://github.com/VMAFx/vmafx/blob/master/CONTRIBUTING.md).
- 🔒 **Security:** report privately through [security advisories](https://github.com/VMAFx/vmafx/security/advisories/new).

## Licences

Code written for VMAFx is licensed under **EUPL-1.2**. Code inherited from Netflix keeps its **BSD-2-Clause-Patent** licence. Each file's SPDX line is authoritative. Pelorus is **EUPL-1.2** since v0.3.0; files it adds to FFmpeg are LGPL-2.1-or-later, and releases up to v0.2.2 stay BSD-2-Clause-Patent. See the vmafx [LICENSE](https://github.com/VMAFx/vmafx/blob/master/LICENSE) and [NOTICE](https://github.com/VMAFx/vmafx/blob/master/NOTICE), and the Pelorus [LICENSE](https://github.com/VMAFx/pelorus/blob/master/LICENSE).
