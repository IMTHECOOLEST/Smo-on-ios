# smo-ios

Cloud build harness and DualSense layer for running **your own** Super Mario Odyssey dump on iOS with [nxnative](https://github.com/seedds/nxnative). You supply the NSPs and `prod.keys` in one zip; a Mac runner does the build. Nothing from any game is in this repository.

## Read this first

- **nxnative now lists Super Mario Odyssey** as supported: base game (NSP or XCI) + update 1.4.1, IPA about 6 GB (22 October 2026, from its README; I could not open the profile folder itself, so the workflow's run summary confirms `profile 0100000000010000: found` at run time).
- This repo does not contain the port. It is the cloud build harness around nxnative: it takes your files as one zip, builds on a Mac runner, and hands you the IPA. In `auto` mode it builds when nxnative has a profile for the game and runs a survey when it does not.
- **Not yet verified:** nothing here has run on a real Mac runner or an iPhone. The Python, shell and C parts have unit tests; the Objective-C DualSense code is only checked by CI on first run, and it is not wired into nxnative.

## Use it

Full walkthrough: **[docs/TUTORIAL.md](docs/TUTORIAL.md)** (prepare the files, build on your own Mac or in the cloud, install, troubleshoot). Short version of the cloud route:

1. Create a **private** repo from this code. The workflow refuses to run in a public repo, because the IPA embeds your game files.
2. On a computer, pack your files (base game NSP or XCI, update 1.4.1 NSP):
   ```
   python3 scripts/pack_inputs.py --nsp-dir ~/Games/SMO --keys ~/keys/prod.keys -o smo-inputs.zip
   ```
3. Put the zip somewhere only you can reach and get a direct download URL. Add repo secrets:
   - `INPUT_ZIP_URL` (required)
   - `INPUT_ZIP_SHA256` (printed by the pack script; recommended)
   - `OUTPUT_PUT_URL` (optional; a single PUT is often capped at 5 GB, below Odyssey's ~6 GB IPA)
4. **Actions, Build IPA, Run workflow.** Leave `mode` on `auto` and `release_parts` on.
5. Download the IPA parts from the draft release, join them (`cat` and check the hash in the notes), and install.

## Controls and 1.43:1 work (patches)

Put `controls-1_43.patch` (from the earlier chat) in `patches/`. The workflow applies every `patches/*.patch` to the nxnative checkout before building (`apply_patches` input, on by default). Set `nxnative_url` and `nxnative_ref` to the repo and commit the patch was made against; if it does not apply, the run stops and `diagnostics/patches.txt` says why.

After the build the workflow also:

- writes `diagnostics/compile-errors.txt` (and the first 40 lines into the run summary), so the never-compiled Objective-C and SDL3 code is checked by a real Xcode build;
- runs `dm/tools/aspect_scan.py` on the extracted `main` NSO with `--ratio 1.43` (`aspect_scan` and `aspect_ratio` inputs) and writes `diagnostics/aspect-scan.txt`. It looks for an extracted `main` file on the runner; if nxnative removed it, the file says so.

## No billing set up? Use a public repo (free macOS runners)

Private repos bill macOS minutes at a multiplier; with a failed payment or a $0 spending limit the job never starts ("recent account payments have failed or your spending limit needs to be increased"). Standard GitHub-hosted runners are free in **public** repositories. Make this repo public (Settings, Danger Zone, Change visibility; it holds no game data or keys) and run Build IPA with **`allow_public` on**. In that mode:

- the IPA parts and a `diagnostics.zip` go only to **draft releases** (visible to people with write access), never to artifacts, which anyone can download from a public repo;
- the run log and summary are public: they show file names, the title ID and build output (key contents are never printed), so use throwaway names if that matters;
- delete both draft releases when you have downloaded them, and never publish them.

A free standard runner may still be too small for Odyssey's disk needs; the run stops early with a clear message if so.

## Limits to check before running

- **Disk:** nxnative needs about twice the NSPs' size plus 10 GB free. The script checks this and fails early. Standard GitHub Mac runners list only 14 GB of storage, so you will likely need a larger or self-hosted Mac (`runner` input).
- **Cost and quota:** private repos bill macOS minutes at a multiplier. The IPA is about 6 GB, which usually exceeds a personal plan's artifact storage, so the workflow also attaches it to a draft release in parts under 2 GiB (`release_parts`, on by default). The artifact upload is allowed to fail.
- **Other Macs:** `scripts/cloud_build.sh` runs on any Mac (EC2 Mac, MacStadium). Set `INPUT_ZIP_PATH` instead of `INPUT_ZIP_URL`.
- `nxnative_ref` defaults to `main`; pin a commit SHA for reproducible builds. The resolved commit is shown in the run summary.
- **Shader tool lock:** nxnative pins the exact spirv-cross build and Metal compiler it was authored with (`dm/gfx/tools/dmsh_chain.lock`), and a runner never has those exact binaries, so its shader stage stops with `translation chain tools do not match the lock file`. Before the build, `scripts/pick_xcode.sh` selects an installed Xcode whose Metal compiler matches the lock, if there is one, and `scripts/sync_chain_lock.sh` re-baselines the lock and the game profile's `dmsh_chain.h` to the tools the runner has. The rewriting is done by nxnative's own `dmsh_chain.py` in the runner's checkout; no nxnative code is patched. The first line of `diagnostics/toolchain-lock.txt` (also in the run summary) says `match`, `re-baselined` or `failed`; a re-baselined build translates shaders with tools nxnative was not pinned to, so keep that in mind if the game renders wrongly.

## What gets uploaded

Only small text files (survey, profile status, logs) and, when one is built, the IPA (as an artifact and as draft-release parts in your private repo). Extracted game files, rewritten code and shader libraries are never uploaded. Game data and keys are deleted from the runner on exit. Key contents are never printed.

## DualSense

See [dualsense/README.md](dualsense/README.md). Short version: rumble, gyro and light bar are implemented as a separate module but not wired into nxnative yet; each run produces a report showing where to wire it.

## Tests

```
python3 -m unittest discover -s tests -v
cc -std=c11 -Wall -Wextra -fsanitize=address,undefined tests/test_ds_core.c dualsense/dm_ds_core.c -lm -o /tmp/t && /tmp/t
```

## License

MIT (this repo only). nxnative is cloned at build time and keeps its own license.
