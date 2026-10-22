#!/usr/bin/env bash
# Split each IPA in OUT_DIR into parts under 2 GiB and attach them to a DRAFT GitHub
# release (drafts are visible only to people with write access to the repository).
# Needed because an IPA of several GB exceeds most Actions artifact quotas and the
# 2 GiB per-file limit of release assets.
#
#   scripts/publish_release_parts.sh OUT_DIR
#
# Environment: GITHUB_REPOSITORY and GH_TOKEN (for gh), GITHUB_RUN_ID (used in the tag),
#              PART_BYTES (default 1992294400 = 1900 MiB).
set -euo pipefail

OUT_DIR="${1:?usage: publish_release_parts.sh OUT_DIR}"
PART_BYTES="${PART_BYTES:-1992294400}"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}"
RUN_ID="${GITHUB_RUN_ID:-local}"

sha256() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}

cd "$OUT_DIR"
shopt -s nullglob
ipas=( *.ipa )
if (( ${#ipas[@]} == 0 )); then
  echo "no IPA in $OUT_DIR; nothing to publish"
  exit 0
fi

n=0
for ipa in "${ipas[@]}"; do
  n=$((n + 1))
  tag="ipa-${RUN_ID}"
  if (( ${#ipas[@]} > 1 )); then tag="${tag}-${n}"; fi
  prefix="${ipa}.part-"
  rm -f "${prefix}"*
  split -b "$PART_BYTES" "$ipa" "$prefix"
  parts=( "${prefix}"* )
  digest="$(sha256 "$ipa")"
  size="$(wc -c < "$ipa" | tr -d ' ')"

  notes="$(mktemp)"
  {
    echo "Parts of ${ipa} (${size} bytes, sha256 ${digest})."
    echo
    echo "Download every part, then join them in order:"
    echo
    echo "    cat '${ipa}.part-'* > '${ipa}'"
    echo "    shasum -a 256 '${ipa}'"
    echo
    echo "The hash must match the one above. Delete this release when you are done."
  } > "$notes"

  echo "Publishing ${#parts[@]} part(s) of ${ipa} to draft release ${tag}"
  gh release create "$tag" "${parts[@]}" \
    --repo "$REPO" --draft \
    --title "IPA parts (run ${RUN_ID})" \
    --notes-file "$notes"
  rm -f "$notes" "${parts[@]}"
done
