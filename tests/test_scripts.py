"""Tests for the input packing/unpacking scripts. Uses tiny synthetic files only."""
import contextlib
import io
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pack_inputs  # noqa: E402
import prepare_inputs  # noqa: E402

FAKE_KEY_HEX = "deadbeefdeadbeefdeadbeefdeadbeef"
FAKE_KEYS = f"master_key_00 = {FAKE_KEY_HEX}\nheader_key = {FAKE_KEY_HEX}{FAKE_KEY_HEX}\n"
BASE = "Game [0100000000010000][v0].nsp"
UPD = "Game [0100000000010800][v393216].nsp"


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            zf.writestr(name, data)


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main(argv)
    return rc, out.getvalue(), err.getvalue()


class PrepareInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.zip = self.dir / "in.zip"
        self.dest = self.dir / "dest"

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, *extra):
        return run(prepare_inputs, [str(self.zip), str(self.dest), *extra])

    def test_happy_path(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), (f"nsp/{BASE}", b"base"), (f"nsp/{UPD}", b"upd"), ("readme.txt", b"x")])
        rc, out, err = self.prepare()
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(p.name for p in (self.dest / "nsp").iterdir()), sorted([BASE, UPD]))
        self.assertEqual((self.dest / "nsp" / BASE).read_bytes(), b"base")
        self.assertEqual(oct((self.dest / "prod.keys").stat().st_mode & 0o777), "0o600")
        self.assertIn("NSP_BYTES=7", (self.dest / "meta.env").read_text())
        self.assertIn("1 other entry ignored", out)
        self.assertNotIn(FAKE_KEY_HEX, out + err)  # key values are never printed

    def test_apple_metadata_entries_are_ignored(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), (f"nsp/{BASE}", b"base"),
                            ("__MACOSX/._prod.keys", b"meta"), ("__MACOSX/nsp/._" + BASE, b"meta"),
                            ("nsp/._" + BASE, b"meta")])
        rc, out, err = self.prepare()
        self.assertEqual(rc, 0, err)
        self.assertEqual([p.name for p in (self.dest / "nsp").iterdir()], [BASE])
        self.assertIn("3 other entries ignored", out)

    def test_zip_made_without_folder(self):
        # e.g. the Files app archiving the selected files directly, no nsp/ folder
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), (BASE, b"base"), (UPD, b"upd")])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(p.name for p in (self.dest / "nsp").iterdir()), sorted([BASE, UPD]))

    def test_zip_inside_one_top_level_folder(self):
        make_zip(self.zip, [("SMO/prod.keys", FAKE_KEYS), (f"SMO/{BASE}", b"base")])
        self.assertEqual(self.prepare()[0], 0)

    def test_keys_in_subfolder_and_odd_case(self):
        make_zip(self.zip, [("keys/PROD.KEYS", FAKE_KEYS), (BASE, b"b")])
        self.assertEqual(self.prepare()[0], 0)

    def test_path_traversal_names_are_flattened(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), ("../../evil [0100000000010000].nsp", b"e"),
                            ("/abs/abs [0100000000010000].nsp", b"a"), ("x\\..\\back [0100000000010000].nsp", b"b")])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(p.name for p in (self.dest / "nsp").iterdir()),
                         ["abs [0100000000010000].nsp", "back [0100000000010000].nsp", "evil [0100000000010000].nsp"])
        # nothing was written outside dest
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["dest", "in.zip"])

    def test_duplicate_nsp_names_rejected(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), (f"a/{BASE}", b"1"), (f"b/{BASE}", b"2")])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("share the file name", err)

    def test_missing_or_duplicate_keys_rejected(self):
        make_zip(self.zip, [(BASE, b"b")])
        self.assertEqual(self.prepare()[0], 1)
        make_zip(self.zip, [("a/prod.keys", FAKE_KEYS), ("b/prod.keys", FAKE_KEYS), (BASE, b"b")])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("exactly one prod.keys", err)

    def test_no_nsp_rejected(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS)])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("no .nsp", err)

    def test_wrong_title_rejected_and_unnamed_allowed(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), ("Other [0100ABCDEF000000][v0].nsp", b"o")])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("Wrong game", err)
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), ("whatever.nsp", b"o")])
        rc, out, _ = self.prepare()
        self.assertEqual(rc, 0)
        self.assertIn("warning", out)

    def test_title_id_option(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), ("Other [0100ABCDEF000000][v0].nsp", b"o")])
        self.assertEqual(self.prepare("--title-id", "0100abcdef000000")[0], 0)

    def test_garbage_keys_rejected(self):
        make_zip(self.zip, [("prod.keys", "this is not a keys file\n"), (BASE, b"b")])
        rc, _, err = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("no 'name = hex' lines", err)

    def test_corrupt_zip_rejected(self):
        make_zip(self.zip, [("prod.keys", FAKE_KEYS), (BASE, b"A" * 64)])
        raw = bytearray(self.zip.read_bytes())
        idx = raw.index(b"A" * 64)
        raw[idx + 10] ^= 0xFF  # flip a data byte; CRC must catch it
        self.zip.write_bytes(raw)
        rc, _, err = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("pack_inputs.py", err)

    def test_not_a_zip(self):
        self.zip.write_bytes(b"nope")
        self.assertEqual(self.prepare()[0], 1)


class PackInputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.nsp = self.dir / "nsp"
        self.nsp.mkdir()
        self.keys = self.dir / "prod.keys"
        self.keys.write_text(FAKE_KEYS)
        self.out = self.dir / "out.zip"

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, *extra):
        return run(pack_inputs, ["--nsp-dir", str(self.nsp), "--keys", str(self.keys), "-o", str(self.out), *extra])

    def test_round_trip_with_prepare(self):
        (self.nsp / BASE).write_bytes(b"base")
        (self.nsp / UPD).write_bytes(b"upd")
        rc, out, err = self.pack()
        self.assertEqual(rc, 0, err)
        self.assertNotIn(FAKE_KEY_HEX, out + err)
        self.assertIn("sha256:", out)
        rc, _, err = run(prepare_inputs, [str(self.out), str(self.dir / "dest")])
        self.assertEqual(rc, 0, err)

    def test_warns_without_update(self):
        (self.nsp / BASE).write_bytes(b"base")
        rc, out, _ = self.pack()
        self.assertEqual(rc, 0)
        self.assertIn("no update NSP", out)

    def test_xci_base_game_is_accepted(self):
        (self.nsp / "Game [0100000000010000][v0].xci").write_bytes(b"xci")
        (self.nsp / UPD).write_bytes(b"upd")
        rc, out, err = self.pack()
        self.assertEqual(rc, 0, err)
        self.assertIn("XCI for the base game only", out)
        with zipfile.ZipFile(self.out) as zf:
            self.assertIn("nsp/Game [0100000000010000][v0].xci", zf.namelist())
        rc, _, err = run(prepare_inputs, [str(self.out), str(self.dir / "dest")])
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.dir / "dest" / "nsp" / "Game [0100000000010000][v0].xci").exists())

    def test_compressed_only_gives_hint(self):
        (self.nsp / "Game.nsz").write_bytes(b"x")
        (self.nsp / "Game2.xcz").write_bytes(b"x")
        rc, _, err = self.pack()
        self.assertEqual(rc, 1)
        self.assertIn("decompress", err)

    def test_warns_on_other_update_version(self):
        (self.nsp / BASE).write_bytes(b"base")
        (self.nsp / "Game [0100000000010800][v262144].nsp").write_bytes(b"old")
        rc, out, _ = self.pack()
        self.assertEqual(rc, 0)
        self.assertIn("v262144", out)
        self.assertIn("1.4.1", out)

    def test_no_version_warning_for_expected_update(self):
        (self.nsp / BASE).write_bytes(b"base")
        (self.nsp / UPD).write_bytes(b"upd")
        rc, out, _ = self.pack()
        self.assertEqual(rc, 0)
        self.assertNotIn("warning: Game", out)
        self.assertNotIn("no update NSP", out)

    def test_wrong_game_rejected(self):
        (self.nsp / "Other [0100ABCDEF000000][v0].nsp").write_bytes(b"o")
        self.assertEqual(self.pack()[0], 1)

    def test_bad_keys_rejected(self):
        (self.nsp / BASE).write_bytes(b"b")
        self.keys.write_text("garbage\n")
        self.assertEqual(self.pack()[0], 1)

    def test_refuses_to_overwrite(self):
        (self.nsp / BASE).write_bytes(b"b")
        self.out.write_bytes(b"x")
        self.assertEqual(self.pack()[0], 1)


