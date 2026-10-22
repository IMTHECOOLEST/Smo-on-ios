# Tutorial: from your game files to an IPA

Checked against nxnative's README on 22 October 2026.

> **Status of Super Mario Odyssey.** nxnative's README now lists Odyssey in its games table: **base game (NSP, or an XCI cartridge dump) + update 1.4.1**, IPA about **6 GB**. I could read that in snapshots of the README but could not open the `dm/games/0100000000010000/` folder itself, so the build tells you at run time: the run summary says `profile 0100000000010000: found` or `missing`. If it says `missing`, your nxnative checkout predates the profile; use `nxnative_ref: main`.

Use only dumps from your own Switch. Never commit, paste or share your keys or game files.

---

## 1. Prepare your files (needed for both routes)

You need:

- the **base game**: an `.nsp`, or an `.xci` cartridge dump
- the **update 1.4.1** as an `.nsp`: title ID `0100000000010800`, version tag `v393216`
- your **`prod.keys`**

Rules that avoid the usual failures:

- **NSZ and XCZ (compressed) are not supported.** Decompress them first. The update must be an NSP.
- **Keep the `[title ID]` in the file names.** nxnative finds the game profile from it (it falls back to the ticket inside the NSP).
- Put exactly one game's files in one folder:

```
~/Games/SMO/
  Super Mario Odyssey [0100000000010000][v0].nsp
  Super Mario Odyssey [0100000000010800][v393216].nsp
```

No DLC is listed for Odyssey. For other games, see the row in nxnative's README.

---

## Route A: build on a Mac you control

This is nxnative's own documented flow. You need a Mac with [Xcode](https://apps.apple.com/app/xcode/id497799835) and [Homebrew](https://brew.sh). nxnative asks for free disk space of about twice the game files' size plus 10 GB; for Odyssey that is roughly 21 GB or more.

**A1. Get nxnative and its tools** (once):

```
git clone https://github.com/seedds/nxnative.git && cd nxnative
brew install xcodegen zstd spirv-cross
brew install --cask dotnet-sdk
python3 -m pip install lz4 capstone fonttools
```

**A2. Build:**

```
python3 scripts/build_ipa_from_nsp.py ~/Games/SMO -k ~/keys/prod.keys
```

The IPA appears in the same folder as your game files. The first build takes 30 to 60 minutes, later ones about 10. `-h` lists the options (`-o` output path, `--app-name` home-screen name).

Then go to step 3.

---

## Route B: build in the cloud with this repo

Everything runs on a Mac runner. Steps B1 to B3 and the final download need a **computer**: the files are several GB, which is impractical to handle from a phone. Steps B4 to B6 work from a phone browser.

**B1. Create your private repo.** Put this code in a new **private** repository. The workflow refuses to run in a public one, because the IPA contains your game files.

**B2. Pack your files into one zip** (on your computer, in a clone of this repo):

```
python3 scripts/pack_inputs.py --nsp-dir ~/Games/SMO --keys ~/keys/prod.keys -o smo-inputs.zip
```

It checks the files and the keys (it never prints key values), writes the zip, and prints a `sha256:` line. Copy that hash for B4. It warns if the update is missing or is not version 1.4.1, and stops if the title ID does not match.

**B3. Host the zip privately and get a direct download URL.** The URL must return the file itself, not a web page. A pre-signed link from your own storage works well. With the AWS CLI, for example:

```
aws s3 cp smo-inputs.zip s3://YOUR-PRIVATE-BUCKET/smo-inputs.zip
aws s3 presign s3://YOUR-PRIVATE-BUCKET/smo-inputs.zip --expires-in 86400
```

That link is valid for 24 hours. Delete the object when the build is done. (GitHub release assets are capped at 2 GiB per file, so they cannot hold this zip. Sharing pages of consumer cloud drives usually return a web page instead of the file.)

**B4. Add the secrets.** In your repo: **Settings, Secrets and variables, Actions, New repository secret.**

| Secret | Required | Value |
| --- | --- | --- |
| `INPUT_ZIP_URL` | yes | the download URL from B3 |
| `INPUT_ZIP_SHA256` | recommended | the hash printed in B2; the build stops if the download differs |
| `OUTPUT_PUT_URL` | no | a pre-signed upload URL; the IPA is also uploaded there. Many hosts cap a single PUT at 5 GB, which is below Odyssey's ~6 GB IPA, so this usually will not work for it |

**B5. Run it.** **Actions, Build IPA, Run workflow.** Inputs:

