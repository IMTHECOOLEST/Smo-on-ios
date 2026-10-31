# patches/

Every `*.patch` file in this folder is applied, in name order, to the nxnative
checkout before the build (`scripts/apply_patches.sh`). Patches use `git diff` format
with `-p1` paths relative to the nxnative root.

`odyssey-touch-layout.patch` adds the OD touch layout (Super Mario Odyssey's: one ring
on the left, JUMP / CAP / CROUCH on the right, the camera turned by swiping) to
`dm/ios/Sources/DmGamepad.m`. It is made against the updated NXNATIVE-1.43.1 tree
(nxnative's current `main` with the 1.43:1 view, the scaled touch pad with its floating
left stick and the controller work), so `nxnative_url` and `nxnative_ref` must name that
repo. If it does not apply, the run stops and `diagnostics/patches.txt` says why.

To make a patch against another tree: unzip it twice, edit one copy, and run
`diff -ruN a b > patches/name.patch` from their parent folder (`a/` and `b/` as the
folder names give `-p1` paths).
