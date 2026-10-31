#!/usr/bin/env bash
# Build an IPA with nxnative from a user-supplied inputs zip, on any Mac
# (GitHub-hosted runner, self-hosted runner, EC2 Mac, ...).
#
# Environment:
#   INPUT_ZIP_URL      URL of the inputs zip (secret). Or set INPUT_ZIP_PATH to a local zip.
#   INPUT_ZIP_SHA256   optional; the download is rejected if it does not match
#   OUTPUT_PUT_URL     optional; the IPA is also uploaded there with an HTTP PUT
#   NXNATIVE_REF       nxnative branch, tag or commit (default: main)
#   MODE               auto | survey | build  (default: auto = build if nxnative has a profile
#                      for TITLE_ID, otherwise survey)
#   TITLE_ID           base title ID to require (default: 0100000000010000)
#   APP_NAME           optional home-screen name
#   APPLY_PATCHES      1 (default) applies patches/*.patch to the nxnative checkout; 0 skips
#   ALLOW_OTHER_METAL  0 (default) stops when the Mac has not the Metal compiler nxnative locked (Xcode 27.1); 1 builds with the one it has
#                      (nxnative's --allow-other-metal: such shaders can render wrong pictures, GitHub issue #242 of nxnative)
#   ASPECT_SCAN        1 (default) runs dm/tools/aspect_scan.py on the extracted main NSO
#   ASPECT_RATIO       ratio for the scan (default: 1.43)
#   WORK_DIR           scratch dir (default: ./work)
#   OUT_DIR            where IPA and diagnostics are collected (default: ./out)
#   KEEP_WORK          set to 1 to keep extracted game files and keys afterwards
#
# Nothing here prints key contents. Game data and keys are deleted on exit
# unless KEEP_WORK=1.
set -euo pipefail
set +x

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NXNATIVE_URL="${NXNATIVE_URL:-https://github.com/IMTHECOOLEST/NXNATIVE-1.43.1.git}"
NXNATIVE_REF="${NXNATIVE_REF:-main}"
MODE="${MODE:-auto}"
TITLE_ID="${TITLE_ID:-0100000000010000}"
WORK_DIR="${WORK_DIR:-$PWD/work}"
OUT_DIR="${OUT_DIR:-$PWD/out}"
KEEP_WORK="${KEEP_WORK:-0}"
APPLY_PATCHES="${APPLY_PATCHES:-1}"
ASPECT_SCAN="${ASPECT_SCAN:-1}"
ALLOW_OTHER_METAL="${ALLOW_OTHER_METAL:-0}"
ASPECT_RATIO="${ASPECT_RATIO:-1.43}"

case "$MODE" in auto|survey|build) ;; *) echo "error: MODE must be auto, survey or build" >&2; exit 2 ;; esac
if [[ ! "$NXNATIVE_REF" =~ ^[A-Za-z0-9._][A-Za-z0-9._/-]*$ ]]; then
  echo "error: NXNATIVE_REF has unexpected characters" >&2; exit 2