class CloudBuildArgs(unittest.TestCase):
    def sh(self, **env):
        e = {**os.environ, **env}
        return subprocess.run(["bash", str(ROOT / "scripts" / "cloud_build.sh")], env=e,
                              capture_output=True, text=True, cwd=tempfile.gettempdir())

    def test_rejects_bad_mode(self):
        r = self.sh(MODE="nope")
        self.assertEqual(r.returncode, 2)
        self.assertIn("MODE", r.stderr)

    def test_rejects_option_like_ref(self):
        r = self.sh(NXNATIVE_REF="--upload-pack=evil")
        self.assertEqual(r.returncode, 2)
        self.assertIn("NXNATIVE_REF", r.stderr)

    def test_rejects_bad_title_id(self):
        r = self.sh(TITLE_ID="xyz")
        self.assertEqual(r.returncode, 2)
        self.assertIn("TITLE_ID", r.stderr)

    @unittest.skipIf(sys.platform == "darwin", "checks the non-Mac refusal")
    def test_auto_mode_is_accepted(self):
        r = self.sh(MODE="auto")
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs a Mac", r.stderr)

    @unittest.skipIf(sys.platform == "darwin", "checks the non-Mac refusal")
    def test_refuses_off_mac(self):
        r = self.sh()
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs a Mac", r.stderr)


class PublishReleaseParts(unittest.TestCase):
    def run_script(self, out_dir, bindir, log, **env):
        e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_REPOSITORY": "me/repo",
             "GITHUB_RUN_ID": "123", "PART_BYTES": "1000", "GH_LOG": str(log), **env}
        return subprocess.run(["bash", str(ROOT / "scripts" / "publish_release_parts.sh"), str(out_dir)],
                              env=e, capture_output=True, text=True)

    def make_fake_gh(self, bindir):
        gh = Path(bindir) / "gh"
        # records its arguments and copies the part files it was given, as the real upload would read them
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$GH_LOG"\nfor a in "$@"; do case "$a" in *.part-*) cp "$a" "$GH_LOG.$(basename "$a")";; esac; done\n')
        gh.chmod(0o755)

    def test_splits_publishes_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, bindir, log = tmp / "out", tmp / "bin", tmp / "gh.log"
            out.mkdir()
            bindir.mkdir()
            self.make_fake_gh(bindir)
            data = bytes(range(256)) * 10  # 2560 bytes -> 3 parts of at most 1000
            (out / "Game.ipa").write_bytes(data)
            r = self.run_script(out, bindir, log)
            self.assertEqual(r.returncode, 0, r.stderr)
            args = log.read_text().split("\n")
            self.assertEqual(args[:3], ["release", "create", "ipa-123"])
            self.assertIn("--draft", args)
            self.assertIn("me/repo", args)
            parts = sorted(a for a in args if ".part-" in a)
            self.assertEqual(parts, ["Game.ipa.part-aa", "Game.ipa.part-ab", "Game.ipa.part-ac"])
            joined = b"".join((tmp / f"gh.log.{p}").read_bytes() for p in parts)
            self.assertEqual(joined, data)  # parts rejoin to the original, in order
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["Game.ipa"])  # parts removed afterwards

    def test_diagnostics_release_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, bindir, log = tmp / "out", tmp / "bin", tmp / "gh.log"
            (out / "diagnostics").mkdir(parents=True)
            bindir.mkdir()
            self.make_fake_gh(bindir)
            (out / "diagnostics" / "compile-errors.txt").write_text("x\n")
            r = self.run_script(out, bindir, log)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(log.exists())  # no DIAG_RELEASE: nothing published, and no IPA either
            r = self.run_script(out, bindir, log, DIAG_RELEASE="1")
            self.assertEqual(r.returncode, 0, r.stderr)
            args = log.read_text().split("\n")
            self.assertEqual(args[:3], ["release", "create", "diag-123"])
            self.assertIn("--draft", args)
            self.assertTrue(any(a.endswith("diagnostics.zip") for a in args))

    def test_no_ipa_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out, bindir, log = tmp / "out", tmp / "bin", tmp / "gh.log"
            out.mkdir()
            bindir.mkdir()
            self.make_fake_gh(bindir)
            r = self.run_script(out, bindir, log)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(log.exists())


class HasProfile(unittest.TestCase):
    def check(self, dirs, title_id):
        with tempfile.TemporaryDirectory() as tmp:
            for d in dirs:
                os.makedirs(os.path.join(tmp, "dm", "games", d))
            # a file next to the profiles must never count as one
            if dirs:
                Path(tmp, "dm", "games", "README.md").write_text("x")
            r = subprocess.run(["bash", str(ROOT / "scripts" / "has_profile.sh"), tmp, title_id],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()

    def test_found_exact_and_case_insensitive(self):
        self.assertEqual(self.check(["010015100B514000"], "010015100B514000"), "found")
        self.assertEqual(self.check(["010015100B514000"], "010015100b514000"), "found")

    def test_missing(self):
        self.assertEqual(self.check(["010015100B514000"], "0100000000010000"), "missing")
        self.assertEqual(self.check([], "0100000000010000"), "missing")

    def test_file_named_like_profile_is_not_a_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "dm", "games"))
            Path(tmp, "dm", "games", "0100000000010000").write_text("not a dir")
            r = subprocess.run(["bash", str(ROOT / "scripts" / "has_profile.sh"), tmp, "0100000000010000"],
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), "missing")


