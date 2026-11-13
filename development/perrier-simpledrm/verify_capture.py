#!/usr/bin/env python3
"""Recheck a preserved simpledrm RAM trial without touching the panel."""

import hashlib
import json
from pathlib import Path
import re
import sys


def main() -> int:
    run = Path(sys.argv[1])
    raw = (run / "serial.raw").read_bytes()
    original = json.loads((run / "result.json").read_text())

    # Kernel printk can land between two bytes of a PID 1 UART write.
    normalized = re.sub(rb"\[[ \t]*\d+\.\d+\] [^\r\n]*\r?\n", b"", raw)
    proofs = {
        "drm_registered": b"[drm] Initialized simpledrm" in raw,
        "card_created": b"PERRIER_DIR /dev/dri card0" in raw,
        "one_crtc_connector_encoder": re.search(
            rb"PERRIER_DRM_RESOURCES crtcs=1 connectors=1 encoders=1", normalized
        ) is not None,
        "connector_connected_with_mode": re.search(
            rb"PERRIER_DRM_CONNECTOR id=\d+ connection=1 modes=1", normalized
        ) is not None,
        "mode_1280x800_60": b"PERRIER_DRM_MODE name=1280x800 width=1280 height=800 refresh=60" in normalized,
        "probe_exited_zero": b"PERRIER_DRM_PROBE_EXIT status=0" in normalized,
        "stock_recovered": original.get("stock_recovered") is True
        and original.get("after", {}).get("kernel") == "3.4.113+"
        and original.get("after", {}).get("factory_app") == "running",
        "boot_environment_unchanged": original.get("environment_before")
        == original.get("environment_after"),
        "watchdog_advanced": original.get("watchdog_counter_delta", 0) > 0,
        "storage_readonly": original.get("stock_base_readonly") is True
        and original.get("stock_squashfs_readonly") is True,
    }
    verification = {
        "run": str(run.resolve()),
        "serial_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "original_runner_status": original["status"],
        "original_runner_failure": original.get("error"),
        "checker_false_negative": original.get("simpledrm_kms_mode") is False
        and all(proofs.values()),
        "proofs": proofs,
        "verified": all(proofs.values()),
        "limitations": [
            "KMS enumeration does not prove the panel visibly scanned out pixels.",
            "This is a kexec display handoff; cold-boot display setup remains untested.",
        ],
    }
    (run / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps(verification, indent=2))
    return 0 if verification["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
