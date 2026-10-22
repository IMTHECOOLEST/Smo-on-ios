#!/usr/bin/env python3
"""Safely unpack the user-supplied inputs zip for the build.

    python3 scripts/prepare_inputs.py INPUT.zip DEST_DIR [--title-id 0100000000010000]

Result:
    DEST_DIR/prod.keys      (mode 600)
    DEST_DIR/nsp/*.nsp (and *.xci)

Safety:
  * Entry names are never used as paths. Only exactly one 'prod.keys' and any
    '*.nsp' / '*.xci' are accepted, flattened to their base names (no zip-slip, no
    symlinks, nothing else is written).
  * Duplicate NSP base names are rejected instead of overwritten.
  * Key contents are never printed, only the number of key lines.
  * Disk space is checked before anything is written.
"""
import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import PurePosixPath

TITLE_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
KEY_LINE_RE = re.compile(rb"^\s*[A-Za-z0-9_]+\s*=\s*[0-9A-Fa-f]+\s*$")
CHUNK = 1 << 20
SPACE_MARGIN = 512 * 1024 * 1024


class InputError(Exception):
    pass


def safe_base_name(entry_name):
    """Return a safe base name for a zip entry, or raise InputError."""
    if "\x00" in entry_name:
        raise InputError("zip entry name contains a NUL byte")
    normalized = entry_name.replace("\\", "/")
    base = PurePosixPath(normalized).name
    if base in ("", ".", ".."):
        raise InputError(f"zip entry has no usable file name: {entry_name!r}")
    return base


def classify(infos):
    """Split zip entries into (keys_entry, [nsp entries]). Directories and other files are ignored."""
    keys, nsps, ignored = [], [], 0
    seen = {}
    for info in infos:
        if info.is_dir():
            continue
        base = safe_base_name(info.filename)
        # Archives made on Apple devices can carry AppleDouble metadata ("__MACOSX/" folders and
        # "._name" files). It is not game data and must never be mistaken for an NSP or a keys file.
        parts = info.filename.replace("\\", "/").split("/")
        if "__MACOSX" in parts or base.startswith("._"):
            ignored += 1
            continue
        low = base.lower()
        if low == "prod.keys":
            keys.append(info)
        elif low.endswith((".nsp", ".xci")):
            if base in seen:
                raise InputError(f"two game files share the file name {base!r}; rename one")
            seen[base] = info
            nsps.append((base, info))
        else:
            ignored += 1
    if len(keys) != 1:
        raise InputError(f"expected exactly one prod.keys in the zip, found {len(keys)}")
    if not nsps:
        raise InputError("no .nsp or .xci files in the zip")
    return keys[0], nsps, ignored


def check_title(nsps, wanted):
    wanted = wanted.upper()
    ids = set()
    for base, _ in nsps:
        ids |= {m.upper() for m in TITLE_RE.findall(base)}
    if ids and wanted not in ids:
        raise InputError(
            f"none of the NSP names carries the title ID [{wanted}] (found: {', '.join(sorted(ids))}). Wrong game?"
        )
    if not ids:
        print("warning: NSP names carry no [title ID]; nxnative will fall back to the ticket inside the NSP")


def copy_entry(zf, info, dest_path):
    # Opening and reading to EOF makes zipfile verify the CRC; a mismatch raises BadZipFile.
    with zf.open(info) as src, open(dest_path, "wb") as dst:
        shutil.copyfileobj(src, dst, CHUNK)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip_path")
    ap.add_argument("dest_dir")
    ap.add_argument("--title-id", default="0100000000010000")
    args = ap.parse_args(argv)

    try:
        with zipfile.ZipFile(args.zip_path) as zf:
            keys_info, nsps, ignored = classify(zf.infolist())
            check_title(nsps, args.title_id)

            total = keys_info.file_size + sum(i.file_size for _, i in nsps)
            os.makedirs(args.dest_dir, exist_ok=True)
            free = shutil.disk_usage(args.dest_dir).free
            if free < total + SPACE_MARGIN:
                raise InputError(
                    f"not enough free disk space to extract: need {total / 1e9:.1f} GB, have {free / 1e9:.1f} GB free"
                )

            nsp_dir = os.path.join(args.dest_dir, "nsp")
            os.makedirs(nsp_dir, exist_ok=True)

            keys_path = os.path.join(args.dest_dir, "prod.keys")
            copy_entry(zf, keys_info, keys_path)
            os.chmod(keys_path, 0o600)
            with open(keys_path, "rb") as f:
                key_lines = sum(1 for line in f if KEY_LINE_RE.match(line))
            if key_lines == 0:
                raise InputError("prod.keys has no 'name = hex' lines")

            for base, info in nsps:
                print(f"extracting {base} ({info.file_size / 1e9:.2f} GB)")
                copy_entry(zf, info, os.path.join(nsp_dir, base))
    except zipfile.BadZipFile as e:
        print(f"error: {e}", file=sys.stderr)
        print("hint: the zip is damaged or incomplete. Not every tool archives files over 4 GB correctly;"
              " re-create it with scripts/pack_inputs.py.", file=sys.stderr)
        return 1
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    nsp_bytes = sum(i.file_size for _, i in nsps)
    with open(os.path.join(args.dest_dir, "meta.env"), "w", encoding="utf-8") as f:
        f.write(f"NSP_BYTES={nsp_bytes}\n")
    print(f"ok: {len(nsps)} NSP(s), {key_lines} key line(s), {ignored} other entr{'y' if ignored == 1 else 'ies'} ignored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
