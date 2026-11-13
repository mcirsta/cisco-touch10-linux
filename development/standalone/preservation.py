#!/usr/bin/env python3
"""Lossless, private source snapshots for build cleanup.

The cleanup caller decides what is generated. Nothing is excluded by filename or
file format here: upstream binary fixtures, ignored files and unknown additions
are source data unless an explicit callback records another policy. This module
never deletes an original tree. A verified snapshot and an unchanged full-tree
fingerprint are prerequisites for the caller to do that.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid

FORMAT = 1


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _safe(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(p in {".", ".."} for p in name.split("/")):
        raise ValueError(f"Unsafe snapshot path: {name}")
    return path.as_posix()


def _stat(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


def _inspect(path):
    before = path.lstat()
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISREG(before.st_mode):
        entry = {"kind": "file", "mode": mode, "bytes": before.st_size,
                 "sha256": _digest(path)}
    elif stat.S_ISDIR(before.st_mode):
        entry = {"kind": "directory", "mode": mode}
    elif stat.S_ISLNK(before.st_mode):
        entry = {"kind": "symlink", "mode": mode, "target": os.readlink(path)}
    else:
        raise ValueError(f"Unsupported source object; original must be kept: {path}")
    if _stat(before) != _stat(path.lstat()):
        raise RuntimeError(f"Source changed while being read: {path}")
    return entry, _stat(before)


def _scan(tree, skip=()):
    """Read all bytes without following links, and detect directory races too."""
    tree = Path(tree)
    if tree.is_symlink() or not tree.is_dir():
        raise ValueError(f"Source root must be a real directory: {tree}")
    entries, stats = {}, {}

    def visit(directory, relative):
        descriptor, before = _inspect(directory)
        entries[relative] = descriptor
        stats[relative] = before
        with os.scandir(directory) as stream:
            children = sorted(stream, key=lambda child: child.name)
        for child in children:
            name = f"{relative}/{child.name}" if relative else child.name
            if name in skip:
                continue
            descriptor, info = _inspect(Path(child.path))
            entries[name], stats[name] = descriptor, info
            if descriptor["kind"] == "directory":
                visit(Path(child.path), name)
        if _stat(directory.lstat()) != before:
            raise RuntimeError(f"Source directory changed while being read: {directory}")

    visit(tree, "")
    return entries, _hash(_json({"entries": entries, "stat": stats}))


def tree_fingerprint(tree):
    """Hash contents and complete race-sensitive stat metadata, including .git."""
    return _scan(Path(tree))[1]


def _tree_digest(entries):
    return _hash(_json(entries))


def _git(tree, *args, input=None):
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    return subprocess.check_output(["git", "-C", str(tree), *args],
                                   input=input, env=environment, stderr=subprocess.PIPE)


def _within(root, path):
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    # Reject a symlink root instead of silently snapshotting its destination.
    if path.is_symlink():
        raise ValueError(f"Refusing symlink source/store: {path}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path is outside project root: {path}")
    return resolved


def _setup(root, tree, store):
    root = Path(root).resolve()
    tree, store = _within(root, tree), _within(root, store)
    if tree == root or store == tree or store.is_relative_to(tree):
        raise ValueError("Preservation store must be outside the disposable source tree")
    store.mkdir(parents=True, exist_ok=True)
    name = tree.name + "-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    snapshot = store / (name + "-" + uuid.uuid4().hex[:12])
    snapshot.mkdir(mode=0o700)
    # Cleanup groups manifests by run, but source bytes and upstream history
    # are shared across runs instead of accumulating another cache each build.
    automatic = root / "development/source-preservation/auto"
    content_store = automatic if store.is_relative_to(automatic) else store
    content_store.mkdir(parents=True, exist_ok=True)
    return root, tree, content_store, snapshot


def _blob(store, data):
    digest = _hash(data)
    destination = store / "blobs" / digest
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    if destination.exists():
        if _digest(destination) != digest:
            raise ValueError(f"Corrupt existing preservation blob: {destination}")
    else:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".blob-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
    return digest


def _load_blob(manifest, digest):
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid preservation blob digest")
    record = json.loads(manifest.read_text())
    store = _within(Path(record["root"]).resolve(), record["content_store"])
    data = (store / "blobs" / digest).read_bytes()
    if _hash(data) != digest:
        raise ValueError(f"Preservation blob checksum mismatch: {digest}")
    return data


def _archive(archive, expected_sha, consume=None):
    """Describe Python data-filter extraction, streaming original file bytes.

    Directory modes have an explicit 0755 baseline. Actual extraction umask
    differences are metadata deltas, never duplicate copies of file contents.
    """
    if _digest(archive) != expected_sha:
        raise ValueError(f"Upstream archive checksum mismatch: {archive}")
    entries = {"": {"kind": "directory", "mode": 0o755}}
    top = None
    with tarfile.open(archive) as source:
        for member in source:
            name = _safe(member.name.rstrip("/"))
            parts = PurePosixPath(name).parts
            if top is None:
                top = parts[0]
            if parts[0] != top:
                raise ValueError("Archive must contain exactly one source top directory")
            # Validate both link types with the same policy as input extraction.
            filtered = tarfile.data_filter(member, "/__touch10_preservation__")
            name = "/".join(parts[1:])
            if not name:
                if not member.isdir():
                    raise ValueError("Archive source root must be a directory")
                continue
            if name in entries:
                raise ValueError(f"Duplicate archive path: {name}")
            data = None
            if member.isfile() or member.islnk():
                data = source.extractfile(member).read()
                entry = {"kind": "file", "mode": filtered.mode, "bytes": len(data), "sha256": _hash(data)}
            elif member.isdir():
                entry = {"kind": "directory", "mode": 0o755}
            elif member.issym():
                entry = {"kind": "symlink", "mode": 0o777, "target": filtered.linkname}
            else:
                raise ValueError(f"Unsupported archive object: {member.name}")
            entries[name] = entry
            if consume is not None:
                consume(name, entry, data)
    if top is None:
        raise ValueError("Empty upstream archive")
    # Some release archives omit parent directory records.
    for name in list(entries):
        for parent in PurePosixPath(name).parents:
            if str(parent) != ".":
                entries.setdefault(str(parent), {"kind": "directory", "mode": 0o755})
    _validate_entries(entries)
    return entries, top


def _validate_entries(entries):
    if entries.get("", {}).get("kind") != "directory":
        raise ValueError("Snapshot root must be a directory")
    for name, entry in entries.items():
        if name:
            _safe(name)
            parent = str(PurePosixPath(name).parent)
            parent = "" if parent == "." else parent
            if entries.get(parent, {}).get("kind") != "directory":
                raise ValueError(f"Snapshot path has a missing or non-directory parent: {name}")
        if entry.get("kind") not in {"file", "directory", "symlink"}:
            raise ValueError(f"Unknown snapshot object kind: {name}")


def _delta(tree, current, baseline, store, exclude_generated):
    changes, excluded = {}, {}
    expected = dict(baseline)
    for name in sorted(set(current) | set(baseline)):
        before, after = baseline.get(name), current.get(name)
        if before == after:
            continue
        # A changed original upstream file may contain unpublished work even
        # when its filename resembles a generated object. Only additions are
        # eligible for the caller's explicit generated-output policy.
        reason = exclude_generated(name, after) if exclude_generated and name and after and before is None else None
        if reason:
            excluded[name] = {"descriptor": after, "reason": str(reason)}
            continue
        operation = {"before": before, "after": after}
        if after and after["kind"] == "file" and (
                not before or before["kind"] != "file" or before["sha256"] != after["sha256"]):
            data = (tree / name).read_bytes()
            if len(data) != after["bytes"] or _hash(data) != after["sha256"]:
                raise RuntimeError(f"Source changed during preservation: {tree / name}")
            operation["blob"] = _blob(store, data)
        changes[name] = operation
        if after is None:
            expected.pop(name, None)
        else:
            expected[name] = after
    # An explicitly omitted directory omits its descendants only when every
    # child was also explicitly identified as generated by the caller.
    _validate_entries(expected)
    return changes, excluded, expected


def _write_manifest(path, record):
    """Durably publish complete metadata after its referenced blobs exist."""
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _finish(root, tree, snapshot, store, record, before):
    if tree_fingerprint(tree) != before:
        raise RuntimeError(f"Source changed during preservation; original must be kept: {tree}")
    record.update({"format": FORMAT, "root": str(root), "content_store": str(store.relative_to(root)),
                   "original_tree": str(tree.relative_to(root)),
                   "fingerprint": before, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    manifest = snapshot / "manifest.json"
    _write_manifest(manifest, record)
    verify_snapshot(manifest)
    record["verified"] = True
    _write_manifest(manifest, record)
    if tree_fingerprint(tree) != before:
        raise RuntimeError(f"Source changed after preservation; original must be kept: {tree}")
    return {"manifest": str(manifest), "verified": True, "fingerprint": before,
            "tree_sha256": record["tree_sha256"], "exclusions": record["exclusions"]}


def capture_tar_tree(root, tree, archive, archive_sha, store, *, exclude_generated=None):
    """Preserve exact differences against a retained, hash-pinned source tar."""
    root, tree, store, snapshot = _setup(root, tree, store)
    archive = _within(root, archive)
    current, before = _scan(tree)
    baseline, top = _archive(archive, archive_sha)
    changes, excluded, expected = _delta(tree, current, baseline, store, exclude_generated)
    return _finish(root, tree, snapshot, store, {
        "kind": "tar", "archive": str(archive.relative_to(root)), "archive_sha256": archive_sha,
        "archive_top": top, "changes": changes, "exclusions": excluded,
        "tree_sha256": _tree_digest(expected), "objects": len(expected)}, before)


def capture_tree(root, tree, store, *, exclude_generated=None):
    """Preserve a non-upstream tree, excluding only caller-identified outputs."""
    root, tree, store, snapshot = _setup(root, tree, store)
    current, before = _scan(tree)
    changes, excluded, expected = _delta(tree, current, {}, store, exclude_generated)
    return _finish(root, tree, snapshot, store, {
        "kind": "literal", "changes": changes, "exclusions": excluded,
        "tree_sha256": _tree_digest(expected), "objects": len(expected)}, before)


def capture_git_tree(root, tree, store, *, exclude_generated=None):
    """Preserve all local refs/objects/index plus ignored and untracked source.

    A self-contained bundle stores history. Only worktree differences and Git
    objects not reachable from refs/reflogs need literal blobs. Linked worktrees
    are refused because their shared metadata has another owner.
    """
    root, tree, store, snapshot = _setup(root, tree, store)
    gitdir = tree / ".git"
    if gitdir.is_symlink() or not gitdir.is_dir():
        raise ValueError("Cleanup requires an independent Git checkout with a .git directory")
    before = tree_fingerprint(tree)
    current, _ = _scan(tree, skip={".git"})
    head = _git(tree, "rev-parse", "HEAD").decode().strip()
    object_format = _git(tree, "rev-parse", "--show-object-format").decode().strip()
    bundle = snapshot / "source.bundle"
    _git(tree, "bundle", "create", str(bundle), "--all", "--reflog", "HEAD")
    bundle_sha = _digest(bundle)
    bundles = store / "bundles"
    bundles.mkdir(mode=0o700, exist_ok=True)
    shared_bundle = bundles / (bundle_sha + ".bundle")
    if shared_bundle.exists():
        if _digest(shared_bundle) != bundle_sha:
            raise ValueError("Corrupt shared source bundle")
        bundle.unlink()
    else:
        with bundle.open("rb") as stream:
            os.fsync(stream.fileno())
        bundle.replace(shared_bundle)
    os.link(shared_bundle, bundle)
    # Preserve metadata (including raw index, reflogs, custom hooks and config),
    # but replace the reproducible object database with the compact bundle.
    metadata, _ = _scan(gitdir, skip={"objects"})
    metadata_changes, _, _ = _delta(gitdir, metadata, {}, store, None)
    reachable = set(_git(tree, "rev-list", "--objects", "--all", "--reflog",
                         "HEAD", "--no-object-names").decode().splitlines())
    all_objects = _git(tree, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)")
    extras = {}
    for line in all_objects.decode().splitlines():
        oid, kind = line.split()
        if oid not in reachable:
            extras[oid] = {"kind": kind, "blob": _blob(store, _git(tree, "cat-file", kind, oid))}
    baseline = {"": current[""]}
    listing = _git(tree, "ls-tree", "-r", "-z", head)
    for row in listing.split(b"\0"):
        if not row:
            continue
        attributes, raw_name = row.split(b"\t", 1)
        mode, kind, oid = attributes.decode().split()
        name = _safe(os.fsdecode(raw_name))
        if kind != "blob":
            raise ValueError("Git submodules require separate preservation; original must be kept")
        data = _git(tree, "cat-file", "blob", oid)
        if mode == "120000":
            baseline[name] = {"kind": "symlink", "mode": 0o777, "target": os.fsdecode(data)}
        else:
            baseline[name] = {"kind": "file", "mode": 0o755 if mode == "100755" else 0o644,
                              "bytes": len(data), "sha256": _hash(data)}
        for parent in PurePosixPath(name).parents:
            if str(parent) != ".":
                baseline.setdefault(str(parent), {"kind": "directory", "mode": 0o755})
    changes, excluded, expected = _delta(tree, current, baseline, store, exclude_generated)
    return _finish(root, tree, snapshot, store, {
        "kind": "git", "head": head, "object_format": object_format,
        "bundle_sha256": bundle_sha, "baseline": baseline,
        "git_metadata": metadata_changes, "extra_git_objects": extras,
        "changes": changes, "exclusions": excluded,
        "tree_sha256": _tree_digest(expected), "objects": len(expected)}, before)


def _read(snapshot):
    path = Path(snapshot["manifest"] if isinstance(snapshot, dict) else snapshot).resolve()
    record = json.loads(path.read_text())
    if record.get("format") != FORMAT:
        raise ValueError("Unsupported preservation snapshot format")
    return path, record


def _expected(path, record, consume=None):
    if record["kind"] == "tar":
        root = Path(record["root"])
        archive = _within(root, record["archive"])
        baseline, top = _archive(archive, record["archive_sha256"], consume)
        if top != record["archive_top"]:
            raise ValueError("Upstream archive root changed")
    elif record["kind"] == "git":
        if _digest(path.parent / "source.bundle") != record["bundle_sha256"]:
            raise ValueError("Git source bundle checksum mismatch")
        baseline = record["baseline"]
    elif record["kind"] == "literal":
        baseline = {}
    else:
        raise ValueError("Unknown preservation snapshot kind")
    expected = dict(baseline)
    for name, change in record["changes"].items():
        if name:
            _safe(name)
        if change["before"] != baseline.get(name):
            raise ValueError(f"Preservation baseline mismatch: {name}")
        after = change["after"]
        if after is None:
            expected.pop(name, None)
        else:
            expected[name] = after
        if "blob" in change:
            data = _load_blob(path, change["blob"])
            if after["kind"] != "file" or len(data) != after["bytes"] or _hash(data) != after["sha256"]:
                raise ValueError(f"Preservation content mismatch: {name}")
        elif after and after["kind"] == "file" and (
                not change["before"] or after["sha256"] != change["before"].get("sha256")):
            raise ValueError(f"Missing preserved file bytes: {name}")
    _validate_entries(expected)
    if _tree_digest(expected) != record["tree_sha256"] or len(expected) != record["objects"]:
        raise ValueError("Preservation reconstructed tree checksum mismatch")
    return expected


def verify_snapshot(snapshot):
    """Verify every reconstruction input without needing the original tree."""
    path, record = _read(snapshot)
    expected = _expected(path, record)
    if record["kind"] == "git":
        # A physical, offline Git restore verifies history, staging and the
        # complete worktree against the manifest, rather than trusting a bundle.
        with tempfile.TemporaryDirectory(prefix="verify-git-source-", dir=path.parent) as temporary:
            restored = Path(temporary) / "tree"
            _restore(path, record, expected, restored)
    return {"verified": True, "tree_sha256": record["tree_sha256"], "objects": len(expected)}


def snapshot_matches_tree(snapshot, tree):
    """Recheck all bytes/stats immediately before cleanup; errors mean keep it."""
    _, record = _read(snapshot)
    return bool(record.get("verified")) and tree_fingerprint(tree) == record["fingerprint"]


def _write_entries(base, entries, data_for):
    _validate_entries(entries)
    for name, entry in sorted(entries.items(), key=lambda item: (item[0].count("/"), item[0])):
        if not name:
            continue
        target = base / _safe(name)
        if entry["kind"] == "directory":
            target.mkdir(exist_ok=True)
        elif entry["kind"] == "file":
            data = data_for(name, entry)
            if len(data) != entry["bytes"] or _hash(data) != entry["sha256"]:
                raise ValueError(f"Restoration file checksum mismatch: {name}")
            target.write_bytes(data)
            target.chmod(entry["mode"])
        elif entry["kind"] == "symlink":
            target.symlink_to(entry["target"])
    # Apply restrictive directory permissions after their children are written.
    for name, entry in sorted(entries.items(), key=lambda item: -item[0].count("/")):
        if entry["kind"] == "directory":
            (base / name).chmod(entry["mode"])


def _restore(path, record, expected, destination):
    destination.mkdir()
    if record["kind"] == "git":
        _git(destination, "init", "--quiet", "--object-format=" + record["object_format"])
        metadata = {name: change["after"] for name, change in record["git_metadata"].items()}
        for child in (destination / ".git").iterdir():
            if child.name != "objects":
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        _write_entries(destination / ".git", metadata,
                       lambda name, entry: _load_blob(path, record["git_metadata"][name]["blob"]))
        # A normal bundle clone traverses missing parents before installing the
        # source's shallow boundaries. Input checkouts are intentionally shallow,
        # so import the self-contained pack after restoring that metadata.
        with (path.parent / "source.bundle").open("rb", buffering=0) as stream:
            if stream.readline() not in {b"# v2 git bundle\n", b"# v3 git bundle\n"}:
                raise ValueError("Invalid preserved Git bundle header")
            while True:
                line = stream.readline()
                if line == b"\n":
                    break
                if not line:
                    raise ValueError("Truncated preserved Git bundle")
            subprocess.run(["git", "-C", str(destination), "index-pack", "--stdin", "--fix-thin"],
                           stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        for oid, entry in record["extra_git_objects"].items():
            actual = _git(destination, "hash-object", "-w", "-t", entry["kind"], "--stdin",
                          input=_load_blob(path, entry["blob"])).decode().strip()
            if actual != oid:
                raise ValueError("Preserved Git object checksum mismatch")
        _git(destination, "fsck", "--no-reflogs", "--connectivity-only")

    # Stream baseline archive bytes directly into final expected file paths,
    # then materialize modified files. No upstream binary fixture is duplicated
    # into the snapshot store.
    archive_files = set()
    if record["kind"] == "tar":
        def write_baseline(name, entry, data):
            if entry["kind"] == "file" and expected.get(name, {}).get("kind") == "file" and (
                    expected[name]["sha256"] == entry["sha256"]):
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                archive_files.add(name)
        _archive(_within(Path(record["root"]), record["archive"]), record["archive_sha256"], write_baseline)

    def data_for(name, entry):
        change = record["changes"].get(name, {})
        if "blob" in change:
            return _load_blob(path, change["blob"])
        if name in archive_files:
            return (destination / name).read_bytes()
        if record["kind"] == "git":
            return _git(destination, "show", record["head"] + ":" + name)
        raise ValueError(f"No reconstruction data: {name}")

    _write_entries(destination, expected, data_for)
    actual, _ = _scan(destination, skip={".git"} if record["kind"] == "git" else ())
    if actual != expected:
        raise ValueError("Restored source tree does not match preservation manifest")


def restore_snapshot(snapshot, destination):
    """Restore atomically to a new path, retaining originals on any failure."""
    path, record = _read(snapshot)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Restoration destination must not already exist")
    expected = _expected(path, record)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".restore-source-", dir=destination.parent) as temporary:
        restored = Path(temporary) / "tree"
        _restore(path, record, expected, restored)
        restored.replace(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "restore"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.action == "restore":
        if args.destination is None:
            parser.error("restore requires --destination")
        restore_snapshot(args.manifest, args.destination)
    else:
        print(json.dumps(verify_snapshot(args.manifest), indent=2))


if __name__ == "__main__":
    main()
