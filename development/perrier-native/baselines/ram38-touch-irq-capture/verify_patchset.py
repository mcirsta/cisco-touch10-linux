#!/usr/bin/env python3
"""Apply the reviewed kernel patches to a fresh seven-file source extraction."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / "development/sources/linux-6.18.48.tar.xz"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(ARCHIVE) == "5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c"
    manifest = json.loads((HERE / "kernel-patches/manifest.json").read_text())
    assert manifest["kernel"] == "linux-6.18.48"
    entries = manifest["patches"]
    with tempfile.TemporaryDirectory(prefix="perrier-patchcheck-") as temp:
        subprocess.run(["tar", "-xJf", str(ARCHIVE), "-C", temp,
                        *("linux-6.18.48/" + item["path"] for item in entries)],
                       check=True)
        source = Path(temp) / "linux-6.18.48"
        for item in entries:
            target = source / item["path"]
            patch = HERE / "kernel-patches" / item["patch"]
            assert sha(target) == item["vanilla_sha256"], target
            assert sha(patch) == item["patch_sha256"], patch
            subprocess.run(["patch", "--batch", "--forward", "--fuzz=0",
                            "-d", str(source), "-p1", "-i", str(patch)],
                           check=True, stdout=subprocess.DEVNULL)
            assert sha(target) == item["patched_sha256"], target
    print(f"Verified {len(entries)} exact patches against pristine Linux 6.18.48")


if __name__ == "__main__":
    main()
