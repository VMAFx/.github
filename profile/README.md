<!-- markdownlint-disable MD013 MD033 MD036 MD041 -->
<div align="center">

  <img src="https://raw.githubusercontent.com/VMAFx/vmafx/master/docs/assets/vmafx-readme-banner.svg" alt="VMAFx — perceptual video quality assessment, GPU-accelerated and SIMD-tuned" height="120" />

  <!-- README-STANDARD badge block: one group, fixed order (docs/README-STANDARD.md) -->
  <!-- 1 release/version -->
  [![Release](https://img.shields.io/badge/Release-Releases-3b82f6?style=for-the-badge&labelColor=111a35)](https://github.com/VMAFx/vmafx/releases)
  <!-- 2 CI/build -->
  [![Tests](https://github.com/VMAFx/vmafx/actions/workflows/tests-and-quality-gates.yml/badge.svg?branch=master&event=push)](https://github.com/VMAFx/vmafx/actions/workflows/tests-and-quality-gates.yml)
  <!-- 3 security/scorecard -->
  [![OpenSSF Scorecard](https://img.shields.io/badge/OpenSSF-Scorecard-06b6d4?style=for-the-badge&labelColor=111a35)](https://scorecard.dev/viewer/?uri=github.com/VMAFx/vmafx)
  [![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14549/badge)](https://www.bestpractices.dev/projects/14549)
  [![CodeRabbit](https://img.shields.io/badge/Reviews-CodeRabbit-8b5cf6?style=for-the-badge&logo=coderabbit&logoColor=white&labelColor=111a35)](https://coderabbit.ai)
  <!-- 4 standards -->
  [![HISS-21](https://img.shields.io/badge/Standards-HISS--21-06b6d4?style=for-the-badge&logo=nasa&labelColor=111a35)](https://github.com/VMAFx/vmafx/blob/master/AGENTS.md)
  [![Power of 10](https://img.shields.io/badge/NASA_JPL-Power_of_10-3b82f6?style=for-the-badge&logo=nasa&labelColor=111a35)](https://github.com/VMAFx/vmafx/blob/master/docs/principles.md)
  [![Conventional Commits](https://img.shields.io/badge/Commits-Conventional-8b5cf6?style=for-the-badge&logo=conventionalcommits&logoColor=white&labelColor=111a35)](https://github.com/VMAFx/vmafx/blob/master/CONTRIBUTING.md)
  <!-- 5 licence -->
  [![License](https://img.shields.io/badge/License-EUPL--1.2_·_BSD--2--Clause--Patent-3b82f6?style=for-the-badge&labelColor=111a35)](https://github.com/VMAFx/vmafx/blob/master/LICENSE)
  <!-- 6 support -->
  [![Discussions](https://img.shields.io/badge/Support-Discussions-8b5cf6?style=for-the-badge&logo=github&labelColor=111a35)](https://github.com/VMAFx/vmafx/discussions)

  **Perceptual video quality assessment that gives the [same score on every device](https://github.com/VMAFx/vmafx/blob/master/docs/development/cross-backend-gate.md).**

  _A fork of [Netflix/vmaf](https://github.com/Netflix/vmaf) that [keeps the reference scores](https://github.com/VMAFx/vmafx/blob/master/docs/principles.md#31-netflix-golden-data-gate)_

</div>

VMAFx is a fork of [Netflix/vmaf](https://github.com/Netflix/vmaf). Netflix's own reference tests run on every change, so the CPU scores stay the reference scores. On top of that, VMAFx scores on GPUs from every major vendor and holds each GPU version of a metric to the CPU's result **bit for bit**, with the evidence published.

**[📖 Documentation](https://vmafx.github.io/vmafx/)** · **[🗺️ Roadmap](https://vmafx.github.io/vmafx/roadmap/)** · **[🚀 First score](https://vmafx.github.io/vmafx/getting-started/first-score/)** · **[💬 Discussions](https://github.com/VMAFx/vmafx/discussions)**

---

## Why VMAFx

- **Correct before fast.** The reference scores don't move. A faster path that changes a score is a bug, not a trade-off.
- **Every vendor, same answer.** NVIDIA, Intel, AMD and Apple GPUs, and the CPU's SIMD paths, all return the reference result, and published tables show where that is proven.
- **Reproducible and verifiable.** Signed releases, build provenance, SBOMs, and scores that can carry a record of exactly how they were produced.
- **Upstream-friendly.** We port Netflix's changes and keep the classic `libvmaf` API working for existing users.

## At a glance

| Repository | What it is |
| --- | --- |
| [**vmafx**](https://github.com/VMAFx/vmafx) | The scoring library, CLI, FFmpeg integration, server and tooling: CUDA, SYCL, HIP and Metal backends, SIMD paths, containers and Helm. |
| [**pelorus**](https://github.com/VMAFx/pelorus) | Encoder-side companion: a GPU pre-encode pipeline and the interop VMAFx reads (side data, QP reports, encoder parameters). |
| [**netflix-vmaf-contributions**](https://github.com/VMAFx/netflix-vmaf-contributions) | Our fork of Netflix/vmaf, used to contribute fixes back upstream. |

## Contribute

- 📟 **Have a GPU or Mac we haven't tested?** Run the [tester kit](https://vmafx.github.io/vmafx/usage/tester-image/); see the [hardware we need](https://vmafx.github.io/vmafx/usage/hardware-we-need/).
- 🙋 **Questions and ideas:** [Discussions](https://github.com/VMAFx/vmafx/discussions).
- 🧑‍💻 **First contribution:** [good first issues](https://github.com/VMAFx/vmafx/issues?q=is%3Aopen+label%3A%22good+first+issue%22) and [help wanted](https://github.com/VMAFx/vmafx/issues?q=is%3Aopen+label%3A%22help+wanted%22); start with [CONTRIBUTING](https://github.com/VMAFx/vmafx/blob/master/CONTRIBUTING.md).
- 🔒 **Security:** report privately through [security advisories](https://github.com/VMAFx/vmafx/security/advisories/new).

## Roadmap and releases

The release badge above, the [roadmap](https://vmafx.github.io/vmafx/roadmap/) and the [milestones](https://github.com/VMAFx/vmafx/milestones) are always current. This page doesn't repeat them, so it can't go stale.

## Upstream and licences

Code written for VMAFx is licensed under **EUPL-1.2**. Code inherited from Netflix keeps its **BSD-2-Clause-Patent** licence. Each file's SPDX line is authoritative. Pelorus is **EUPL-1.2** since v0.3.0; files it adds to FFmpeg are LGPL-2.1-or-later, and releases up to v0.2.2 stay BSD-2-Clause-Patent. See the vmafx [LICENSE](https://github.com/VMAFx/vmafx/blob/master/LICENSE) and [NOTICE](https://github.com/VMAFx/vmafx/blob/master/NOTICE), and the Pelorus [LICENSE](https://github.com/VMAFx/pelorus/blob/master/LICENSE).