METAL_NEW = "Apple metal version 32023.921 (metalfe-32023.921.6)"   # what nxnative's lock was made with
METAL_OLD = "Apple metal version 32023.883 (metalfe-32023.883)"     # what the runner has
METAL_BUILD_SUFFIX = "Apple metal version 32023.921 (metalfe-32023.921.7)"


def metal_text(first_line):
    # like the real `metal --version`: the version is only the first of several lines
    return first_line + "\nTarget: air64-apple-darwin25.0.0\nThread model: posix\nInstalledDir: /somewhere\n"


class PickXcode(unittest.TestCase):
    """scripts/pick_xcode.sh with a fake xcrun that reads <developer dir>/metal-<sdk>.txt."""

    FAKE_XCRUN = (
        "#!/bin/sh\n"
        'if [ "$1" != "-sdk" ] || [ "$3" != "metal" ] || [ "$4" != "--version" ]; then\n'
        '  echo "fake xcrun: unsupported: $*" >&2; exit 64\n'
        "fi\n"
        'dev="${DEVELOPER_DIR:-$FAKE_DEFAULT_DEV}"\n'
        'f="$dev/metal-$2.txt"\n'
        'if [ ! -f "$f" ]; then echo "xcrun: error: unable to find utility \\"metal\\"" >&2; exit 72; fi\n'
        'cat "$f"\n'
    )
    LOCK = f"xlate_source=built\nspirv_cross=d9dc197f061b42a5\nmetal_macosx={METAL_NEW}\nmetal_iphoneos={METAL_NEW}\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        xcrun = self.bin / "xcrun"
        xcrun.write_text(self.FAKE_XCRUN)
        xcrun.chmod(0o755)
        self.search = self.dir / "Applications"
        self.search.mkdir()
        self.default_dev = self.dir / "default-dev"
        self.default_dev.mkdir()
        self.lock = self.dir / "dmsh_chain.lock"
        self.lock.write_text(self.LOCK)
        self.set_metal(self.default_dev, METAL_OLD, METAL_OLD)  # the Xcode in use does not match

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def set_metal(dev, mac, ios):
        """None means that SDK has no working Metal compiler."""
        for sdk, line in (("macosx", mac), ("iphoneos", ios)):
            f = Path(dev) / f"metal-{sdk}.txt"
            if line is None:
                if f.exists():
                    f.unlink()
            else:
                f.write_text(metal_text(line))

    def make_xcode(self, name, mac, ios):
        dev = self.search / name / "Contents" / "Developer"
        dev.mkdir(parents=True)
        self.set_metal(dev, mac, ios)
        return str(dev)

    def pick(self, lock="default", **env):
        e = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "XCODE_SEARCH_DIR": str(self.search),
             "FAKE_DEFAULT_DEV": str(self.default_dev), **env}
        e.pop("DEVELOPER_DIR", None)
        args = [str(self.lock)] if lock == "default" else ([] if lock is None else [str(lock)])
        return subprocess.run(["bash", str(ROOT / "scripts" / "pick_xcode.sh"), *args], env=e,
                              capture_output=True, text=True)

    def assertPicks(self, r, dev):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, dev + "\n")

    def assertNothing(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")

    def test_xcode_in_use_already_matches_prints_nothing(self):
        self.set_metal(self.default_dev, METAL_NEW, METAL_NEW)
        self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_NEW)  # also matches, but must not be chosen
        self.assertNothing(self.pick())

    def test_xcode_in_use_with_only_one_sdk_matching_does_not_count(self):
        self.set_metal(self.default_dev, METAL_NEW, METAL_OLD)
        dev = self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_NEW)
        self.assertPicks(self.pick(), dev)

    def test_picks_the_first_matching_xcode_and_prints_its_developer_dir(self):
        self.make_xcode("Xcode_25.app", METAL_OLD, METAL_OLD)
        first = self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_NEW)
        self.make_xcode("Xcode_26.1.app", METAL_NEW, METAL_NEW)
        (self.search / "Notes.app").mkdir()  # not an Xcode
        self.assertPicks(self.pick(), first)

    def test_both_sdks_must_match(self):
        self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_OLD)   # macosx only
        self.make_xcode("Xcode_26.1.app", METAL_OLD, METAL_NEW)   # iphoneos only
        self.assertNothing(self.pick())
        both = self.make_xcode("Xcode_26.2.app", METAL_NEW, METAL_NEW)
        self.assertPicks(self.pick(), both)

    def test_xcode_without_a_metal_toolchain_is_skipped(self):
        self.make_xcode("Xcode_26.0.app", None, None)             # no working Metal compiler at all
        self.make_xcode("Xcode_26.1.app", METAL_NEW, None)        # no iphoneos Metal compiler
        self.assertNothing(self.pick())
        good = self.make_xcode("Xcode_26.2.app", METAL_NEW, METAL_NEW)
        self.assertPicks(self.pick(), good)

    def test_nothing_matches_prints_nothing(self):
        self.make_xcode("Xcode_25.app", METAL_OLD, METAL_OLD)
        self.assertNothing(self.pick())

    def test_comparison_is_exact(self):
        self.make_xcode("Xcode_26.0.app", METAL_BUILD_SUFFIX, METAL_BUILD_SUFFIX)
        self.assertNothing(self.pick())

    def test_lock_without_the_metal_lines_prints_nothing(self):
        self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_NEW)
        for text in ("spirv_cross=d9dc197f061b42a5\n", f"metal_macosx={METAL_NEW}\n",
                     f"metal_iphoneos={METAL_NEW}\n", "metal_macosx=\nmetal_iphoneos=\n", ""):
            self.lock.write_text(text)
            self.assertNothing(self.pick())

    def test_missing_lock_or_argument_prints_nothing(self):
        self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_NEW)
        self.assertNothing(self.pick(lock=self.dir / "nope.lock"))
        self.assertNothing(self.pick(lock=None))

    def test_missing_search_dir_prints_nothing(self):
        self.assertNothing(self.pick(XCODE_SEARCH_DIR=str(self.dir / "does-not-exist")))

    def test_lock_line_styles(self):
        dev = self.make_xcode("Xcode_26.0.app", METAL_NEW, METAL_NEW)
        for text in (f"metal_macosx: {METAL_NEW}\nmetal_iphoneos: {METAL_NEW}\n",
                     f"metal_macosx = {METAL_NEW}\n  metal_iphoneos = {METAL_NEW}  \n",
                     f"metal_macosx {METAL_NEW}\nmetal_iphoneos {METAL_NEW}\n",
                     f"metal_macosx={METAL_NEW}\r\nmetal_iphoneos={METAL_NEW}\r\n",
                     f"metal_macosx_extra=decoy\nmetal_macosx={METAL_NEW}\nmetal_iphoneos={METAL_NEW}"):
            self.lock.write_text(text)
            self.assertPicks(self.pick(), dev)


