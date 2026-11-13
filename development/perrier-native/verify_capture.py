#!/usr/bin/env python3
"""Validate the ram24 run after the runner's one-version parser error."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    result = json.loads((run / "result.json").read_text())
    serial = (run / "serial.raw").read_bytes()
    markers = (
        b"PERRIER_INIT_ENTER ram24",
        b"PERRIER_DRM_CONNECTOR id=61 connection=1 modes=1 encoders=1",
        b"PERRIER_DRM_MODE name=1280x800 width=1280 height=800 refresh=60",
        b"DSI2LVDS Chip ID.65 Revision ID. 00",
        b"PERRIER_PATTERN_SETCRTC_OK",
        b"PERRIER_PATTERN_WINDOW_END",
        b"PERRIER_PATTERN_EXIT status=0",
        b"PERRIER_SOFT_REBOOT_REQUESTED",
    )
    checks = {m.decode(): m in serial for m in markers}
    checks.update({
        "stock_recovered": result.get("stock_recovered") is True,
        "stock_kernel": result.get("after", {}).get("kernel") == "3.4.113+",
        "phoenix_running": result.get("after", {}).get("factory_app") == "running",
        "boot_id_changed": result.get("before", {}).get("boot_id") != result.get("after", {}).get("boot_id"),
        "uboot_environment_unchanged": result.get("environment_before") == result.get("environment_after"),
        "watchdog_running": result.get("watchdog_counter_delta", 0) > 0,
        "eMMC_readonly": (b"PERRIER_BASE_RDONLY result=0 ro=1 errno=0" in serial and
                          all(f"PERRIER_SQUASH_MOUNT name={name} result=0 errno=0 loop_ro=1 fs_ro=1".encode() in serial
                              for name in ("extra", "gui", "apps"))),
        "native_card": result.get("native_drm_card_seen") is True,
    })
    report = {
        "passed": all(checks.values()),
        "scope": "driver modeset and recovery; visible pixels require user observation",
        "original_runner_error": "kernel_init_ready parser omitted ram24",
        "checks": checks,
    }
    (run / "offline-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
