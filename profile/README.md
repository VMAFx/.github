# VMAFx

**Modernized perceptual video quality assessment.**

A cloud-native fork-descended-from Netflix VMAF, rebuilt for distributed video pipelines: GPU-vendor-agnostic backends, tiny-AI models for one-shot scoring, MCP server for AI-agent integrations, Kubernetes-native deployment with a 3-vendor GPU device-plugin matrix.

## What's here

- **[vmafx](https://github.com/VMAFx/vmafx)** — the main repo: core C++23 library (`libvmaf` C ABI being retired), Go production tooling, Rust pilots, Python ML training, Helm chart, dev container.

## Core principles

- **Cloud-native first.** Production artifacts are Docker images + Helm chart. Native `.so` / `.deb` / `.rpm` publishing is out of scope — Docker is the platform.
- **Multi-vendor GPU.** First-class support for NVIDIA (CUDA), AMD (HIP / ROCm), Intel (SYCL / Arc).
- **Correctness above speed.** Bit-exactness against the Netflix CPU reference is the non-negotiable safety net.
- **Multi-language, multi-purpose.** Go for production tooling (controller / node / Operator / CLI / MCP), Rust for pilot integrations + bindings, Python for ML training, C++23 internals for the scoring core.

## License

Dual-licensed for fork-added code: **BSD-3-Clause-Plus-Patent OR MIT**. Netflix-inherited code stays under BSD-3-Clause-Plus-Patent. See the [LICENSE](https://github.com/VMAFx/vmafx/blob/master/LICENSE) and [LICENSE-MIT](https://github.com/VMAFx/vmafx/blob/master/LICENSE-MIT) on the main repo.

## Status

Active development. The fork is undergoing an aggressive modernization sweep (Phase 4) toward a distributed controller / node / operator architecture. See [ADR-0686](https://github.com/VMAFx/vmafx/blob/master/docs/adr/0686-vmafx-rebrand-aggressive-modernization.md) (rebrand umbrella) and [ADR-0709](https://github.com/VMAFx/vmafx/blob/master/docs/adr/0709-vmafx-phase4b-distributed-platform.md) (Phase 4b distributed platform).