STUB_TOOL_LOCK = r"""#!/usr/bin/env python3
# Stand-in for nxnative's dm/gfx/tools/tool_lock.py: same CLI for --check-tools, fake tools.
# FAKE_ACTUAL (file) is "what the runner has" (tab-separated like the lock); FAKE_CALLS (file) logs every call.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = os.path.join(HERE, "dmsh_chain.lock")


def kv(path):
    d = {}
    with open(path) as f:
        for line in f:
            if "\t" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("\t", 1)
                d[k] = v
    return d


def main(argv):
    with open(os.environ["FAKE_CALLS"], "a") as log:
        log.write(" ".join(argv) + " DM_GAME=" + os.environ.get("DM_GAME", "") + "\n")
    if os.environ.get("FAKE_CRASH"):
        raise RuntimeError("the checker fell over")
    if argv != ["--check-tools"]:
        sys.exit("usage: tool_lock.py --check-tools | --update-lock")
    actual, lock = kv(os.environ["FAKE_ACTUAL"]), kv(LOCK)
    bad = ["%s: lock %s / actual %s" % (k, lock[k], actual.get(k, "missing")) for k in lock if lock[k] != actual.get(k)]
    for b in bad:
        print("[RED] translation chain tools do not match the lock file: " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
"""

# before the check moved out of dmsh_chain.py: the same CLI in dmsh_chain.py, which wants a profile to start
STUB_OLD_CHAIN = STUB_TOOL_LOCK.replace(
    'def main(argv):\n',
    'def main(argv):\n    if not os.environ.get("DM_GAME"):\n        print("dmsh_chain: set DM_GAME to the base title ID")\n        return 2\n')

LOCK_AUTHOR = ("dmsh_xlate.dll\tc23076f1647facaf\nspirv-cross\te37945d8e441d34d\n"
               f"metal_macosx\t{METAL_NEW}\nmetal_iphoneos\t{METAL_NEW}\n")
LOCK_RUNNER = ("dmsh_xlate.dll\tc23076f1647facaf\nspirv-cross\te37945d8e441d34d\n"
               f"metal_macosx\t{METAL_OLD}\nmetal_iphoneos\t{METAL_OLD}\n")
