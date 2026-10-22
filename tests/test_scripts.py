"""Tests for the input packing/unpacking scripts. Uses tiny synthetic files only."""
import contextlib
import io
import hashlib
import os
import re
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


STUB_CHAIN = r"""#!/usr/bin/env python3
# Stand-in for nxnative's dm/gfx/tools/dmsh_chain.py: same CLI, fake tools.
# FAKE_ACTUAL (file) is "what the runner has"; FAKE_CALLS (file) logs every call.
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = os.path.join(HERE, "dmsh_chain.lock")
GAMES = os.path.join(HERE, "..", "..", "games")


def _kv(path):
    d = {}
    with open(path) as f:
        for line in f:
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                d[k] = v
    return d


def version():
    with open(LOCK, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def main(argv):
    game = os.environ.get("DM_GAME")
    if not game:
        print("dmsh_chain: set DM_GAME to the base title ID")
        return 2
    if not os.path.isdir(os.path.join(GAMES, game)):
        print("dmsh_chain: no profile " + game)
        return 2
    cmd = argv[0] if argv else ""
    with open(os.environ["FAKE_CALLS"], "a") as log:
        log.write(cmd + " DM_GAME=" + game + "\n")
    if cmd == "--check-tools":
        actual, lock = _kv(os.environ["FAKE_ACTUAL"]), _kv(LOCK)
        bad = [k for k in lock if lock[k] != actual.get(k)]
        for k in bad:
            print("[RED] translation chain tools do not match the lock file: %s: lock %s / actual %s"
                  % (k, lock[k], actual.get(k)))
        if not bad:
            print("tools match the lock file")
        return 1 if bad else 0
    if cmd == "--update-lock":
        if os.environ.get("FAKE_REFUSE"):
            print("[RED] the translator was not built from source: refusing to write the lock")
            return 1
        if not os.environ.get("FAKE_NOOP_UPDATE"):
            with open(os.environ["FAKE_ACTUAL"]) as src, open(LOCK, "w") as dst:
                dst.write(src.read())
        print("lock updated")
        return 0
    if cmd == "--header":
        if os.environ.get("FAKE_FAIL_HEADER"):
            print("[RED] cannot write the header")
            return 1
        with open(os.path.join(GAMES, game, "dmsh_chain.h"), "w") as f:
            f.write('#define DMSH_CHAIN_VERSION "%s"\n' % version())
        print("header written")
        return 0
    print("usage: dmsh_chain.py --check-tools | --update-lock | --header")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
"""

LOCK_AUTHOR = (f"xlate_source=built-from-source\nspirv_cross=d9dc197f061b42a5\n"
               f"metal_macosx={METAL_NEW}\nmetal_iphoneos={METAL_NEW}\n")
LOCK_RUNNER = (f"xlate_source=built-from-source\nspirv_cross=242d2c694be3ec91\n"
               f"metal_macosx={METAL_OLD}\nmetal_iphoneos={METAL_OLD}\n")
SMO = "0100000000010000"


