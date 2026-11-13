#!/usr/bin/env python3
"""Apply the reviewed kernel patches to a fresh source extraction."""
import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--patches', type=Path, default=HERE/'kernel-patches')
    args = parser.parse_args()
    args.patches = args.patches.resolve()
    assert sha(ARCHIVE) == "5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c"
    manifest = json.loads((args.patches / "manifest.json").read_text())
    assert manifest["kernel"] == "linux-6.18.48"
    entries = manifest["patches"]
    with tempfile.TemporaryDirectory(prefix="perrier-patchcheck-") as temp:
        subprocess.run(["tar", "-xJf", str(ARCHIVE), "-C", temp,
                        *("linux-6.18.48/" + item["path"] for item in entries
                          if item['vanilla_sha256'] is not None)],
                       check=True)
        source = Path(temp) / "linux-6.18.48"
        for item in entries:
            target = source / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            patch = args.patches / item["patch"]
            assert (sha(target) if target.exists() else None) == item["vanilla_sha256"], target
            assert sha(patch) == item["patch_sha256"], patch
            subprocess.run(["patch", "--batch", "--forward", "--fuzz=0",
                            "-d", str(source), "-p1", "-i", str(patch)],
                           check=True, stdout=subprocess.DEVNULL)
            assert sha(target) == item["patched_sha256"], target
    print(f"Verified {len(entries)} exact patches against pristine Linux 6.18.48")


if __name__ == "__main__":
    main()