fi
if [[ ! "$NXNATIVE_URL" =~ ^https://[A-Za-z0-9._/-]+$ ]]; then
  echo "error: NXNATIVE_URL must be an https:// URL" >&2; exit 2
fi
if [[ ! "$TITLE_ID" =~ ^[0-9A-Fa-f]{16}$ ]]; then
  echo "error: TITLE_ID must be 16 hex digits" >&2; exit 2
fi
if [[ "$(uname -s)" != "Darwin" ]]; then echo "error: this script needs a Mac" >&2; exit 2; fi
if [[ -z "${INPUT_ZIP_PATH:-}" && -z "${INPUT_ZIP_URL:-}" ]]; then
  echo "error: set INPUT_ZIP_URL (or INPUT_ZIP_PATH)" >&2; exit 2
fi

mkdir -p "$WORK_DIR" "$OUT_DIR/diagnostics"
IN_DIR="$WORK_DIR/in"
NX_DIR="$WORK_DIR/nxnative"
ZIP="$WORK_DIR/inputs.zip"

cleanup() {
  if [[ "$KEEP_WORK" != "1" ]]; then
    # Remove only what this script created. A user-supplied INPUT_ZIP_PATH is never touched.
    rm -rf "$IN_DIR" "$WORK_DIR/inputs.zip"
  fi
}
trap cleanup EXIT

step() { printf '\n==> %s\n' "$*"; }

# 1. Get the zip --------------------------------------------------------------
if [[ -n "${INPUT_ZIP_PATH:-}" ]]; then
  step "Using local inputs zip"
  ZIP="$INPUT_ZIP_PATH"
else
  step "Downloading inputs zip"
  curl --fail --silent --show-error --location \
       --retry 5 --retry-delay 10 --retry-all-errors \
       --output "$ZIP" "$INPUT_ZIP_URL"
fi

if [[ -n "${INPUT_ZIP_SHA256:-}" ]]; then
  step "Verifying SHA-256"
  actual="$(shasum -a 256 "$ZIP" | awk '{print tolower($1)}')"
  expected="$(printf '%s' "$INPUT_ZIP_SHA256" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  if [[ "$actual" != "$expected" ]]; then
    echo "error: SHA-256 mismatch for the downloaded zip" >&2
    exit 1
  fi
fi

# 2. Unpack safely ------------------------------------------------------------
step "Unpacking inputs"
rm -rf "$IN_DIR"
python3 "$REPO_ROOT/scripts/prepare_inputs.py" "$ZIP" "$IN_DIR" --title-id "$TITLE_ID"
if [[ -z "${INPUT_ZIP_PATH:-}" ]]; then rm -f "$ZIP"; fi   # free the disk space
# shellcheck disable=SC1091
source "$IN_DIR/meta.env"
python3 "$REPO_ROOT/scripts/diskcheck.py" "$WORK_DIR" "$NSP_BYTES"

# 3. Tools --------------------------------------------------------------------
step "Installing build tools"
export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 HOMEBREW_NO_ENV_HINTS=1
brew install xcodegen zstd glslang   # SPIRV-Cross and the shader translator are nxnative's own (dm/gfx/tools), pinned by its lock: not Homebrew's
brew install --cask dotnet-sdk || {
  command -v dotnet >/dev/null 2>&1 || { echo "error: dotnet SDK unavailable" >&2; exit 1; }
  echo "note: cask install failed; using the dotnet already on this machine"
}
python3 -m venv "$WORK_DIR/venv"
export PATH="$WORK_DIR/venv/bin:$PATH"
python -m pip install --quiet lz4 capstone fonttools nsz zbic "backports.zstd; python_version < '3.14'"   # as nxnative's README lists them

# 4. nxnative -----------------------------------------------------------------
step "Fetching nxnative ($NXNATIVE_REF)"
rm -rf "$NX_DIR"
git init --quiet "$NX_DIR"
git -C "$NX_DIR" remote add origin "$NXNATIVE_URL"
git -C "$NX_DIR" fetch --quiet --depth 1 origin "$NXNATIVE_REF"
git -C "$NX_DIR" checkout --quiet FETCH_HEAD
git -C "$NX_DIR" submodule update --init --recursive --depth 1 --quiet || true

NX_SHA="$(git -C "$NX_DIR" rev-parse HEAD)"
echo "nxnative commit: $NX_SHA"
echo "$NX_SHA" > "$OUT_DIR/diagnostics/nxnative-commit.txt"

if [[ "$APPLY_PATCHES" == "1" ]]; then
  step "Applying patches"
  bash "$REPO_ROOT/scripts/apply_patches.sh" "$NX_DIR" "$REPO_ROOT/patches" "$OUT_DIR/diagnostics/patches.txt"
fi

PROFILE_STATUS="$(bash "$REPO_ROOT/scripts/has_profile.sh" "$NX_DIR" "$TITLE_ID")"
echo "profile for $TITLE_ID in this nxnative commit: $PROFILE_STATUS"
echo "profile $TITLE_ID: $PROFILE_STATUS" > "$OUT_DIR/diagnostics/profile-status.txt"
if [[ "$MODE" == "auto" ]]; then
  if [[ "$PROFILE_STATUS" == "found" ]]; then MODE="build"; else MODE="survey"; fi
  echo "mode auto -> $MODE"
fi
if [[ "$MODE" == "build" && "$PROFILE_STATUS" == "missing" ]]; then
  echo "warning: no profile for $TITLE_ID in this nxnative commit. nxnative will write a survey and" \
       "may pack a best-effort IPA from guessed values; do not expect it to run." >&2
fi

bash "$REPO_ROOT/scripts/inspect_nxnative_input.sh" "$NX_DIR" \
  > "$OUT_DIR/diagnostics/dualsense-integration-report.md" || true

# nxnative pins its shader translator, its SPIRV-Cross (both are in its checkout) and the Metal compiler of Xcode 27.1 in
# dm/gfx/tools/dmsh_chain.lock, and its build stops when they differ. Only the Metal compiler depends on the Mac: use an installed Xcode
# that has the locked one if there is one. The lock is then only CHECKED (scripts/check_chain_lock.sh), never rewritten: an earlier version
# of this script re-baselined the lock to whatever tools the runner had, which swaps the tools the shaders were tested with.
# Another Metal compiler stops the build unless ALLOW_OTHER_METAL=1 (nxnative's own --allow-other-metal; untested compilers can corrupt
# the picture). The report is diagnostics/toolchain-lock.txt.
allow_other_metal_arg=0
if [[ "$MODE" == "build" ]]; then
  step "Checking the shader tools against nxnative's lock"
  xcode_dev="$(bash "$REPO_ROOT/scripts/pick_xcode.sh" "$NX_DIR/dm/gfx/tools/dmsh_chain.lock")"
  if [[ -n "$xcode_dev" ]]; then
    export DEVELOPER_DIR="$xcode_dev"
    echo "using Xcode at $xcode_dev (its Metal compiler matches nxnative's lock)"
  fi
  if ! xcrun -sdk iphoneos metal --version >/dev/null 2>&1; then
    echo "the Metal toolchain component is not installed; downloading it"
    xcodebuild -downloadComponent MetalToolchain || echo "note: the Metal toolchain download failed"
  fi
  lock_rc=0
  bash "$REPO_ROOT/scripts/check_chain_lock.sh" "$NX_DIR" "$OUT_DIR/diagnostics/toolchain-lock.txt" "$TITLE_ID" || lock_rc=$?
  if [[ $lock_rc -eq 3 ]]; then
    if [[ "$ALLOW_OTHER_METAL" == "1" ]]; then
      echo "warning: building with a Metal compiler that is not nxnative's locked one (ALLOW_OTHER_METAL=1); the shaders can render wrong pictures" >&2
      allow_other_metal_arg=1
    else
      echo "error: this Mac's Metal compiler is not the one nxnative's shaders were tested with (see diagnostics/toolchain-lock.txt)." \
           "Use a runner with Xcode 27.1 (the runner input), or set allow_other_metal to build anyway (artifacts in the picture are then likely)." >&2
      exit 1
    fi
  elif [[ $lock_rc -ne 0 ]]; then
    exit "$lock_rc"
  fi
fi

# 5. Run nxnative -------------------------------------------------------------
step "Running nxnative ($MODE)"
args=("$IN_DIR/nsp" -k "$IN_DIR/prod.keys")
[[ "$MODE" == "survey" ]] && args+=(--survey-only)
[[ -n "${APP_NAME:-}" ]] && args+=(--app-name "$APP_NAME")
[[ "$allow_other_metal_arg" == "1" ]] && args+=(--allow-other-metal)

set +e
( cd "$NX_DIR" && python scripts/build_ipa_from_nsp.py "${args[@]}" ) 2>&1 | tee "$OUT_DIR/diagnostics/nxnative-build.log"
rc=${PIPESTATUS[0]}
set -e

# 6. Collect outputs ----------------------------------------------------------
step "Collecting outputs"

# Compiler errors, so a failed Objective-C build is readable without opening the full log.
grep -E 'error:|fatal error:|BUILD FAILED|Traceback' "$OUT_DIR/diagnostics/nxnative-build.log" \
  | head -n 200 > "$OUT_DIR/diagnostics/compile-errors.txt" || true

if [[ "$ASPECT_SCAN" == "1" ]]; then
  step "Scanning the main NSO for 16:9 sites (ratio $ASPECT_RATIO)"
  bash "$REPO_ROOT/scripts/aspect_scan.sh" "$NX_DIR" "$ASPECT_RATIO" \
    "$OUT_DIR/diagnostics/aspect-scan.txt" "$IN_DIR" "$WORK_DIR" "${RUNNER_TEMP:-$WORK_DIR}"
fi

find "$IN_DIR/nsp" -mindepth 2 \
  \( -name '*.md' -o -name '*.log' -o -name '*.tsv' -o -name '*.h' -o -name '*.txt' \) \
  -size -5M -type f -print0 2>/dev/null |
  while IFS= read -r -d '' f; do
    rel="${f#"$IN_DIR/nsp/"}"
    mkdir -p "$OUT_DIR/diagnostics/$(dirname "$rel")"
    cp "$f" "$OUT_DIR/diagnostics/$rel"
  done

ipa_count=0
while IFS= read -r -d '' ipa; do
  cp "$ipa" "$OUT_DIR/"
  ipa_count=$((ipa_count + 1))
  echo "IPA: $(basename "$ipa") ($(du -h "$ipa" | cut -f1))"
done < <(find "$WORK_DIR" -name '*.ipa' -type f -print0)

if [[ $rc -ne 0 ]]; then
  echo "nxnative exited with status $rc; see diagnostics/nxnative-build.log" >&2
  exit "$rc"
fi

if [[ "$MODE" == "build" && $ipa_count -eq 0 ]]; then
  if [[ "$PROFILE_STATUS" == "missing" ]]; then
    echo "No IPA: this nxnative commit has no profile for $TITLE_ID. See diagnostics for the survey." >&2
  else
    echo "error: nxnative reported success but produced no IPA" >&2
  fi
  exit 1
fi

# 7. Optional upload ----------------------------------------------------------
if [[ -n "${OUTPUT_PUT_URL:-}" && $ipa_count -gt 0 ]]; then
  step "Uploading IPA to your storage"
  first_ipa="$(find "$OUT_DIR" -maxdepth 1 -name '*.ipa' -type f | head -n 1)"
  curl --fail --silent --show-error --retry 3 --retry-delay 10 --retry-all-errors \
       --upload-file "$first_ipa" "$OUTPUT_PUT_URL"
  echo "uploaded"
fi

step "Done ($MODE): $ipa_count IPA(s)"
