#!/usr/bin/env python3
"""Stage the pinned ARM SGX runtime without executing package scripts."""

import hashlib
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACKAGES = HERE / "packages"
TARGET = HERE / "rootfs"
TI = ROOT / "development/reference/ti-sgx-um-1.17/targetfs/ti443x_linux/lws-generic/release"

# SHA-256 values are from Debian bookworm's binary-armhf Packages.xz, whose
# hash was checked against dists/bookworm/InRelease on 2026-11-08.
EXPECTED = {
    "libgcc-s1.deb": "f58562bf01efd6112b914182147ee149e0d4c90869046e31844da8803669eeb3",
    "libstdc++6.deb": "66d53ddeb10a37f22e455611c2c515f9d444e523b55d873ff48bde47267963db",
    "libc6.deb": "758c68b92654747025b48476a45c315bf16df1321224abdd9be672bfd120be45",
    "libdrm-common.deb": "32f9664138b38b224383c6986457d5ad2ec8efd559b1a0ce7749405f7a451aad",
    "libdrm2.deb": "f8ead294af29759700620385f8f380bc290f94cf1a17c307e72a9098b6c48846",
}

for name, expected in EXPECTED.items():
    path = PACKAGES / name
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"SHA-256 mismatch: {path}")

TARGET.mkdir(parents=True, exist_ok=True)
for name in EXPECTED:
    with subprocess.Popen(["ar", "p", PACKAGES / name, "data.tar.xz"], stdout=subprocess.PIPE) as ar:
        subprocess.run(["tar", "-xJf", "-", "--no-same-owner", "-C", TARGET],
                       stdin=ar.stdout, check=True)
        assert ar.stdout is not None
        ar.stdout.close()
        if ar.wait() != 0:
            raise SystemExit(f"Failed to extract {name}")

for directory in ("usr/bin", "usr/lib"):
    shutil.copytree(TI / directory, TARGET / directory,
                    dirs_exist_ok=True, symlinks=True)

print(f"Staged Debian armhf and TI SGX 1.17 in {TARGET}")
