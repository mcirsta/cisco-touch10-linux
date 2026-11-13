#!/usr/bin/env python3
"""Build and audit a DT-only thermal candidate from frozen ram110.

This script never connects to the Touch 10. It deliberately leaves the
validated zImage, initramfs, source patches and U-Boot profiles unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = ROOT / "development/perrier-ramenv/smp-boot-two"
PROFILE = ROOT / "development/perrier-ramenv/thermal-policy"
KERNEL = ROOT / "development/sources/linux-6.18.48"
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "development/perrier-simpledrm"))
from audit import fdt_nodes


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def run(*argv: object) -> None:
    subprocess.run([str(x) for x in argv], check=True)


def main() -> None:
    os.umask(0o077)
    manifest = json.loads((BASE / "manifest.json").read_text())
    review = json.loads((BASE / "reviewed-image.json").read_text())
    assert manifest["kernel"] == review["kernel"] == "6.18.48-perrier-ram110"
    assert review["passed"] and manifest["profile"] == "smp-boot-two"
    for name in ("zImage", "board.dtb"):
        artifact = manifest["artifacts"][name]
        path = Path(artifact["path"])
        assert path.stat().st_size == artifact["size"]
        assert digest(path) == artifact["sha256"]

    cfg = config(BASE / "kernel-build/.config")
    assert digest(BASE / "kernel-build/.config") == manifest["kernel_config_sha256"]
    assert cfg["CONFIG_THERMAL"] == cfg["CONFIG_THERMAL_OF"] == "y"
    assert cfg["CONFIG_TI_SOC_THERMAL"] == cfg["CONFIG_TI_THERMAL"] == "y"
    assert cfg["CONFIG_OMAP_WATCHDOG"] == cfg["CONFIG_WATCHDOG_NOWAYOUT"] == "y"
    assert cfg["CONFIG_CMDLINE_FORCE"] == "y"
    assert "initcall_blacklist=omap2_common_pm_late_init" in cfg["CONFIG_CMDLINE"]
    for key in ("CONFIG_CPU_FREQ", "CONFIG_POWER_AVS_OMAP"):
        assert cfg.get(key) != "y", key

    OUT.mkdir(exist_ok=True)
    source = HERE / "omap4-cisco-perrier-thermal-ram.dts"
    preprocessed = OUT / "thermal-ram.pre.dts"
    candidate = OUT / "board.dtb"
    with preprocessed.open("w") as stream:
        subprocess.run([
            "cpp", "-x", "assembler-with-cpp", "-P", "-nostdinc",
            "-undef", "-D__DTS__",
            "-I", KERNEL / "include",
            "-I", KERNEL / "arch/arm/boot/dts/ti/omap",
            "-I", ROOT / "development/kernel/source/arch/arm/boot/dts/ti/omap",
            source,
        ], check=True, stdout=stream)
    run("dtc", "-q", "-I", "dts", "-O", "dtb",
        "-i", KERNEL / "arch/arm/boot/dts/ti/omap", "-o", candidate,
        preprocessed)

    old = fdt_nodes((BASE / "board.dtb").read_bytes())
    new = fdt_nodes(candidate.read_bytes())
    assert set(old) == set(new), "DT node set changed"
    differences = {(path, key): (old[path].get(key), new[path].get(key))
                   for path in old for key in old[path].keys() | new[path].keys()
                   if old[path].get(key) != new[path].get(key)}
    alert = "/thermal-zones/cpu_thermal/trips/cpu_alert"
    critical = "/thermal-zones/cpu_thermal/trips/cpu_crit"
    expected = {
        (alert, "temperature"): (struct.pack(">I", 100000),
                                  struct.pack(">I", 85000)),
        (critical, "temperature"): (struct.pack(">I", 125000),
                                     struct.pack(">I", 95000)),
    }
    assert differences == expected, differences
    assert new["/thermal-zones/cpu_thermal"].get("cooling-maps") is None
    assert new[critical]["type"] == b"critical\0"
    assert new[alert]["type"] == b"passive\0"
    assert new["/ocp/bandgap@4a002260"].get("status", b"okay\0") in (b"okay\0", b"ok\0")

    result = {
        "passed": True,
        "live_tested": False,
        "base_profile": "smp-boot-two",
        "kernel": manifest["kernel"],
        "zImage_sha256": manifest["artifacts"]["zImage"]["sha256"],
        "base_dtb_sha256": manifest["artifacts"]["board.dtb"]["sha256"],
        "candidate_dtb_sha256": digest(candidate),
        "source_sha256": digest(source),
        "critical_millicelsius": 95000,
        "passive_millicelsius": 85000,
        "changed_properties": [f"{path}:{key}" for path, key in sorted(differences)],
        "cpu_frequency_scaling_disabled": True,
        "power_averaging_disabled": True,
        "pm_late_init_blacklisted": True,
        "watchdog_nowayout_preserved": True,
        "persistent_device_state_unchanged": True,
    }
    (OUT / "review.json").write_text(json.dumps(result, indent=2) + "\n")
    PROFILE.mkdir(exist_ok=True)
    profile_review = {
        "kernel": manifest["kernel"],
        "profile": "thermal-policy",
        "artifacts": {
            "zImage": manifest["artifacts"]["zImage"],
            "board.dtb": {
                "path": str(candidate),
                "size": candidate.stat().st_size,
                "sha256": digest(candidate),
            },
        },
        "base_review_sha256": digest(BASE / "reviewed-image.json"),
        "thermal_review_sha256": digest(OUT / "review.json"),
        "guard_sha256": review["guard_sha256"],
        "kernel_span_bytes": review["kernel_span_bytes"],
        "passed": True,
        "live_tested": False,
    }
    (PROFILE / "reviewed-image.json").write_text(json.dumps(profile_review, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
