#!/bin/sh
# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2
#
# Claim check (docs/adr/0001-absolute-claim-check.md). The organisation profile
# must carry no absolute claim, the qualified fixture must pass, and the
# VMAFx.AbsoluteClaim rule must still report every planted claim. Exit 0 when
# all three hold; exit 1 on a finding, a missing vale, a vale error, or a rule
# that no longer reports the planted claims.
set -eu

PLANTED_EXPECTED=8

if ! command -v vale >/dev/null 2>&1; then
  echo "check-claims: vale is not installed; install it (https://vale.sh/docs/install/)" \
    "or rely on the Claim check workflow" >&2
  exit 1
fi

lint() {
  vale --no-global --no-wrap --output=line "$@"
}

rc=0
lint profile || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "check-claims: profile/ failed with rc $rc;" \
    "state the scope each claim's evidence proves (ADR-0001)" >&2
  exit 1
fi

rc=0
lint tests/claims/qualified.md || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "check-claims: tests/claims/qualified.md failed with rc $rc;" \
    "the rule now reports qualified text" >&2
  exit 1
fi

rc=0
out=$(lint tests/claims/planted.md) || rc=$?
hits=$(printf '%s\n' "$out" | awk '/:VMAFx[.]AbsoluteClaim:/ { n++ } END { print n + 0 }')
if [ "$rc" -ne 1 ] || [ "$hits" -ne "$PLANTED_EXPECTED" ]; then
  printf '%s\n' "$out" >&2
  echo "check-claims: tests/claims/planted.md gave rc $rc (want 1)" \
    "and $hits reports (want $PLANTED_EXPECTED)" >&2
  exit 1
fi

echo "check-claims: profile clean; qualified fixture clean;" \
  "planted fixture reported $hits of $PLANTED_EXPECTED"