class SyncChainLock(unittest.TestCase):
    """scripts/sync_chain_lock.sh against a fake nxnative tree and a stub dmsh_chain.py."""

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

    def fresh(self):
        """Start over with an empty scratch dir (for loops over several fake trees in one test)."""
        self.tearDown()
        self.setUp()

    def tree(self, profiles=(SMO,), chain=True, lock=LOCK_AUTHOR, actual=LOCK_RUNNER, games=True):
        """profiles: names (with a game.tsv) or (name, False) for a folder without game.tsv."""
        self.tools.mkdir(parents=True)
        if chain:
            (self.tools / "dmsh_chain.py").write_text(STUB_CHAIN)
        if lock is not None:
            (self.tools / "dmsh_chain.lock").write_text(lock)
        self.actual.write_text(actual)
        if games:
            (self.nx / "dm" / "games").mkdir(parents=True)
        for prof in profiles:
            name, has_tsv = (prof, True) if isinstance(prof, str) else prof
            d = self.nx / "dm" / "games" / name
            d.mkdir(parents=True)
            if has_tsv:
                (d / "game.tsv").write_text("title\t" + name + "\n")
            (d / "dmsh_chain.h").write_text('#define DMSH_CHAIN_VERSION "stale-%s"\n' % name)

    def sync(self, title=SMO, nx=None, **env):
        e = {**os.environ, "FAKE_ACTUAL": str(self.actual), "FAKE_CALLS": str(self.calls), **env}
        return subprocess.run(["bash", str(ROOT / "scripts" / "sync_chain_lock.sh"), str(nx or self.nx), title,
                               str(self.report)], env=e, capture_output=True, text=True)

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def flags(self):
        return [c.split()[0] for c in self.called()]

    def lock_text(self):
        return (self.tools / "dmsh_chain.lock").read_text()

    def header(self, name):
        return (self.nx / "dm" / "games" / name / "dmsh_chain.h").read_text()

    @staticmethod
    def version_of(text):
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def test_match_changes_nothing(self):
        self.tree(lock=LOCK_RUNNER)
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.report.read_text().startswith("match:"))
        self.assertEqual(self.flags(), ["--check-tools"])
        self.assertEqual(self.lock_text(), LOCK_RUNNER)
        self.assertEqual(self.header(SMO), '#define DMSH_CHAIN_VERSION "stale-%s"\n' % SMO)

    def test_mismatch_rewrites_lock_and_header_of_the_target_profile_only(self):
        other = "010015100B514000"
        self.tree(profiles=(other, SMO))
        before_other = [(self.nx / "dm" / "games" / other / n).read_bytes() for n in ("game.tsv", "dmsh_chain.h")]
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.flags(), ["--check-tools", "--update-lock", "--header", "--check-tools"])
        self.assertTrue(all(c.endswith("DM_GAME=" + SMO) for c in self.called()))
        self.assertEqual(self.lock_text(), LOCK_RUNNER)
        new_version = self.version_of(LOCK_RUNNER)
        self.assertEqual(self.header(SMO), '#define DMSH_CHAIN_VERSION "%s"\n' % new_version)
        after_other = [(self.nx / "dm" / "games" / other / n).read_bytes() for n in ("game.tsv", "dmsh_chain.h")]
        self.assertEqual(before_other, after_other)
        rep = self.report.read_text()
        self.assertTrue(rep.startswith("re-baselined:"), rep)
        self.assertIn("what differed:", rep)
        self.assertIn("spirv_cross: lock d9dc197f061b42a5 / actual 242d2c694be3ec91", rep)
        self.assertIn("lock before:\n" + LOCK_AUTHOR.rstrip("\n"), rep)
        self.assertIn("lock after:\n" + LOCK_RUNNER.rstrip("\n"), rep)
        self.assertIn("chain version: " + new_version, rep)

    def test_title_id_matches_case_insensitively(self):
        folder = "0100ABCDEF000000"
        self.tree(profiles=("0100000000010000", folder))   # the first profile sorts before the match
        r = self.sync(title="0100abcdef000000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.flags(), ["--check-tools", "--update-lock", "--header", "--check-tools"])
        self.assertTrue(all(c.endswith("DM_GAME=" + folder) for c in self.called()), self.called())
        self.assertEqual(self.header(folder), '#define DMSH_CHAIN_VERSION "%s"\n' % self.version_of(LOCK_RUNNER))
        self.assertEqual(self.header("0100000000010000"), '#define DMSH_CHAIN_VERSION "stale-0100000000010000"\n')

    def test_no_matching_profile_rewrites_the_lock_but_writes_no_header(self):
        other = "010015100B514000"
        self.tree(profiles=(other,))
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.flags(), ["--check-tools", "--update-lock", "--check-tools"])
        self.assertTrue(all(c.endswith("DM_GAME=" + other) for c in self.called()))
        self.assertEqual(self.lock_text(), LOCK_RUNNER)
        self.assertEqual(self.header(other), '#define DMSH_CHAIN_VERSION "stale-%s"\n' % other)
        rep = self.report.read_text()
        self.assertTrue(rep.startswith("re-baselined:"), rep)
        self.assertIn("no header", rep.splitlines()[0])

    def test_translator_refusal_fails_loudly_and_leaves_the_lock_alone(self):
        self.tree()
        r = self.sync(FAKE_REFUSE="1")
        self.assertEqual(r.returncode, 1)
        rep = self.report.read_text()
        self.assertTrue(rep.startswith("failed:"), rep)
        self.assertIn("not built from source", rep)
        self.assertIn("not built from source", r.stderr)
        self.assertEqual(self.flags(), ["--check-tools", "--update-lock"])
        self.assertEqual(self.lock_text(), LOCK_AUTHOR)
        self.assertEqual(self.header(SMO), '#define DMSH_CHAIN_VERSION "stale-%s"\n' % SMO)

    def test_still_mismatching_after_update_fails(self):
        self.tree()
        r = self.sync(FAKE_NOOP_UPDATE="1")
        self.assertEqual(r.returncode, 1)
        rep = self.report.read_text()
        self.assertTrue(rep.startswith("failed:"), rep)
        self.assertIn("still do not match", rep.splitlines()[0])
        self.assertIn("still do not match", r.stderr)
        self.assertEqual(self.flags(), ["--check-tools", "--update-lock", "--header", "--check-tools"])

    def test_header_failure_fails(self):
        self.tree()
        r = self.sync(FAKE_FAIL_HEADER="1")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.report.read_text().startswith("failed:"))
        self.assertIn("cannot write the header", r.stderr)

    def test_no_lock_mechanism_is_skipped(self):
        for kw in ({"chain": False}, {"lock": None}, {"chain": False, "lock": None}):
            with self.subTest(**kw):
                self.fresh()
                self.tree(**kw)
                r = self.sync()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.report.read_text().startswith("skipped:"))
                self.assertEqual(self.called(), [])
        self.fresh()
        r = self.sync(nx=self.dir / "no-such-checkout")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.report.read_text().startswith("skipped:"))

    def test_no_profiles_is_skipped(self):
        for kw in ({"profiles": ()}, {"profiles": (("0100000000010000", False),)}, {"profiles": (), "games": False}):
            with self.subTest(**kw):
                self.fresh()
                self.tree(**kw)
                r = self.sync()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.report.read_text().startswith("skipped:"))
                self.assertEqual(self.called(), [])
                self.assertEqual(self.lock_text(), LOCK_AUTHOR)

    def test_a_profile_without_game_tsv_is_not_used(self):
        self.tree(profiles=((SMO, False), "010015100B514000"))   # same ID but no game.tsv
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.flags(), ["--check-tools", "--update-lock", "--check-tools"])  # no header
        self.assertEqual(self.header(SMO), '#define DMSH_CHAIN_VERSION "stale-%s"\n' % SMO)


