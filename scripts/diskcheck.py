#!/usr/bin/env python3
"""Fail early if there is not enough free disk for nxnative's build.

    python3 scripts/diskcheck.py DIR NSP_BYTES

nxnative's README: free space of about twice the NSPs' size plus 10 GB
(on top of the NSPs themselves).
"""
import shutil
import sys

GIB = 1024 ** 3


def required_bytes(nsp_bytes):
    return 2 * nsp_bytes + 10 * GIB


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    path, nsp_bytes = argv[1], int(argv[2])
    need = required_bytes(nsp_bytes)
    free = shutil.disk_usage(path).free
    print(f"disk: {free / GIB:.1f} GiB free, build needs about {need / GIB:.1f} GiB")
    if free < need:
        print(
            "error: not enough free disk space. Use a runner with more disk "
            "(larger or self-hosted Mac) via the 'runner' workflow input.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
