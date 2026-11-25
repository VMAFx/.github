# ADR-0001: Absolute-claim check on the organisation profile

- **Status**: Accepted
- **Date**: 2026-11-22
- **Authors**: Lusoris

## Context

PR 7 (profile README presentation standard) drew two review findings of one class:
claims without an evidence link (fixed in 2ffd06e), and a linked tagline,
"same score on every device", that overstates its evidence. The linked parity gate
uses zero tolerance for exact twins. The default absolute tolerance for other
cells is `5e-5`. The [tolerance table](https://github.com/VMAFx/vmafx/blob/master/docs/development/cross-backend-gate.md#tolerance-contract)
sets `5e-3` for the non-exact `ciede` twin and for `ssimulacra2`.
The CI lane covers one backend and one feature.

## Decision

[Vale](https://vale.sh) (maintained prose linter) runs the local style `VMAFx`
with one rule, `VMAFx.AbsoluteClaim` (`.vale/styles/VMAFx/AbsoluteClaim.yml`),
on `profile/*.md`. `scripts/check-claims.sh` lints the profile, requires
`tests/claims/qualified.md` to pass, and requires one report for each of the
eight expected phrases in `tests/claims/planted.md`. A positive control plants a
claim in a scratch copy of `profile/README.md` and requires a report on that
line to verify the profile selector. `lefthook.yml` lists the script as a
commit-time command for changes to the profile, the style, the
fixtures, or the script. `.github/workflows/claims.yml` runs the same script
inside the `jdkato/vale` image pinned by tag and digest, which Renovate updates.
A phrase whose universal form is proven goes under the rule's `exceptions` with
its evidence path in a comment.

## Consequences

Catches the absolute phrasings in the token list, with case and hyphen variants.
Does not judge whether a linked page supports a qualified claim, and does not
detect an unlinked claim without an absolute phrase, or a synonym outside the
list; those stay review work.

## Alternatives considered

- **Hand-written checker script** (rejected: Vale is the maintained tool for phrase
  rules).
- **Per-claim inline `vale off` comments** (rejected: a silent per-line opt-out).
- **No check** (rejected: the same class reached review twice on one PR).
