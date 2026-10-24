#!/usr/bin/env bash
# Apply every patches/*.patch to an nxnative checkout, in name order.
#   scripts/apply_patches.sh NX_DIR PATCH_DIR REPORT_FILE
# A patch that is already applied is skipped. A patch that neither applies nor is
# already applied stops the build (exit 1) with the reason in REPORT_FILE.
set -euo pipefail

NX="${1:?usage: apply_patches.sh <nxnative checkout> <patch dir> <report file>}"
DIR="${2:?usage: apply_patches.sh <nxnative checkout> <patch dir> <report file>}"
REPORT="${3:?usage: apply_patches.sh <nxnative checkout> <patch dir> <report file>}"

mkdir -p "$(dirname "$REPORT")"
: > "$REPORT"
shopt -s nullglob
patches=( "$DIR"/*.patch )

if (( ${#patches[@]} == 0 )); then
  echo "no patches in $DIR" | tee -a "$REPORT"
  exit 0
fi

for p in "${patches[@]}"; do
  name="$(basename "$p")"
  if git -C "$NX" apply --check --whitespace=nowarn "$p" >/dev/null 2>&1; then
    git -C "$NX" apply --whitespace=nowarn "$p"
    echo "applied: $name" | tee -a "$REPORT"
  elif git -C "$NX" apply --check --reverse --whitespace=nowarn "$p" >/dev/null 2>&1; then
    echo "already applied, skipped: $name" | tee -a "$REPORT"
  else
    {
      echo "FAILED: $name does not apply to this nxnative commit"
      git -C "$NX" apply --check --whitespace=nowarn "$p" 2>&1 | head -n 40 || true
    } | tee -a "$REPORT" >&2
    echo "hint: the patch was made against a different nxnative commit or fork." \
         "Set nxnative_url/nxnative_ref to the base it was made for, or set apply_patches to false." >&2
    exit 1
  fi
done
