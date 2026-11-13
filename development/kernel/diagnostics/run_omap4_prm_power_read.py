#!/usr/bin/env python3
"""Run one owner-authorized, read-only OMAP PRM snapshot on stock Linux."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import touch10_dev as dev
from analyze_omap4_prm_power import decode

BINARY = HERE / "omap4_prm_power_read.arm"
REVIEW = HERE / "omap4-prm-power-read-review.json"
AUTH = HERE / "omap4-prm-power-read-authorization.json"
USED = HERE / "omap4-prm-power-read-used.json"
TEMP = "/tmp/perrier-omap4-prm-power-read"


def run(panel: dev.Panel, script: str, timeout: int = 12) -> str:
    result = panel.run(script, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"stock SSH command failed: {result.stderr.strip()}")
    return result.stdout


def main() -> None:
    review = json.loads(REVIEW.read_text())
    binary = BINARY.read_bytes()
    assert review["passed"] and not review["device_run"]
    assert review["binary_sha256"] == hashlib.sha256(binary).hexdigest()
    assert review["binary_sha512"] == hashlib.sha512(binary).hexdigest()
    assert len(binary) == review["binary_size"] == 45244
    if not AUTH.is_file():
        raise RuntimeError("an explicit one-run authorization is required")
    approval = json.loads(AUTH.read_text())
    if approval != {"authorized": True, "binary_sha256": review["binary_sha256"],
                    "scope": "one RAM-only upload, one read-only PRM snapshot, removal"}:
        raise RuntimeError("authorization does not cover this exact helper and scope")
    if USED.exists():
        raise RuntimeError("the one-run authorization has already been consumed")
    directory = ROOT / "development/runs" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
        "-stock-prm-read-" + uuid.uuid4().hex[:6])
    directory.mkdir(mode=0o700)
    panel = dev.Panel(directory)
    before = panel.snapshot()
    if before["kernel"] != "3.4.113+" or before["factory_app"] != "running":
        raise RuntimeError("healthy stock Linux and Phoenix are required")
    mounts = run(panel, "awk '$2 == \"/tmp\" { print $3 }' /proc/mounts\n")
    if mounts.strip() != "tmpfs":
        raise RuntimeError("/tmp is not RAM-only tmpfs")
    if run(panel, f"if [ -e {TEMP} ] || [ -L {TEMP} ]; then echo occupied; else echo free; fi\n").strip() != "free":
        raise RuntimeError("temporary path is occupied")
    uploaded = False
    try:
        USED.write_text(json.dumps({"started": datetime.now(timezone.utc).isoformat(),
                                    "directory": str(directory),
                                    "binary_sha256": review["binary_sha256"]}, indent=2) + "\n")
        uploaded = True
        transfer = subprocess.run(panel.ssh + [f"umask 077; cat > {TEMP}"],
                                  input=binary, capture_output=True, timeout=20)
        if transfer.returncode:
            raise RuntimeError("RAM-only transfer failed: " +
                               transfer.stderr.decode(errors="replace"))
        remote_hash = run(panel, f"sha512sum {TEMP}\n").split()[0]
        if remote_hash != review["binary_sha512"]:
            raise RuntimeError("RAM-only transfer hash mismatch")
        run(panel, f"chmod 700 {TEMP}\n")
        raw = run(panel, f"{TEMP}\n", timeout=15)
        raw_path = directory / "prm-raw.csv"
        raw_path.write_text(raw)
        decoded = decode(raw_path)
        (directory / "prm-decoded.json").write_text(json.dumps(decoded, indent=2) + "\n")
    finally:
        if uploaded:
            run(panel, f"rm -f {TEMP}\n")
    after = panel.snapshot()
    if after["kernel"] != before["kernel"] or after["boot_id"] != before["boot_id"] or \
       after["factory_app"] != "running":
        raise RuntimeError("stock health or boot identity changed during snapshot")
    if run(panel, f"if [ -e {TEMP} ] || [ -L {TEMP} ]; then echo occupied; else echo free; fi\n").strip() != "free":
        raise RuntimeError("RAM helper was not removed")
    report = {
        "passed": True,
        "device_run": True,
        "temporary_helper_removed": True,
        "stock_boot_id_unchanged": True,
        "source_review_sha256": hashlib.sha256(REVIEW.read_bytes()).hexdigest(),
        "binary_sha256": review["binary_sha256"],
        "raw_sha256": hashlib.sha256((directory / "prm-raw.csv").read_bytes()).hexdigest(),
        "decoded_sha256": hashlib.sha256((directory / "prm-decoded.json").read_bytes()).hexdigest(),
        "before": before,
        "after": after,
        "directory": str(directory),
    }
    (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
