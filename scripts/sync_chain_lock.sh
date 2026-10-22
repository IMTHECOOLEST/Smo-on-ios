#!/usr/bin/env bash
# Make nxnative's pinned shader tool lock agree with the tools on this machine.
#   scripts/sync_chain_lock.sh <nxnative checkout> <title id> <report file>
#
# nxnative pins the translation chain (spirv-cross, the Metal compiler, the translator)
# in dm/gfx/tools/dmsh_chain.lock, and its shader stage refuses to run when the tools
# differ. A runner never has the author's exact binaries, so this script:
#   1. runs dmsh_chain.py --check-tools; if it passes, nothing else happens;
#   2. otherwise runs --update-lock (nxnative refuses this for a translator that was
#      not built from source; that failure is reported and never absorbed),
#   3. runs --header for the profile of the target title ID, because the chain version
#      hashes the lock and the profile's committed dmsh_chain.h goes stale otherwise,
#   4. runs --check-tools again.
# Nothing in the nxnative checkout is edited by hand; only dmsh_chain.py writes there.
#
# The first line of the report says what happened: "match:", "re-baselined:",
# "skipped: ..." (exit 0) or "failed: ..." (exit 1, also printed to stderr).
set -euo pipefail

NX_ARG="${1:?usage: sync_chain_lock.sh <nxnative checkout> <title id> <report file>}"
ID="${2:?usage: sync_chain_lock.sh <nxnative checkout> <title id> <report file>}"
REPORT="${3:?usage: sync_chain_lock.sh <nxnative checkout> <title id> <report file>}"

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
CHAIN="$TOOLS/dmsh_chain.py"
LOCK="$TOOLS/dmsh_chain.lock"

[ -f "$CHAIN" ] || skip "this nxnative commit has no dm/gfx/tools/dmsh_chain.py"
[ -f "$LOCK" ] || skip "this nxnative commit has no dm/gfx/tools/dmsh_chain.lock"

# Profiles are dm/games/<base title ID>/ folders that have a game.tsv.
want="$(printf '%s' "$ID" | tr '[:upper:]' '[:lower:]')"
match=""
any=""
for d in "$NX"/dm/games/*/; do
  [ -f "${d}game.tsv" ] || continue
  name="$(basename "$d")"
  [ -n "$any" ] || any="$name"
  if [ -z "$match" ] && [ "$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')" = "$want" ]; then
    match="$name"
  fi
done
[ -n "$any" ] || skip "this nxnative commit has no game profile with a game.tsv"
game="${match:-$any}"   # dmsh_chain.py needs some profile to start; only a matching one gets a header

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sync_chain_lock.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

OUT=""
RC=0
run_chain() {
  RC=0
  OUT="$(cd "$NX" && DM_GAME="$game" python3 "$CHAIN" "$@" 2>&1 < /dev/null)" || RC=$?
}

BEFORE=""
fail() {
  {
    printf 'failed: %s\n' "$1"
    printf '(DM_GAME=%s, nxnative %s)\n\n' "$game" "$NX"
    printf '%s\n' "$OUT"
    if [ -n "$BEFORE" ]; then
      printf '\nlock before:\n%s\n' "$BEFORE"
      printf '\nlock now:\n%s\n' "$(cat "$LOCK")"
    fi
  } > "$REPORT"
  cat "$REPORT" >&2
  exit 1
}

run_chain --check-tools
if [ "$RC" -eq 0 ]; then
  {
    printf 'match: runner tools match the lock file (DM_GAME=%s)\n' "$game"
    printf '%s\n' "$OUT"
  } > "$REPORT"
  cat "$REPORT"
  exit 0
fi
DIFFERED="$OUT"

cp "$LOCK" "$TMP/lock.before"
BEFORE="$(cat "$LOCK")"

run_chain --update-lock
if [ "$RC" -ne 0 ]; then
  if cmp -s "$LOCK" "$TMP/lock.before"; then state="lock file left unchanged"; else state="lock file was modified"; fi
  fail "dmsh_chain.py --update-lock exited $RC ($state); the tools cannot be re-baselined here"
fi
UPDATE_OUT="$OUT"

if [ -n "$match" ]; then
  run_chain --header
  [ "$RC" -eq 0 ] || fail "dmsh_chain.py --header exited $RC for profile $match"
  HEADER_OUT="$OUT"
  HEADER_NOTE="dmsh_chain.h regenerated for profile $match"
  SUMMARY="lock rewritten, header regenerated for $match"
else
  HEADER_OUT="(not run)"
  HEADER_NOTE="no profile for $ID, so no header was regenerated ($game was only used to start dmsh_chain.py)"
  SUMMARY="lock rewritten, no profile for $ID so no header"
fi

run_chain --check-tools
[ "$RC" -eq 0 ] || fail "tools still do not match the lock file after --update-lock"

AFTER="$(cat "$LOCK")"

# Informational only: the chain version that dmsh_build.py looks for in the profile's header.
vout="$(cd "$NX" && DM_GAME="$game" python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import dmsh_chain; print(dmsh_chain.version())' "$TOOLS" 2>/dev/null < /dev/null)" || vout=""
VERSION="$(printf '%s\n' "$vout" | tail -n 1)"
[ -n "$VERSION" ] || VERSION="unavailable (could not call dmsh_chain.version())"

{
  printf "re-baselined: runner tools differ from nxnative's lock; %s\n" "$SUMMARY"
  printf '\nwhat differed:\n%s\n' "$DIFFERED"
  printf '\nlock before:\n%s\n' "$BEFORE"
  printf '\nlock after:\n%s\n' "$AFTER"
  printf '\nchain version: %s\n' "$VERSION"
  printf 'header: %s\n' "$HEADER_NOTE"
  printf '\n--update-lock output:\n%s\n' "$UPDATE_OUT"
  printf '\n--header output:\n%s\n' "$HEADER_OUT"
} > "$REPORT"
cat "$REPORT"
