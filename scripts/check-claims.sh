#!/bin/sh
# SPDX-FileCopyrightText: 2026 Lusoris <lusoris@proton.me>
# SPDX-License-Identifier: EUPL-1.2
#
# Claim check (docs/adr/0001-absolute-claim-check.md). Check the profile and
# qualified fixture, then exercise both selectors with planted claims.
set -eu

for path in profile/README.md tests/claims/qualified.md tests/claims/planted.md; do
  if [ ! -f "$path" ]; then
    echo "check-claims: missing required file: $path" >&2
    exit 1
  fi
done

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

scratch=$(mktemp -d)
trap 'rm -r "$scratch"' EXIT
cp -R .vale.ini .vale "$scratch/"
mkdir "$scratch/profile"
readme="$scratch/profile/README.md"
cp profile/README.md "$readme"
printf '\n\nEvery device gives the same score.\n' >> "$readme"
line=$(wc -l < "$readme")
rc=0
out=$(cd "$scratch" && lint profile) || rc=$?
if [ "$rc" -ne 1 ] || ! printf '%s\n' "$out" | awk -F: -v line="$line" '
  $1 == "profile/README.md" && $2 == line + 0 && $4 == "VMAFx.AbsoluteClaim" { hit = 1 }
  END { exit !hit }
'; then
  printf '%s\n' "$out" >&2
  echo "check-claims: profile selector does not reach profile/README.md" >&2
  exit 1
fi

rc=0
lint tests/claims/qualified.md || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "check-claims: tests/claims/qualified.md failed with rc $rc;" \
    "the rule now reports qualified text" >&2
  exit 1
fi

# One VMAFx.AbsoluteClaim report per expected match, in any order.
set -- "same score" "every device" "Every Vendor" "bit-for-bit" \
  "all GPUs" "always" "guaranteed" "bit exact"
rc=0
out=$(lint tests/claims/planted.md) || rc=$?
hits=$(printf '%s\n' "$out" | awk '/:VMAFx[.]AbsoluteClaim:/ { n++ } END { print n + 0 }')
if [ "$rc" -ne 1 ] || [ "$hits" -ne "$#" ]; then
  printf '%s\n' "$out" >&2
  echo "check-claims: tests/claims/planted.md gave rc $rc (want 1)" \
    "and $hits reports (want $#)" >&2
  exit 1
fi

for phrase do
  case "$out" in
    *":VMAFx.AbsoluteClaim:Absolute claim '$phrase':"*) ;;
    *)
      echo "check-claims: tests/claims/planted.md missing report for '$phrase'" >&2
      exit 1
      ;;
  esac
done

echo "check-claims: profile clean; qualified fixture clean;" \
  "planted fixture reported $hits of $#"