SMO = "0100000000010000"


class CheckChainLock(unittest.TestCase):
    """scripts/check_chain_lock.sh against a fake nxnative tree and a stub tool_lock.py. It must only check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.nx = self.dir / "nx"
        self.tools = self.nx / "dm" / "gfx" / "tools"
        self.calls = self.dir / "calls.log"
        self.actual = self.dir / "actual.txt"
        self.report = self.dir / "diag" / "toolchain-lock.txt"  # its folder does not exist yet

    def tearDown(self):
        self.tmp.cleanup()

    def tree(self, checker="tool_lock.py", stub=STUB_TOOL_LOCK, lock=LOCK_AUTHOR, actual=LOCK_AUTHOR):
        self.tools.mkdir(parents=True)
        if checker:
            (self.tools / checker).write_text(stub)
        if lock is not None:
            (self.tools / "dmsh_chain.lock").write_text(lock)
        self.actual.write_text(actual)
        (self.nx / "dm" / "games" / SMO).mkdir(parents=True)
        (self.nx / "dm" / "games" / SMO / "game.tsv").write_text("title\tSMO\n")
        (self.nx / "dm" / "games" / SMO / "keep.txt").write_text("untouched\n")

    def snapshot(self):
        return {str(p.relative_to(self.nx)): p.read_bytes() for p in sorted(self.nx.rglob("*")) if p.is_file()}

    def check(self, title=SMO, nx=None, **env):
        e = {**os.environ, "FAKE_ACTUAL": str(self.actual), "FAKE_CALLS": str(self.calls), **env}
        args = ["bash", str(ROOT / "scripts" / "check_chain_lock.sh"), str(nx or self.nx), str(self.report)]
        if title is not None:
            args.append(title)
        return subprocess.run(args, env=e, capture_output=True, text=True)

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def first_line(self):
        return self.report.read_text().splitlines()[0]

    def run_checked(self, **kw):
        """Run the check and assert it left the checkout exactly as it was"""
        before = self.snapshot()
        r = self.check(**kw)
        self.assertEqual(self.snapshot(), before, "the checkout was changed")
        return r

    def test_match_exits_0_and_changes_nothing(self):
        self.tree()
        r = self.run_checked()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.first_line().startswith("match:"))
        self.assertEqual([c.split()[0] for c in self.called()], ["--check-tools"])

    def test_only_the_metal_compiler_differing_exits_3_and_leaves_the_lock_alone(self):
        self.tree(actual=LOCK_RUNNER)
        r = self.run_checked()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(self.first_line().startswith("metal-only:"))
        text = self.report.read_text()
        self.assertIn("metal_macosx: lock", text)
        self.assertEqual((self.tools / "dmsh_chain.lock").read_text(), LOCK_AUTHOR)
        # the checker is called once, with --check-tools only: no --update-lock, no --header
        self.assertEqual([c.split()[0] for c in self.called()], ["--check-tools"])

    def test_one_metal_sdk_differing_is_still_metal_only(self):
        self.tree(actual=LOCK_AUTHOR.replace(f"metal_iphoneos\t{METAL_NEW}", f"metal_iphoneos\t{METAL_OLD}"))
        r = self.run_checked()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_another_spirv_cross_fails(self):
        self.tree(actual=LOCK_AUTHOR.replace("e37945d8e441d34d", "242d2c694be3ec91"))
        r = self.run_checked()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.first_line().startswith("failed:"))
        self.assertIn("spirv-cross", r.stderr)

    def test_another_translator_fails(self):
        self.tree(actual=LOCK_AUTHOR.replace("c23076f1647facaf", "0000000000000000"))
        self.assertEqual(self.run_checked().returncode, 1)

    def test_metal_plus_another_tool_is_not_metal_only(self):
        self.tree(actual=LOCK_RUNNER.replace("e37945d8e441d34d", "242d2c694be3ec91"))
        r = self.run_checked()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.first_line().startswith("failed:"))

    def test_a_metal_compiler_that_does_not_run_fails(self):
        gone = LOCK_AUTHOR.replace(f"metal_iphoneos\t{METAL_NEW}\n", "")   # the stub reports a tool the runner lacks as "missing"
        self.tree(actual=gone)
        r = self.run_checked()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("actual missing", self.report.read_text())

    def test_a_checker_that_crashes_fails_loudly(self):
        self.tree()
        r = self.run_checked(FAKE_CRASH="1")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.first_line().startswith("failed:"))
        self.assertIn("fell over", self.report.read_text())

    def test_no_lock_is_skipped(self):
        self.tree(lock=None)
        r = self.run_checked()
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.first_line().startswith("skipped:"))
        self.assertEqual(self.called(), [])

    def test_no_checker_is_skipped(self):
        self.tree(checker=None)
        r = self.run_checked()
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.first_line().startswith("skipped:"))

    def test_a_dmsh_chain_without_the_check_is_skipped(self):
        self.tree(checker="dmsh_chain.py", stub="print('no lock check here')\n")
        r = self.run_checked()
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.first_line().startswith("skipped:"))

    def test_older_nxnative_with_the_check_in_dmsh_chain_uses_it_with_the_profile(self):
        self.tree(checker="dmsh_chain.py", stub=STUB_OLD_CHAIN, actual=LOCK_RUNNER)
        r = self.run_checked()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.called(), [f"--check-tools DM_GAME={SMO}"])

    def test_missing_checkout_is_skipped(self):
        r = self.check(nx=self.dir / "nowhere")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.first_line().startswith("skipped:"))

    def test_tool_lock_is_preferred_over_dmsh_chain(self):
        self.tree()
        (self.tools / "dmsh_chain.py").write_text("raise SystemExit('must not run')\n")
        r = self.run_checked()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_title_id_is_optional(self):
        self.tree()
        r = self.run_checked(title=None)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_script_has_no_way_to_write_the_lock(self):
        text = (ROOT / "scripts" / "check_chain_lock.sh").read_text()
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("--update-lock", code)
        self.assertNotIn("--header", code)
        self.assertNotIn("sed -i", code)


class CloudBuildToolLock(unittest.TestCase):
    text = (ROOT / "scripts" / "cloud_build.sh").read_text()

    def test_no_sed_patch_of_nxnative(self):
        self.assertNotIn("sed -i", self.text)
        self.assertNotIn("FORCE TOOLCHAIN VERSION OVERRIDE", self.text)
        self.assertNotIn("Bypassing lock validation", self.text)

    def test_the_lock_is_only_checked_never_rewritten(self):
        self.assertFalse((ROOT / "scripts" / "sync_chain_lock.sh").exists())
        self.assertNotIn("sync_chain_lock", self.text)
        self.assertNotIn("--update-lock", self.text)

    def test_calls_both_scripts_with_bash_in_build_mode_before_nxnative_runs(self):
        pick = re.search(r'xcode_dev="\$\(bash "\$REPO_ROOT/scripts/pick_xcode\.sh" "\$NX_DIR/dm/gfx/tools/dmsh_chain\.lock"\)"',
                         self.text)
        check = re.search(r'^\s*bash "\$REPO_ROOT/scripts/check_chain_lock\.sh" "\$NX_DIR" '
                          r'"\$OUT_DIR/diagnostics/toolchain-lock\.txt" "\$TITLE_ID" \|\| lock_rc=\$\?$', self.text, re.M)
        self.assertTrue(pick, "pick_xcode.sh is not called with bash")
        self.assertTrue(check, "check_chain_lock.sh is not called with bash")
        self.assertIn('export DEVELOPER_DIR="$xcode_dev"', self.text)
        run_nxnative = self.text.index("build_ipa_from_nsp.py")
        self.assertLess(pick.start(), check.start())
        self.assertLess(check.start(), run_nxnative)
        # only when MODE=build: the closest `if` above the call is the MODE check
        self.assertTrue(self.text[:pick.start()].rsplit("\nif ", 1)[1].startswith('[[ "$MODE" == "build" ]]'))

    def test_another_metal_compiler_stops_the_build_unless_it_was_allowed(self):
        i = self.text.index("lock_rc -eq 3")
        block = self.text[i:self.text.index("# 5. Run nxnative")]
        self.assertIn('"$ALLOW_OTHER_METAL" == "1"', block)
        self.assertIn("exit 1", block)
        self.assertIn('ALLOW_OTHER_METAL="${ALLOW_OTHER_METAL:-0}"', self.text)   # off by default
        # the flag reaches nxnative only through the variable the allowed branch sets
        self.assertEqual(self.text.count("args+=(--allow-other-metal)"), 1)
        self.assertRegex(self.text, r'\[\[ "\$allow_other_metal_arg" == "1" \]\] && args\+=\(--allow-other-metal\)')
        self.assertLess(self.text.index("allow_other_metal_arg=1"), self.text.index("args+=(--allow-other-metal)"))

    def test_any_other_mismatch_stops_the_build(self):
        self.assertRegex(self.text, r'elif \[\[ \$lock_rc -ne 0 \]\]; then\n\s+exit "\$lock_rc"')

    def test_prerequisites_are_the_ones_nxnative_lists(self):
        brew = [l for l in self.text.splitlines() if l.startswith("brew install xcodegen")]
        self.assertEqual(len(brew), 1)
        self.assertIn("glslang", brew[0])
        self.assertNotIn("spirv-cross", brew[0])   # nxnative's own, pinned by its lock
        pip = [l for l in self.text.splitlines() if "pip install" in l]
        self.assertEqual(len(pip), 1)
        for pkg in ("lz4", "capstone", "fonttools", "nsz", "zbic", "backports.zstd"):
            self.assertIn(pkg, pip[0])


class OdysseyPatch(unittest.TestCase):
    """The patches folder holds a layout patch for the updated NXNATIVE-1.43.1 and nothing that rewrites memory management."""

    def patches(self):
        return sorted((ROOT / "patches").glob("*.patch"))

    def test_the_folder_has_exactly_the_layout_patch(self):
        self.assertEqual([p.name for p in self.patches()], ["odyssey-touch-layout.patch"])

    def test_it_parses_and_touches_only_the_gamepad(self):
        for p in self.patches():
            r = subprocess.run(["git", "apply", "--numstat", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            files = [line.split("\t")[2] for line in r.stdout.splitlines()]
            self.assertEqual(files, ["dm/ios/Sources/DmGamepad.m"])

    def test_it_does_not_touch_the_command_segment_pool(self):
        text = (ROOT / "patches" / "odyssey-touch-layout.patch").read_text()
        for word in ("hostseg", "HOSTSEG", "nvn_mtl", "hle_nvn"):
            self.assertNotIn(word, text)

    def test_the_layout_cycle_and_the_saved_modes_agree_with_nxnative(self):
        text = (ROOT / "patches" / "odyssey-touch-layout.patch").read_text()
        # 0 = 2D, 1 = 3D, 2 = Tap (nxnative's numbers), 3 = OD; the saved key is nxnative's own, so a saved choice keeps its meaning
        self.assertIn("0 = 2D, 1 = 3D, 2 = Tap (DM_GAME_PAD_LAYOUT's numbers), 3 = OD", text)
        self.assertNotIn("DmPadLayoutMode", text)
        self.assertIn("int l = _od ? 0 : _tap ? 3 : _full ? (dm_opmode() == 0 ? 2 : 3) : 1;", text)


class ApplyPatches(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.nx = self.tmp / "nx"
        self.nx.mkdir()
        (self.nx / "a.txt").write_text("one\n")
        self.pdir = self.tmp / "patches"
        self.pdir.mkdir()
        self.report = self.tmp / "out" / "patches.txt"
        subprocess.run(["git", "init", "-q", str(self.nx)], check=True)
        subprocess.run(["git", "-C", str(self.nx), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.nx), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "x"], check=True)
        (self.nx / "a.txt").write_text("two\n")
        self.diff = subprocess.run(["git", "-C", str(self.nx), "diff"], capture_output=True,
                                   text=True, check=True).stdout
        subprocess.run(["git", "-C", str(self.nx), "checkout", "-q", "a.txt"], check=True)

    def run_script(self):
        return subprocess.run(["bash", str(ROOT / "scripts" / "apply_patches.sh"), str(self.nx),
                               str(self.pdir), str(self.report)], capture_output=True, text=True)

    def test_no_patches_is_fine(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0)
        self.assertIn("no patches", self.report.read_text())

    def test_applies_then_skips_when_already_applied(self):
        (self.pdir / "a.patch").write_text(self.diff)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.nx / "a.txt").read_text(), "two\n")
        self.assertIn("applied (-p1): a.patch", self.report.read_text())   # the script says how many path components it stripped
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already applied", self.report.read_text())

    def test_patch_that_does_not_apply_fails(self):
        (self.pdir / "a.patch").write_text(self.diff)
        (self.nx / "a.txt").write_text("something else\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED: a.patch", self.report.read_text())


class AspectScan(unittest.TestCase):
    def test_skips_without_the_tool_and_never_fails(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        rep = tmp / "r.txt"
        r = subprocess.run(["bash", str(ROOT / "scripts" / "aspect_scan.sh"), str(tmp), "1.43",
                            str(rep), str(tmp)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped", rep.read_text())

    def test_reports_when_no_nso_is_found(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "dm" / "tools").mkdir(parents=True)
        (tmp / "dm" / "tools" / "aspect_scan.py").write_text("print('x')\n")
        rep = tmp / "r.txt"
        r = subprocess.run(["bash", str(ROOT / "scripts" / "aspect_scan.sh"), str(tmp), "1.43",
                            str(rep), str(tmp / "empty")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no extracted", rep.read_text())