class CloudBuildToolLock(unittest.TestCase):
    text = (ROOT / "scripts" / "cloud_build.sh").read_text()

    def test_no_sed_patch_of_nxnative(self):
        self.assertNotIn("sed -i", self.text)
        self.assertNotIn("FORCE TOOLCHAIN VERSION OVERRIDE", self.text)
        self.assertNotIn("Bypassing lock validation", self.text)

    def test_calls_both_scripts_with_bash_in_build_mode_before_nxnative_runs(self):
        pick = re.search(r'xcode_dev="\$\(bash "\$REPO_ROOT/scripts/pick_xcode\.sh" "\$NX_DIR/dm/gfx/tools/dmsh_chain\.lock"\)"',
                         self.text)
        sync = re.search(r'^\s*bash "\$REPO_ROOT/scripts/sync_chain_lock\.sh" "\$NX_DIR" "\$TITLE_ID" '
                         r'"\$OUT_DIR/diagnostics/toolchain-lock\.txt"$', self.text, re.M)
        self.assertTrue(pick, "pick_xcode.sh is not called with bash")
        self.assertTrue(sync, "sync_chain_lock.sh is not called with bash")
        self.assertIn('export DEVELOPER_DIR="$xcode_dev"', self.text)
        run_nxnative = self.text.index("build_ipa_from_nsp.py")
        self.assertLess(pick.start(), sync.start())
        self.assertLess(sync.start(), run_nxnative)
        # only when MODE=build: the closest `if` above the call is the MODE check
        self.assertTrue(self.text[:pick.start()].rsplit("\nif ", 1)[1].startswith('[[ "$MODE" == "build" ]]'))


if __name__ == "__main__":
    unittest.main()
