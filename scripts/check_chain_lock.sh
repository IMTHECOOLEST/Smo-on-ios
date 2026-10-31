#!/usr/bin/env bash
# Check nxnative's pinned shader tool lock against the tools on this machine. It never changes anything in the checkout.
#   scripts/check_chain_lock.sh <nxnative checkout> <report file> [title id]
#
# nxnative pins the shader translation chain in dm/gfx/tools/dmsh_chain.lock: the translator, SPIRV-Cross (both come with
# the checkout, dm/gfx/tools) and the Metal compiler of Xcode 27.1. Only the Metal compiler depends on the machine. This script used to
# rewrite the lock and the header to whatever tools the runner had; that changes the chain version and swaps tools the shaders were
# tested with, and nxnative itself says another Metal compiler can corrupt the picture (its GitHub issue #242). So now the lock is left
# as it is and the Metal compiler is checked, nothing more. To build with a Metal compiler that is not the locked one anyway, the caller
# passes --allow-other-metal to nxnative's build script (cloud_build.sh does this only when ALLOW_OTHER_METAL=1).
#
# Exit status and the first line of the report:
#   0  "match: ..."       the tools are the locked ones
#   0  "skipped: ..."     this nxnative commit has no lock check, nothing to do
#   3  "metal-only: ..."  only the Metal compiler differs from the lock (the other tools are the locked ones)
#   1  "failed: ..."      anything else: another translator or SPIRV-Cross, a Metal compiler that does not run, a checker that crashed
# The rest of the report is the checker's own output.
set -uo pipefail

NX_ARG="${1:?usage: check_chain_lock.sh <nxnative checkout> <report file> [title id]}"
REPORT="${2:?usage: check_chain_lock.sh <nxnative checkout> <report file> [title id]}"
ID="${3:-}"

mkdir -p "$(dirname "$REPORT")"

skip() {
  printf 'skipped: %s\n' "$*" > "$REPORT"
  cat "$REPORT"
  exit 0
}

if ! NX="$(cd "$NX_ARG" 2>/dev/null && pwd)"; then
  skip "no nxnative checkout at $NX_ARG"
fi
TOOLS="$NX/dm/gfx/tools"
LOCK="$TOOLS/dmsh_chain.lock"
[ -f "$LOCK" ] || skip "this nxnative commit has no dm/gfx/tools/dmsh_chain.lock"

# The checker: tool_lock.py in current nxnative, dmsh_chain.py itself before the check moved out of it
if [ -f "$TOOLS/tool_lock.py" ]; then
  CHECKER="$TOOLS/tool_lock.py"
elif [ -f "$TOOLS/dmsh_chain.py" ] && grep -q -- "--check-tools" "$TOOLS/dmsh_chain.py"; then
  CHECKER="$TOOLS/dmsh_chain.py"
else
  skip "this nxnative commit has no lock check (dm/gfx/tools/tool_lock.py)"
fi

# Some older checkers want a game profile just to start
if [ -n "$ID" ] && [ -d "$NX/dm/games/$ID" ]; then export DM_GAME="$ID"; fi

out="$(cd "$NX" && python3 "$CHECKER" --check-tools 2>&1)"
rc=$?

if [ "$rc" -eq 0 ]; then
  { echo "match: the shader tools are the ones dmsh_chain.lock records"; [ -z "$out" ] || printf '%s\n' "$out"; } > "$REPORT"
  cat "$REPORT"
  exit 0
fi

# Every mismatch is one line "...: <tool>: lock <x> / actual <y>". Only a Metal compiler that is present but another one is allowed to differ
others="$(printf '%s\n' "$out" | grep -E "RED|lock .* / actual" | grep -Ev "(metal_macosx|metal_iphoneos): lock .* / actual " || true)"
others="$others$(printf '%s\n' "$out" | grep -E "(metal_macosx|metal_iphoneos): lock .* / actual missing$" || true)"
metal="$(printf '%s\n' "$out" | grep -E "(metal_macosx|metal_iphoneos): lock .* / actual " | grep -Ev "actual missing$" || true)"
if [ -n "$metal" ] && [ -z "$(printf '%s' "$others" | tr -d "[:space:]")" ]; then
  { echo "metal-only: the Metal compiler on this machine is not the locked one (the other tools are)"; printf '%s\n' "$out"; } > "$REPORT"
  cat "$REPORT"
  exit 3
fi

{ echo "failed: the shader tools do not match dmsh_chain.lock (checker exit status $rc)"; printf '%s\n' "$out"; } > "$REPORT"
cat "$REPORT" >&2
exit 1
