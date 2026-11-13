"""Input integrity, isolated extraction, and pinned offline Git source tests."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inputs


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def archive(self, members=None):
        archive = self.root / "source.tar.xz"
        with tarfile.open(archive, "w:xz") as output:
            if members is None:
                member = tarfile.TarInfo("upstream/hello.c")
                payload = b"int hello(void) { return 1; }\n"
                member.size = len(payload)
                output.addfile(member, io.BytesIO(payload))
            else:
                for member in members:
                    output.addfile(member)
        entry = {"filename": archive.name, "sha256": inputs.digest(archive),
                 "extract_to": "sources", "top_directory": "upstream"}
        return archive, entry

    def test_correct_source_extracts_and_can_be_prepared_again(self):
        archive, entry = self.archive()
        source = inputs.extract_archive(archive, entry, self.root)
        self.assertEqual((source / "hello.c").read_text(), "int hello(void) { return 1; }\n")
        self.assertEqual(source, inputs.extract_archive(archive, entry, self.root))

    def test_corrupted_archive_never_extracts(self):
        archive, entry = self.archive()
        archive.write_bytes(archive.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            inputs.extract_archive(archive, entry, self.root)
        self.assertFalse((self.root / "sources/upstream").exists())

    def test_traversal_member_cannot_write_outside_source(self):
        member = tarfile.TarInfo("upstream/../escape")
        archive, entry = self.archive([member])
        with self.assertRaisesRegex(ValueError, "Unexpected source archive path"):
            inputs.extract_archive(archive, entry, self.root)
        self.assertFalse((self.root / "sources/escape").exists())
        self.assertFalse((self.root / "sources/upstream").exists())

    def test_outside_symlink_is_rejected_by_data_filter(self):
        member = tarfile.TarInfo("upstream/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../escape"
        archive, entry = self.archive([member])
        with self.assertRaises(tarfile.FilterError):
            inputs.extract_archive(archive, entry, self.root)
        self.assertFalse((self.root / "sources/upstream").exists())

    def test_preexisting_unverified_source_is_not_silently_reused(self):
        archive, entry = self.archive()
        (self.root / "sources/upstream").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "unverified existing source"):
            inputs.extract_archive(archive, entry, self.root)

    def test_archive_top_directory_cannot_be_a_parent_path(self):
        archive, entry = self.archive()
        entry["top_directory"] = "../upstream"
        with self.assertRaisesRegex(ValueError, "top_directory"):
            inputs.extract_archive(archive, entry, self.root)

    def test_input_destination_cannot_follow_symlink_outside_clone(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        (self.root / "sources").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes the clone"):
            inputs.local_path(self.root, "sources/input.tar.xz")

    def test_offline_missing_input_does_not_attempt_network(self):
        entry = {"filename": "input.tar.xz", "sha256": "0" * 64,
                 "destination": "downloads/input.tar.xz", "url": "https://example.invalid/input"}
        with mock.patch.object(inputs.urllib.request, "urlopen") as network:
            with self.assertRaisesRegex(FileNotFoundError, "Offline input missing"):
                inputs.fetch_archive(entry, self.root, None, offline=True)
            network.assert_not_called()

    def test_verified_original_archive_cache_is_copied_without_network(self):
        cache = self.root / "cache"
        cache.mkdir()
        cached = cache / "input.tar.xz"
        cached.write_bytes(b"original archive bytes")
        entry = {"filename": cached.name, "sha256": inputs.digest(cached),
                 "destination": "downloads/input.tar.xz", "url": "https://example.invalid/input"}
        with mock.patch.object(inputs.urllib.request, "urlopen") as network:
            result = inputs.fetch_archive(entry, self.root, cache, offline=True)
            self.assertEqual(result.read_bytes(), cached.read_bytes())
            self.assertNotEqual(result.stat().st_ino, cached.stat().st_ino)
            network.assert_not_called()

    def test_bad_cache_is_rejected_before_copy(self):
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "input.tar.xz").write_bytes(b"bad bytes")
        entry = {"filename": "input.tar.xz", "sha256": "0" * 64,
                 "destination": "downloads/input.tar.xz", "url": "https://example.invalid/input"}
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            inputs.fetch_archive(entry, self.root, cache, offline=True)
        self.assertFalse((self.root / entry["destination"]).exists())


class GitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original = self.root / "original"
        self.original.mkdir()
        subprocess.run(["git", "init", "-q", str(self.original)], check=True)
        for key, value in [("user.name", "Input Test"), ("user.email", "input@example.invalid")]:
            subprocess.run(["git", "-C", str(self.original), "config", key, value], check=True)
        (self.original / "hello.c").write_text("int hello(void) { return 1; }\n")
        subprocess.run(["git", "-C", str(self.original), "add", "hello.c"], check=True)
        subprocess.run(["git", "-C", str(self.original), "commit", "-qm", "Source fixture"], check=True)
        self.commit = inputs.git_output(self.original, "rev-parse", "HEAD")
        self.entry = {"destination": "sources/source", "commit": self.commit,
                      "url": "https://example.invalid/source.git"}

    def test_offline_bundle_restores_only_pinned_git_source(self):
        cache = self.root / "cache"
        cache.mkdir()
        bundle = cache / f"source-{self.commit}.bundle"
        subprocess.run(["git", "-C", str(self.original), "bundle", "create", str(bundle), "HEAD"], check=True)
        checkout = inputs.prepare_git("source", self.entry, self.root, cache, offline=True)
        self.assertEqual(inputs.git_output(checkout, "rev-parse", "HEAD"), self.commit)
        self.assertEqual((checkout / "hello.c").read_bytes(), (self.original / "hello.c").read_bytes())
        self.assertEqual(inputs.git_output(checkout, "remote", "get-url", "origin"), self.entry["url"])

    def test_modified_pinned_source_is_rejected(self):
        (self.original / "hello.c").write_text("modified source\n")
        with self.assertRaisesRegex(ValueError, "Tracked upstream source changes"):
            inputs.verify_git(self.original, self.commit)

    def test_wrong_commit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Wrong source commit"):
            inputs.verify_git(self.original, "0" * 40)


if __name__ == "__main__":
    unittest.main()
