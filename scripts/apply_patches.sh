#!/usr/bin/env bash
# Apply every patches/*.patch to an nxnative checkout, in name order.
#   scripts/apply_patches.sh NX_DIR PATCH_DIR REPORT_FILE
# A patch that is already applied is skipped. A patch that neither applies nor is
# already applied stops the build (exit 1) with the reason in REPORT_FILE.
#
# Path depth is detected per patch, so both layouts work:
#   a/dm/x.c, b/dm/x.c                                   (git diff, -p1)
#   orig/nxnative-main/dm/x.c, nx/nxnative-main/dm/x.c   (diff -ruN of two unzipped folders, -p2)
#
# Written for bash 3.2 (macOS /bin/bash): no mapfile, no empty-array expansion.
set -Eeuo pipefail

NX="${1:?usage: apply_patches.sh <nxnative checkout> <patch dir> <report file>}"
DIR="${2:?usage: apply_patches.sh <nxnative checkout> <patch dir> <report file>}"
REPORT="${3:?usage: apply_patches.sh <nxnative checkout> <patch dir> <report file>}"

mkdir -p "$(dirname "$REPORT")"
: > "$REPORT"
# never die silently: say where, in the report and in the log
trap 'echo "apply_patches.sh crashed at line $LINENO" | tee -a "$REPORT" >&2' ERR

# git -C changes directory, so patch paths must be absolute
DIR="$(cd "$DIR" && pwd)"
shopt -s nullglob
patches=( "$DIR"/*.patch )

if (( ${#patches[@]} == 0 )); then
  echo "no patches in $DIR" | tee -a "$REPORT"
  exit 0
fi

# Print the number of leading path components to strip (-pN) for a patch:
# the smallest N for which an existing file in the checkout is named by a
# '--- old/path' header. Falls back to 1 if none of them exist (all-new-file patch).
detect_strip() {
  local patch="$1" p f stripped olds
  olds="$(awk -F'\t' '/^--- /{ if (n < 50) { sub(/^--- /,"",$1); sub(/[ \r]+$/,"",$1); if ($1 != "/dev/null") { print $1; n++ } } }' "$patch")"
  for p in 1 2 3 4; do
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      stripped="$(printf '%s\n' "$f" | cut -d/ -f"$((p + 1))-")"
      if [ -n "$stripped" ] && [ "$stripped" != "$f" ] && [ -e "$NX/$stripped" ]; then
        echo "$p"; return 0
      fi
    done <<EOF
$olds
EOF
  done
  echo 1
}

for p in "${patches[@]}"; do
  name="$(basename "$p")"
  n="$(detect_strip "$p")"
  if git -C "$NX" apply --check -p"$n" --whitespace=nowarn "$p" >/dev/null 2>&1; then
    git -C "$NX" apply -p"$n" --whitespace=nowarn "$p"
    echo "applied (-p$n): $name" | tee -a "$REPORT"
  elif git -C "$NX" apply --check --reverse -p"$n" --whitespace=nowarn "$p" >/dev/null 2>&1; then
    echo "already applied, skipped: $name" | tee -a "$REPORT"
  else
    {
      echo "FAILED: $name does not apply to this nxnative commit (tried -p$n)"
      git -C "$NX" apply --check -p"$n" --whitespace=nowarn "$p" 2>&1 | head -n 40 || true
    } | tee -a "$REPORT" >&2
    echo "hint: the patch was made against a different nxnative commit or fork, or the tree" \
         "has edits that differ from the patch. Set nxnative_url/nxnative_ref to the base it" \
         "was made for, or regenerate the patch against the tree you are building." >&2
    exit 1
  fi
done
