#!/usr/bin/env python3
"""Remove one verified, host-backed-up obsolete RAM test image from p14.

This is a one-use maintenance step for ram112 staging. The exact old file is
checked byte-for-byte against its audited host copy before removal. Run only
after the owner explicitly authorizes this single persistent deletion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HOST = ROOT / "development/perrier-ramenv/mainline-ram/kernel-build/arch/arm/boot/zImage"
REMOTE = "/mnt/base/touch10-dev/ram65-a89c15effd18.zImage"
EXPECTED_SHA256 = "a89c15effd1886984246d40a4b25166df43f18d11b6923ad0377ac8dc7953ec4"
EXPECTED_SIZE = 17056880
MIN_FREE_KB = 25904
sys.path.insert(0, str(ROOT / "tools"))
import touch10_dev as dev


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="delete exactly the reviewed obsolete p14 file")
    args = parser.parse_args()
    host = HOST.read_bytes()
    assert len(host) == EXPECTED_SIZE and sha(host) == EXPECTED_SHA256
    baseline = json.loads((ROOT / "development/perrier-ramenv/mainline-ram/reviewed-image.json").read_text())
    assert baseline["passed"] and baseline["artifacts"]["zImage"]["sha256"] == EXPECTED_SHA256
    if not args.execute:
        print(json.dumps({"ready": True, "remote_file": REMOTE,
                          "bytes": EXPECTED_SIZE, "sha256": EXPECTED_SHA256,
                          "host_copy": str(HOST)}, indent=2))
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = ROOT / "development/runs" / (stamp + "-p14-ram65-cleanup")
    directory.mkdir(mode=0o700)
    panel = dev.Panel(directory)
    state = panel.snapshot()
    assert state["kernel"] == "3.4.113+" and state["factory_app"] == "running"
    assert panel.env_hash() == dev.STOCK_ENV_SHA256
    preflight = panel.run("""set -eu
test "$(awk '$2 == "/mnt/base" {print $1}' /proc/mounts)" = /dev/mmcblk0p14
test "$(awk '$2 == "/mnt/base" {print $3}' /proc/mounts)" = ext4
test ! -L /mnt/base/touch10-dev
test -d /mnt/base/touch10-dev
test ! -L /mnt/base/touch10-dev/ram65-a89c15effd18.zImage
test -f /mnt/base/touch10-dev/ram65-a89c15effd18.zImage
df -Pk /mnt/base
""")
    preflight.check_returncode()
    before = subprocess.run(panel.ssh + ["cat " + REMOTE], capture_output=True, timeout=60)
    assert before.returncode == 0 and before.stdout == host
    free_before = int(preflight.stdout.splitlines()[-1].split()[3])
    assert free_before < MIN_FREE_KB
    deleted = panel.run("set -eu\nrm -f " + REMOTE + "\nsync\ntest ! -e " + REMOTE + "\ndf -Pk /mnt/base\n")
    deleted.check_returncode()
    free_after = int(deleted.stdout.splitlines()[-1].split()[3])
    assert free_after >= MIN_FREE_KB, free_after
    assert panel.env_hash() == dev.STOCK_ENV_SHA256
    after_state = panel.snapshot()
    assert after_state["boot_id"] == state["boot_id"]
    assert after_state["factory_app"] == "running"
    report = {"passed": True, "remote_file": REMOTE, "host_copy": str(HOST),
              "sha256": EXPECTED_SHA256, "bytes": EXPECTED_SIZE,
              "free_before_kb": free_before, "free_after_kb": free_after,
              "stock_boot_id": state["boot_id"], "stock_environment_sha256": dev.STOCK_ENV_SHA256}
    (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"run": str(directory), **report}, indent=2))


if __name__ == "__main__":
    main()
