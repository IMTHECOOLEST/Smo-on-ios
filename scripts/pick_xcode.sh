#!/usr/bin/env bash
# Print the Contents/Developer path of an installed Xcode whose Metal compiler is
# the one nxnative's shader tool lock (dm/gfx/tools/dmsh_chain.lock) was made with.
#   scripts/pick_xcode.sh /path/to/nxnative/dm/gfx/tools/dmsh_chain.lock
#
# Best effort, always exits 0. Prints nothing when
#   - the Xcode already in use has both locked Metal versions (macosx and iphoneos SDK),
#   - the lock has no metal_macosx / metal_iphoneos lines,
#   - or no installed Xcode matches.
# Otherwise prints one line: the developer dir of the first match, for DEVELOPER_DIR.
#
# A "match" means the first line of `xcrun -sdk <sdk> metal --version` equals the
# lock's value exactly, for BOTH macosx and iphoneos. An Xcode whose Metal compiler
# does not run (e.g. the Metal toolchain component is not installed) is skipped.
# Xcodes are searched in "${XCODE_SEARCH_DIR:-/Applications}"/Xcode*.app, in glob order.
set -u

lock="${1:-}"
if [ -z "$lock" ] || [ ! -r "$lock" ]; then exit 0; fi

# Value of "<key> = value", "<key>: value" or "<key> value" in the lock; fails if absent or empty.
lock_value() {
  local key="$1" file="$2" line rest
  while IFS= read -r line || [ -n "$line" ]; do
    line="$(printf '%s' "$line" | tr -d '\r')"
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in "$key"*) ;; *) continue ;; esac
    rest="${line#"$key"}"
    case "$rest" in [=:[:space:]]*) ;; *) continue ;; esac
    rest="${rest#"${rest%%[![:space:]]*}"}"
    case "$rest" in [=:]*) rest="${rest#?}" ;; esac
    rest="${rest#"${rest%%[![:space:]]*}"}"
    rest="${rest%"${rest##*[![:space:]]}"}"
    [ -n "$rest" ] || return 1
    printf '%s' "$rest"
    return 0
  done < "$file"
  return 1
}

# First line of `metal --version` for an SDK. dev is a developer dir, or "" for the Xcode in use.
metal_line() {
  local dev="$1" sdk="$2" out
  if [ -n "$dev" ]; then
    out="$(DEVELOPER_DIR="$dev" xcrun -sdk "$sdk" metal --version 2>/dev/null)" || return 1
  else
    out="$(xcrun -sdk "$sdk" metal --version 2>/dev/null)" || return 1
  fi
  printf '%s\n' "$out" | head -n 1 | tr -d '\r'
}

want_mac="$(lock_value metal_macosx "$lock")" || exit 0
want_ios="$(lock_value metal_iphoneos "$lock")" || exit 0
[ -n "$want_mac" ] && [ -n "$want_ios" ] || exit 0

matches() {
  [ "$(metal_line "$1" macosx)" = "$want_mac" ] && [ "$(metal_line "$1" iphoneos)" = "$want_ios" ]
}

if matches ""; then exit 0; fi

for app in "${XCODE_SEARCH_DIR:-/Applications}"/Xcode*.app; do
  dev="$app/Contents/Developer"
  [ -d "$dev" ] || continue
  if matches "$dev"; then
    printf '%s\n' "$dev"
    exit 0
  fi
done
exit 0
