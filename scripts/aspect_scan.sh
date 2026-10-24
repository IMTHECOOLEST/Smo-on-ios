#!/usr/bin/env bash
# Run nxnative's dm/tools/aspect_scan.py on the game's extracted main NSO, if one can
# be found on this machine. Best effort: it never fails the build.
#   scripts/aspect_scan.sh NX_DIR RATIO REPORT_FILE SEARCH_DIR...
# The report holds only offsets and ready-to-paste patch-table lines (small text).
set -uo pipefail

NX="${1:?usage: aspect_scan.sh <nxnative checkout> <ratio> <report file> <search dir>...}"
RATIO="${2:?}"
REPORT="${3:?}"
shift 3

mkdir -p "$(dirname "$REPORT")"
: > "$REPORT"
tool="$NX/dm/tools/aspect_scan.py"
if [[ ! -f "$tool" ]]; then
  echo "skipped: $tool not found (the controls patch is not applied)" | tee -a "$REPORT"
  exit 0
fi
if [[ ! "$RATIO" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
  echo "skipped: ratio '$RATIO' is not a number" | tee -a "$REPORT"
  exit 0
fi

found=0
while IFS= read -r -d '' f; do
  found=$((found + 1))
  {
    echo "### $f"
    ( cd "$NX" && python dm/tools/aspect_scan.py "$f" --ratio "$RATIO" ) 2>&1 | head -n 400
    echo
  } >> "$REPORT"
done < <(find "$@" -type f -name main -size +1M -print0 2>/dev/null)

if (( found == 0 )); then
  echo "no extracted 'main' NSO found under: $*" | tee -a "$REPORT"
fi
exit 0