- `mode`: leave on `auto`. It builds if nxnative has a profile for the game and runs a survey if not.
- `title_id`: `0100000000010000` (Odyssey) is the default.
- `nxnative_ref`: `main`, or a full commit SHA to pin a version. The run summary shows which commit was used.
- `runner`: `macos-26` by default. If the run stops with a disk-space message, use a larger or self-hosted Mac.
- `release_parts`: leave on. See B6.

**B6. Get the IPA.** An IPA of about 6 GB usually exceeds the artifact storage quota of personal GitHub plans, so the workflow also publishes it as **parts of at most 1900 MiB on a draft release**:

1. In your repo, open **Releases** and find the draft named `IPA parts (run ...)`. Drafts are visible only to people with write access to the repo.
2. Download every `.part-` file (on your computer).
3. Join them in order and check the hash from the release notes:

```
cat 'Super Mario Odyssey.ipa.part-'* > 'Super Mario Odyssey.ipa'
shasum -a 256 'Super Mario Odyssey.ipa'
```

(The real file name is shown in the release notes.) Delete the release afterwards.

If your plan's quota allows it, the same IPA is also in the run's **Artifacts** as `ipa`; that upload is allowed to fail without failing the run. The `diagnostics` artifact (logs, survey, profile status, the report used for DualSense wiring) is always uploaded.

Extracted game files and rewritten code are never uploaded. Everything the build unpacked is deleted from the runner when it finishes.

Other Macs (EC2 Mac, MacStadium, your own): run `scripts/cloud_build.sh` there with `INPUT_ZIP_PATH=/path/to/smo-inputs.zip` instead of `INPUT_ZIP_URL`. Output goes to `./out`.

---

## 3. Install the IPA

The IPA is unsigned. Install it with a sideloading tool such as AltStore, Sideloadly or LiveContainer. The device needs iOS or iPadOS 26 or later.

nxnative's README advises signing with the **Increased Memory Limit** capability (`com.apple.developer.kernel.increased-memory-limit`) if your tool can: without it iOS gives the app about 3.4 GB and closes the bigger games; with it a recent iPhone gives about 6 GB. I have not tested Odyssey's memory needs, so use it if your tool offers it.

## 4. Play

- Tap **2D** or **3D** at the top for the touch layout.
- A connected controller hides the touch controls and keeps every button. The DualSense extras in this repo (rumble, gyro, light bar) are not wired in yet; see `dualsense/README.md`.
- Saves and logs are in the Files app under the app's name: `save/` and `log.txt`. If something goes wrong, `log.txt` (and `log.prev.txt`) is what to look at.
- Settings without rebuilding go in `Documents/env.txt`, one `KEY=VALUE` per line.

## 5. When something fails

| Symptom | Cause and fix |
| --- | --- |
| Workflow says the repository is public | Make the repo private (Settings, Danger Zone). |
| `INPUT_ZIP_URL` error or empty download | The secret is missing, expired, or points to a web page. Re-create the link (B3). |
| SHA-256 mismatch | The zip changed or the download was cut off. Re-pack, and update `INPUT_ZIP_SHA256`. |
| "Wrong game" | The file names carry a different title ID than the `title_id` input. |
| "not enough free disk space" | Use a runner with more disk (the `runner` input). |
| Summary says `profile ...: missing`, run ends with a survey | Your nxnative checkout has no profile for that title ID. Set `nxnative_ref` to `main` and run again. |
| `ipa` artifact upload failed | Quota. Use the draft release parts (B6). |
| No draft release | `release_parts` was off, or no IPA was produced. Check `diagnostics/nxnative-build.log`. |
| Build fails inside nxnative | Open `diagnostics/nxnative-build.log`. Check nxnative's issues page before filing anything, and never post keys. |
| Run summary says `shader tool lock, failed: ...`, or the shader stage said `translation chain tools do not match the lock file` | The runner's spirv-cross and Metal compiler differ from the ones pinned in nxnative's `dmsh_chain.lock`. The build now picks an installed Xcode with the locked Metal compiler if there is one, and otherwise re-baselines the lock and the profile's header to the runner's tools (`re-baselined:`). `failed:` means that was not possible, for example because nxnative's translator was not built from source; read `diagnostics/toolchain-lock.txt` and check nxnative's issues page. |

## Checking support for another game

In a clone of nxnative, `python3 dm/games/game.py list` lists the supported profiles, and the **Games** table in its README lists the tested ones. Set the workflow's `title_id` to the base title ID (the update ID minus `0x800`) to build one of them.
