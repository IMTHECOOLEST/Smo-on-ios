"""Tests for the input packing/unpacking scripts. Uses tiny synthetic files only."""
import contextlib
import io
import os
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


if __name__ == "__main__":
    unittest.main()
