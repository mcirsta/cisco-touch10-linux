#!/usr/bin/env python3
"""Fetch pinned upstream inputs for a new Touch 10 build workspace.

Only original release archives and Git source bundles may come from a cache.
No previous kernel, rootfs, Qt installation or locally built executable is used.
Python 3.12 or newer is required for tar's data extraction filter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "inputs.json"
SOURCE_MARKER = ".standalone-upstream.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def checked(path: Path, expected: str) -> Path:
    actual = digest(path)
    if actual != expected:
        raise ValueError(f"Checksum mismatch for {path}: expected {expected}, got {actual}")
    return path


def local_path(root: Path, relative: str) -> Path:
    name = PurePosixPath(relative)
    if name.is_absolute() or ".." in name.parts:
        raise ValueError(f"Input path must stay inside the clone: {relative}")
    path = root.joinpath(*name.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Input path escapes the clone through a symlink: {relative}")
    return path


def copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".input-", dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with source.open("rb") as original:
                shutil.copyfileobj(original, stream, 1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(destination)


def fetch_archive(entry: dict, root: Path, cache: Path | None,
                  offline: bool = False, verify_only: bool = False) -> Path:
    destination = local_path(root, entry["destination"])
    expected = entry["sha256"]
    if destination.exists():
        return checked(destination, expected)
    if verify_only:
        raise FileNotFoundError(f"Missing input archive: {destination}")
    cached = cache / entry["filename"] if cache is not None else None
    if cached is not None and cached.is_file():
        checked(cached, expected)
        copy_atomic(cached, destination)
        return checked(destination, expected)
    if offline:
        raise FileNotFoundError(f"Offline input missing: {entry['filename']}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in [entry["url"], *entry.get("mirrors", [])]:
        if not url.startswith("https://"):
            raise ValueError(f"Upstream downloads require HTTPS: {url}")
        print(f"Fetching {entry['filename']} from {url}", flush=True)
        temporary = None
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "touch10-source-build/1"})
            with urllib.request.urlopen(request, timeout=120) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Refusing an upstream redirect from HTTPS to plaintext")
                with tempfile.NamedTemporaryFile(prefix=".download-", dir=destination.parent,
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    shutil.copyfileobj(response, stream, 1024 * 1024)
                    stream.flush()
                    os.fsync(stream.fileno())
            checked(temporary, expected)
            temporary.replace(destination)
            if cached is not None and not cached.exists():
                copy_atomic(destination, cached)
            return destination
        except (OSError, urllib.error.URLError, ValueError) as error:
            errors.append(f"{url}: {error}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise RuntimeError("Cannot obtain verified source archive:\n" + "\n".join(errors))


def extract_archive(archive: Path, entry: dict, root: Path) -> Path:
    """Extract one validated archive in isolation, rejecting paths and links out.

    Existing directories must have been created by this preparer. Their contents
    can then receive this repository's explicit patches and build configuration.
    """
    checked(archive, entry["sha256"])
    parent = local_path(root, entry["extract_to"])
    top = entry["top_directory"]
    if PurePosixPath(top).parts != (top,):
        raise ValueError("Archive top_directory must be one directory name")
    destination = parent / top
    marker = {"archive": entry["filename"], "sha256": entry["sha256"]}
    if destination.exists():
        source_marker = destination / SOURCE_MARKER
        if not source_marker.is_file() or json.loads(source_marker.read_text()) != marker:
            raise ValueError(f"Refusing unverified existing source directory: {destination}")
        return destination
    if not hasattr(tarfile, "data_filter"):
        raise RuntimeError("Source preparation requires Python 3.12 or newer")
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".unpack-", dir=parent) as temporary:
        unpack = Path(temporary)
        with tarfile.open(archive) as source:
            for member in source:
                path = PurePosixPath(member.name)
                if not path.parts or path.parts[0] != top or ".." in path.parts:
                    raise ValueError(f"Unexpected source archive path: {member.name}")
                source.extract(member, unpack, filter="data")
        extracted = unpack / top
        if not extracted.is_dir() or extracted.is_symlink():
            raise ValueError(f"Missing source archive directory: {top}")
        (extracted / SOURCE_MARKER).write_text(json.dumps(marker, indent=2) + "\n")
        extracted.replace(destination)
    return destination


def git_output(path: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *arguments], text=True).strip()


def verify_git(path: Path, expected: str) -> None:
    if git_output(path, "rev-parse", "HEAD") != expected:
        raise ValueError(f"Wrong source commit in {path}; expected {expected}")
    if git_output(path, "diff", "HEAD", "--name-only"):
        raise ValueError(f"Tracked upstream source changes in {path}")


def prepare_git(name: str, entry: dict, root: Path, cache: Path | None,
                offline: bool = False, verify_only: bool = False) -> Path:
    destination = local_path(root, entry["destination"])
    commit = entry["commit"]
    if destination.exists():
        verify_git(destination, commit)
        return destination
    if verify_only:
        raise FileNotFoundError(f"Missing source checkout: {destination}")
    bundle = cache / f"{name}-{commit}.bundle" if cache is not None else None
    from_bundle = bundle is not None and bundle.is_file()
    if offline and not from_bundle:
        raise FileNotFoundError(f"Offline Git source bundle missing: {name}-{commit}.bundle")
    if not entry["url"].startswith("https://"):
        raise ValueError("Git upstream sources require HTTPS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".git-source-", dir=destination.parent) as temporary:
        checkout = Path(temporary) / name
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        if from_bundle:
            subprocess.run(["git", "-C", str(checkout), "bundle", "verify", str(bundle)], check=True)
        origin = str(bundle.resolve()) if from_bundle else entry["url"]
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", origin], check=True)
        fetch = ["git", "-C", str(checkout), "fetch", "--quiet", "--no-tags"]
        if not from_bundle:
            fetch += ["--depth", "1"]
        subprocess.run(fetch + ["origin", commit], check=True)
        subprocess.run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"], check=True)
        verify_git(checkout, commit)
        subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin", entry["url"]], check=True)
        checkout.replace(destination)
    return destination


def apply_qt_patch(root: Path, manifest: dict) -> None:
    entry = manifest["patches"]["qtbase"]
    patch = checked(local_path(root, entry["path"]), entry["sha256"])
    base = local_path(root, manifest["archives"]["qtbase"]["extract_to"]) / \
        manifest["archives"]["qtbase"]["top_directory"]
    command = ["patch", "--batch", "--dry-run", "-d", str(base), "-p1", "-i", str(patch)]
    forward = subprocess.run(command + ["--forward"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if forward.returncode == 0:
        subprocess.run([part for part in command if part != "--dry-run"] + ["--forward"], check=True)
    else:
        reverse = subprocess.run(command + ["--reverse"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if reverse.returncode:
            raise ValueError("Qt source differs from both the pinned original and the recorded patch")


def prepare(root: Path, cache: Path | None = None, offline: bool = False,
            only: list[str] | None = None, unpack: bool = True,
            verify_only: bool = False) -> dict:
    root = Path(root).resolve()
    cache = Path(cache).resolve() if cache is not None else None
    manifest = json.loads(MANIFEST.read_text())
    all_names = set(manifest["archives"]) | set(manifest["git"])
    selected = set(only) if only is not None else {
        name for section in ("archives", "git")
        for name, entry in manifest[section].items() if entry.get("default", True)
    }
    if selected - all_names:
        raise ValueError("Unknown upstream inputs: " + ", ".join(sorted(selected - all_names)))
    if not root.is_dir():
        raise FileNotFoundError(root)
    if cache is not None and not verify_only:
        cache.mkdir(parents=True, exist_ok=True)
    record: dict = {"archives": {}, "git": {}, "sources": {}}
    for name, entry in manifest["archives"].items():
        if name not in selected:
            continue
        archive = fetch_archive(entry, root, cache, offline, verify_only)
        record["archives"][name] = {"path": str(archive.relative_to(root)),
                                       "sha256": entry["sha256"], "url": entry["url"]}
        if unpack and not verify_only:
            source = extract_archive(archive, entry, root)
            record["sources"][name] = str(source.relative_to(root))
    if "qtbase" in selected and unpack and not verify_only:
        apply_qt_patch(root, manifest)
    for name, entry in manifest["git"].items():
        if name in selected:
            source = prepare_git(name, entry, root, cache, offline, verify_only)
            record["git"][name] = {"path": str(source.relative_to(root)),
                                      "commit": entry["commit"], "url": entry["url"]}
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE.parents[1], help="Fresh clone root")
    parser.add_argument("--cache", type=Path, help="Optional cache of original archives and Git source bundles")
    parser.add_argument("--offline", action="store_true", help="Require local verified originals; do not access network")
    parser.add_argument("--only", nargs="+", help="Select named inputs (default: all except optional TinyALSA and kexec-tools)")
    parser.add_argument("--download-only", action="store_true", help="Fetch archives without extracting them")
    parser.add_argument("--verify-only", action="store_true", help="Check existing archives and Git pins without writing")
    arguments = parser.parse_args()
    record = prepare(arguments.root, arguments.cache, arguments.offline, arguments.only,
                     not arguments.download_only, arguments.verify_only)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
