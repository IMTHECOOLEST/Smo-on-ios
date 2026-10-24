# patches/

Every `*.patch` file in this folder is applied, in name order, to the nxnative
checkout before the build (`scripts/apply_patches.sh`). Patches use `git diff` format
with `-p1` paths relative to the nxnative root.

Put `controls-1_43.patch` here. It must be made against the same nxnative repo and
commit the workflow checks out (`nxnative_url` and `nxnative_ref` inputs). If it does
not apply, the run stops and `diagnostics/patches.txt` says why.
