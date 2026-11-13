"""Source preservation must prove reconstruction before cleanup may delete."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preservation


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = self.root / "private"

    def archive(self, rows=None):
        archive = self.root / "upstream.tar.xz"
        if rows is None:
            rows = [("upstream/hello.c", b"original source\n", 0o664),
                    ("upstream/script", b"#!/bin/sh\nexit 0\n", 0o775),
                    ("upstream/fixtures/program", b"\x7fELF\x00binary source fixture", 0o755),
                    ("upstream/deleted.c", b"delete me\n", 0o644)]
        with tarfile.open(archive, "w:xz") as output:
            for name, data, mode in rows:
                member = tarfile.TarInfo(name)
                member.mode, member.size = mode, len(data)
                output.addfile(member, io.BytesIO(data))
        tree = self.root / "source"
        with tarfile.open(archive) as source:
            source.extractall(self.root / "unpack", filter="data")
        (self.root / "unpack/upstream").rename(tree)
        return tree, archive, preservation._digest(archive)

    def record(self, result):
        return json.loads(Path(result["manifest"]).read_text())

    def assert_same_tree(self, first, second, skip=()):
        self.assertEqual(preservation._scan(first, skip)[0], preservation._scan(second, skip)[0])


class PreservationTests(Fixture):
    def test_tar_roundtrip_preserves_all_bytes_types_modes_and_deletions(self):
        tree, archive, digest = self.archive()
        (tree / "hello.c").write_bytes(b"changed source\x00with literal binary\n")
        (tree / "hello.c").chmod(0o600)
        (tree / "script").chmod(0o700)
        (tree / "deleted.c").unlink()
        (tree / "new/empty").mkdir(parents=True)
        (tree / "new/source.bin").write_bytes(b"\x00unpublished binary fixture\xff")
        (tree / "new/source.bin").chmod(0o640)
        (tree / "new/link").symlink_to("../hello.c")
        (tree / "new/external-link").symlink_to("../../outside")
        (tree / "new").chmod(0o700)
        tree.chmod(0o700)
        result = preservation.capture_tar_tree(self.root, tree, archive, digest, self.store)
        self.assertTrue(result["verified"])
        self.assertTrue(preservation.snapshot_matches_tree(result, tree))
        record = self.record(result)
        self.assertNotIn("fixtures/program", record["changes"])
        self.assertNotIn("blob", record["changes"]["script"])
        restored = preservation.restore_snapshot(result, self.root / "restored")
        self.assert_same_tree(tree, restored)
        self.assertTrue((tree / "hello.c").exists())

    def test_mode_only_changes_do_not_duplicate_upstream_bytes(self):
        tree, archive, digest = self.archive()
        for path in tree.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        tree.chmod(0o700)
        result = preservation.capture_tar_tree(self.root, tree, archive, digest, self.store)
        self.assertFalse((self.store / "blobs").exists())
        restored = preservation.restore_snapshot(result, self.root / "restored")
        self.assert_same_tree(tree, restored)

    def test_deleted_directory_and_replaced_object_types_restore(self):
        tree, archive, digest = self.archive()
        shutil.rmtree(tree / "fixtures")
        (tree / "fixtures").write_bytes(b"directory replaced by authored data")
        (tree / "hello.c").unlink()
        (tree / "hello.c").symlink_to("script")
        (tree / "deleted.c").unlink()
        (tree / "deleted.c/empty").mkdir(parents=True)
        (tree / "deleted.c/new.c").write_text("file replaced by directory\n")
        result = preservation.capture_tar_tree(self.root, tree, archive, digest, self.store)
        self.assert_same_tree(tree, preservation.restore_snapshot(result, self.root / "restored"))

    def test_archive_hardlinks_and_internal_symlinks_are_reconstructible(self):
        tree, archive, digest = self.archive()
        with tarfile.open(archive, "w:xz") as output:
            payload = b"upstream alias contents\n"
            member = tarfile.TarInfo("upstream/file")
            member.mode, member.size = 0o664, len(payload)
            output.addfile(member, io.BytesIO(payload))
            member = tarfile.TarInfo("upstream/hardlink")
            member.type, member.linkname, member.mode = tarfile.LNKTYPE, "upstream/file", 0o664
            output.addfile(member)
            member = tarfile.TarInfo("upstream/symlink")
            member.type, member.linkname = tarfile.SYMTYPE, "file"
            output.addfile(member)
        shutil.rmtree(tree)
        with tarfile.open(archive) as source:
            source.extractall(self.root / "unpack", filter="data")
        (self.root / "unpack/upstream").rename(tree)
        result = preservation.capture_tar_tree(self.root, tree, archive, preservation._digest(archive), self.store)
        self.assert_same_tree(tree, preservation.restore_snapshot(result, self.root / "restored"))

    def test_repeated_unknown_bytes_are_deduplicated_and_ignored_files_preserved(self):
        tree = self.root / "source"
        tree.mkdir()
        (tree / "a").write_bytes(b"same unpublished bytes")
        (tree / "b").write_bytes(b"same unpublished bytes")
        (tree / ".gitignore").write_text("a\nb\n")
        first = preservation.capture_tree(self.root, tree, self.store)
        second = preservation.capture_tree(self.root, tree, self.store)
        blobs = list((self.store / "blobs").iterdir())
        self.assertEqual(len(blobs), 2)
        self.assert_same_tree(tree, preservation.restore_snapshot(second, self.root / "restored"))
        self.assertTrue(preservation.verify_snapshot(first)["verified"])

    def test_generated_exclusions_are_explicit_and_do_not_capture_binaries(self):
        tree, archive, digest = self.archive()
        (tree / "cache").mkdir()
        (tree / "cache/build.o").write_bytes(b"\x7fELF generated object")
        (tree / "unknown.o").write_bytes(b"hand authored fixture despite suffix")

        def policy(name, descriptor):
            return "known compiler cache" if name == "cache" or name.startswith("cache/") else None

        result = preservation.capture_tar_tree(self.root, tree, archive, digest, self.store,
                                               exclude_generated=policy)
        record = self.record(result)
        self.assertEqual(set(record["exclusions"]), {"cache", "cache/build.o"})
        restored = preservation.restore_snapshot(result, self.root / "restored")
        self.assertFalse((restored / "cache").exists())
        self.assertEqual((restored / "unknown.o").read_bytes(), (tree / "unknown.o").read_bytes())
        self.assertEqual((restored / "fixtures/program").read_bytes(), (tree / "fixtures/program").read_bytes())
        (tree / "cache/build.o").write_bytes(b"different generated object")
        self.assertFalse(preservation.snapshot_matches_tree(result, tree))

    def test_changed_upstream_fixture_is_preserved_even_if_policy_calls_it_generated(self):
        tree, archive, digest = self.archive()
        changed = b"\x7fELF unpublished edits to upstream fixture\x00"
        (tree / "fixtures/program").write_bytes(changed)
        result = preservation.capture_tar_tree(
            self.root, tree, archive, digest, self.store,
            exclude_generated=lambda name, entry: "ELF output" if name == "fixtures/program" else None)
        self.assertNotIn("fixtures/program", result["exclusions"])
        restored = preservation.restore_snapshot(result, self.root / "restored")
        self.assertEqual((restored / "fixtures/program").read_bytes(), changed)

    def test_automatic_run_directories_share_delta_bytes(self):
        tree, archive, digest = self.archive()
        (tree / "hello.c").write_text("unpublished shared change\n")
        automatic = self.root / "development/source-preservation/auto"
        first = preservation.capture_tar_tree(self.root, tree, archive, digest, automatic / "run-one")
        second = preservation.capture_tar_tree(self.root, tree, archive, digest, automatic / "run-two")
        self.assertEqual(len(list((automatic / "blobs").iterdir())), 1)
        self.assertEqual(self.record(first)["content_store"], self.record(second)["content_store"])
        self.assert_same_tree(tree, preservation.restore_snapshot(second, self.root / "restored"))

    def test_invalid_exclusion_keeps_original_and_refuses_snapshot(self):
        tree = self.root / "source"
        (tree / "cache").mkdir(parents=True)
        (tree / "cache/unknown.c").write_text("keep this")
        with self.assertRaisesRegex(ValueError, "parent"):
            preservation.capture_tree(self.root, tree, self.store,
                                      exclude_generated=lambda name, entry: "cache" if name == "cache" else None)
        self.assertEqual((tree / "cache/unknown.c").read_text(), "keep this")

    def test_racing_source_is_never_declared_verified(self):
        tree, archive, digest = self.archive()
        original = preservation._finish

        def change(*args):
            (tree / "hello.c").write_text("concurrent unpublished change")
            return original(*args)

        with mock.patch.object(preservation, "_finish", side_effect=change):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                preservation.capture_tar_tree(self.root, tree, archive, digest, self.store)
        self.assertEqual((tree / "hello.c").read_text(), "concurrent unpublished change")

    def test_wrong_archive_hash_or_unsafe_paths_leave_original_untouched(self):
        tree, archive, digest = self.archive()
        with self.assertRaisesRegex(ValueError, "checksum"):
            preservation.capture_tar_tree(self.root, tree, archive, "0" * 64, self.store)
        with tarfile.open(archive, "w:xz") as output:
            member = tarfile.TarInfo("upstream/../../escape")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            preservation.capture_tar_tree(self.root, tree, archive, preservation._digest(archive), self.store)
        self.assertTrue((tree / "hello.c").exists())
        self.assertFalse((self.root / "escape").exists())

    def test_archive_escaping_link_is_rejected_before_any_deletion(self):
        tree, archive, digest = self.archive()
        with tarfile.open(archive, "w:xz") as output:
            member = tarfile.TarInfo("upstream/link")
            member.type, member.linkname = tarfile.SYMTYPE, "../../escape"
            output.addfile(member)
        with self.assertRaises(tarfile.FilterError):
            preservation.capture_tar_tree(self.root, tree, archive, preservation._digest(archive), self.store)
        self.assertTrue(tree.is_dir())

    def test_corrupt_blob_cannot_be_restored_and_existing_destination_is_safe(self):
        tree = self.root / "source"
        tree.mkdir()
        (tree / "private.c").write_text("unpublished")
        result = preservation.capture_tree(self.root, tree, self.store)
        destination = self.root / "restore"
        destination.mkdir()
        (destination / "keep").write_text("untouched")
        with self.assertRaisesRegex(ValueError, "already exist"):
            preservation.restore_snapshot(result, destination)
        self.assertEqual((destination / "keep").read_text(), "untouched")
        shutil.rmtree(destination)
        next((self.store / "blobs").iterdir()).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            preservation.restore_snapshot(result, destination)
        self.assertFalse(destination.exists())
        self.assertEqual((tree / "private.c").read_text(), "unpublished")

    def test_symlink_tree_or_store_cannot_escape_project(self):
        tree = self.root / "source"
        tree.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(tree, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            preservation.capture_tree(self.root, alias, self.store)
        with self.assertRaisesRegex(ValueError, "outside"):
            preservation.capture_tree(self.root, tree, self.root.parent / "outside-store")
        with self.assertRaisesRegex(ValueError, "outside the disposable"):
            preservation.capture_tree(self.root, tree, tree / "private")


class GitPreservationTests(Fixture):
    def setUp(self):
        super().setUp()
        self.tree = self.root / "checkout"
        self.tree.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Preservation Test")
        self.git("config", "user.email", "preservation@example.invalid")
        (self.tree / "hello.c").write_text("initial\n")
        (self.tree / "removed.c").write_text("remove me\n")
        (self.tree / ".gitignore").write_text("ignored/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "upstream source")

    def git(self, *args, input=None, tree=None):
        return preservation._git(tree or self.tree, *args, input=input)

    def test_git_preserves_local_refs_commits_index_ignored_and_untracked_bytes(self):
        (self.tree / "hello.c").write_text("local-only commit\n")
        self.git("commit", "-am", "unpublished local commit", "-q")
        commit = self.git("rev-parse", "HEAD")
        self.git("branch", "private-work")
        (self.tree / "hello.c").write_text("staged unpublished\n")
        self.git("add", "hello.c")
        (self.tree / "hello.c").write_text("unstaged unpublished\n")
        (self.tree / "removed.c").unlink()
        (self.tree / "ignored").mkdir()
        (self.tree / "ignored/fixture").write_bytes(b"\x00ignored authored binary\xff")
        (self.tree / "untracked.c").write_text("unknown source\n")
        (self.tree / "symlink").symlink_to("hello.c")
        dangling = self.git("hash-object", "-w", "--stdin", input=b"unreferenced unpublished blob").strip()
        index_before = (self.tree / ".git/index").read_bytes()
        status_before = self.git("status", "--porcelain=v1", "--untracked-files=all")
        result = preservation.capture_git_tree(self.root, self.tree, self.store)
        self.assertTrue(preservation.snapshot_matches_tree(result, self.tree))
        restored = preservation.restore_snapshot(result, self.root / "restored")
        self.assert_same_tree(self.tree, restored, skip={".git"})
        self.assertEqual(self.git("rev-parse", "private-work", tree=restored), commit)
        self.assertEqual(self.git("show", ":hello.c", tree=restored), b"staged unpublished\n")
        self.assertEqual(self.git("cat-file", "blob", dangling.decode(), tree=restored), b"unreferenced unpublished blob")
        self.assertEqual((restored / ".git/index").read_bytes(), index_before)
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all", tree=restored), status_before)

    def test_git_metadata_race_is_detected(self):
        result = preservation.capture_git_tree(self.root, self.tree, self.store)
        self.git("branch", "new-local-ref")
        self.assertFalse(preservation.snapshot_matches_tree(result, self.tree))

    def test_git_bundle_corruption_prevents_restore(self):
        result = preservation.capture_git_tree(self.root, self.tree, self.store)
        (Path(result["manifest"]).parent / "source.bundle").write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "checksum"):
            preservation.restore_snapshot(result, self.root / "restored")
        self.assertTrue((self.tree / "hello.c").exists())

    def test_depth_one_input_checkout_restores_without_network_or_missing_parents(self):
        (self.tree / "hello.c").write_text("second commit\n")
        self.git("commit", "-qam", "second commit")
        shallow = self.root / "shallow"
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", self.tree.as_uri(), str(shallow)], check=True)
        (shallow / "unpublished.c").write_text("local shallow checkout source\n")
        result = preservation.capture_git_tree(self.root, shallow, self.store)
        restored = preservation.restore_snapshot(result, self.root / "restored")
        self.assert_same_tree(shallow, restored, skip={".git"})
        self.assertEqual(self.git("rev-parse", "--is-shallow-repository", tree=restored), b"true\n")
        self.assertEqual(self.git("rev-parse", "HEAD", tree=restored), self.git("rev-parse", "HEAD", tree=shallow))

    def test_automatic_runs_share_identical_git_bundles(self):
        automatic = self.root / "development/source-preservation/auto"
        first = preservation.capture_git_tree(self.root, self.tree, automatic / "run-one")
        second = preservation.capture_git_tree(self.root, self.tree, automatic / "run-two")
        first_bundle = Path(first["manifest"]).parent / "source.bundle"
        second_bundle = Path(second["manifest"]).parent / "source.bundle"
        self.assertEqual(first_bundle.stat().st_ino, second_bundle.stat().st_ino)
        self.assertEqual(len(list((automatic / "bundles").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
