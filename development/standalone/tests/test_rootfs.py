"""Archive and credential-boundary checks without prior project artifacts."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("standalone_rootfs", Path(__file__).resolve().parents[1] / "rootfs.py")
rootfs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rootfs)


class ArchiveTests(unittest.TestCase):
    def test_packing_is_deterministic_and_independent_of_host_mtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tree = directory / "rootfs"
            (tree / "bin").mkdir(parents=True)
            (tree / "dev").mkdir()
            program = tree / "bin/tool"
            program.write_bytes(b"freshly built payload")
            program.chmod(0o755)
            (tree / "init").symlink_to("bin/tool")
            first, second = directory / "one.cpio", directory / "two.cpio"
            expected = rootfs.pack_rootfs(tree, first)
            program.touch()
            actual = rootfs.pack_rootfs(tree, second)
            self.assertEqual(expected, actual)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(expected["bin/tool"]["sha256"], hashlib.sha256(program.read_bytes()).hexdigest())
            rootfs.audit_archive(first, expected)

    def test_tampered_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tree = directory / "rootfs"
            tree.mkdir()
            (tree / "payload").write_bytes(b"original payload")
            archive = directory / "initramfs.cpio"
            expected = rootfs.pack_rootfs(tree, archive)
            archive.write_bytes(archive.read_bytes().replace(b"original payload", b"modified payload"))
            with self.assertRaises(AssertionError):
                rootfs.audit_archive(archive, expected)

    def test_external_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tree = directory / "rootfs"
            tree.mkdir()
            (tree / "escape").symlink_to("../host-secret")
            with self.assertRaisesRegex(ValueError, "escapes the image"):
                rootfs.pack_rootfs(tree, directory / "initramfs.cpio")


class PublicKeyTests(unittest.TestCase):
    def test_public_key_is_accepted_without_reading_an_owner_access_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "id.pub"
            name = b"ssh-ed25519"
            payload = struct.pack(">I", len(name)) + name + struct.pack(">I", 32) + bytes(range(32))
            line = "ssh-ed25519 " + base64.b64encode(payload).decode() + " clean-clone-test\n"
            path.write_text(line)
            self.assertEqual(rootfs.public_key(path), line)

    def test_private_key_and_authorized_keys_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "key"
            for text in ("-----BEGIN OPENSSH PRIVATE KEY-----\n",
                         'command="unexpected" ssh-ed25519 AAAA\n'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    rootfs.public_key(path)


if __name__ == "__main__":
    unittest.main()
