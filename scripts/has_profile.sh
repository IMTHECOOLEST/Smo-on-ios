#!/usr/bin/env bash
# Print "found" if an nxnative checkout has a game profile for a title ID, else "missing".
# Profiles live in dm/games/<base game title ID>/ (see nxnative's docs/development.md).
#   scripts/has_profile.sh /path/to/nxnative 0100000000010000
set -euo pipefail
NX="${1:?usage: has_profile.sh <nxnative checkout> <title id>}"
ID="${2:?usage: has_profile.sh <nxnative checkout> <title id>}"
want="$(printf '%s' "$ID" | tr '[:upper:]' '[:lower:]')"
for d in "$NX"/dm/games/*/; do
  [[ -d "$d" ]] || continue
  name="$(basename "$d" | tr '[:upper:]' '[:lower:]')"
  if [[ "$name" == "$want" ]]; then
    echo found
    exit 0
  fi
done
echo missing
