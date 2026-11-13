#!/usr/bin/env python3
"""Independently audit ram116's lower OPP, boot image and recovery."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import stat
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "development/kernel/work/linux-6.18.48-ram116"
ORIGINAL_SRC = ROOT / "development/kernel/work/linux-6.18.48"
BASE = ROOT / "development/perrier-ramenv/cpu-dvfs-trial"
DEST = ROOT / "development/perrier-ramenv/cpu-dvfs-mid-trial"
sys.path.insert(0, str(ROOT / "development/kernel"))
from common import audit_archive, fdt_nodes, sha


def config(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def cell(raw: bytes) -> int:
    assert len(raw) == 4
    return struct.unpack(">I", raw)[0]


def audit_dtb() -> dict:
    old = fdt_nodes((BASE / "board.dtb").read_bytes())
    new = fdt_nodes((DEST / "board.dtb").read_bytes())
    supply = "/regulator@4a306000"
    assert set(new) == set(old)
    props = new[supply]
    assert props["compatible"] == b"cisco,perrier-omap4-mpu-vc\0"
    assert props["reg"] == struct.pack(">II", 0x4a306000, 0x2000)
    assert props["regulator-name"] == b"perrier-vdd-mpu\0"
    assert cell(props["regulator-min-microvolt"]) == 1152100
    assert cell(props["regulator-max-microvolt"]) == 1215400
    assert props["regulator-always-on"] == b""
    assert set(props) == set(old[supply])
    new_handles = {cell(p["phandle"]): path for path, p in new.items()
                   if "phandle" in p}
    for cpu in ("/cpus/cpu@0", "/cpus/cpu@1"):
        assert new_handles[cell(new[cpu]["cpu-supply"])] == supply
    for hz, uv in ((350000000, 1152100), (700000000, 1215400)):
        path = f"/opp-table-cpu/opp-{hz}"
        assert cell(new[path]["opp-microvolt"]) == uv
        assert new[path]["opp-hz"] == old[path]["opp-hz"] == struct.pack(">Q", hz)
    changed = {(path, key) for path in old for key in old[path]
               if old[path][key] != new[path][key]}
    assert changed == {(supply, "regulator-min-microvolt"),
                       ("/opp-table-cpu/opp-350000000", "opp-microvolt")}
    assert all(set(old[path]) == set(new[path]) for path in old)
    return {"candidate_mpu_selectors": [0x24, 0x29],
            "opp_hz_uv": [[350000000, 1152100], [700000000, 1215400]],
            "unrelated_dt_properties_preserved": True}


def main() -> None:
    base = json.loads((BASE / "reviewed-image.json").read_text())
    manifest = json.loads((DEST / "manifest.json").read_text())
    assert base["passed"] and base["kernel"] == "6.18.48-perrier-ram114"
    assert manifest["kernel"] == "6.18.48-perrier-ram116"
    assert manifest["profile"] == "cpu-dvfs-mid-trial" and not manifest["live_tested"]
    for item in list(manifest["artifacts"].values()) + list(manifest["inputs"].values()):
        path = Path(item["path"])
        assert sha(path) == item["sha256"], path
        if "size" in item:
            assert path.stat().st_size == item["size"], path
    low = json.loads(Path(manifest["inputs"]["low_probe_result"]["path"]).read_text())
    assert low["passed"] and [s["selector"] for s in low["stages"]] == ["0x24", "0x24", "0x20", "0x20"]
    assert all(s["measured_drop_millivolts"] >= 20 for s in low["stages"][:2])
    recovery = json.loads(Path(manifest["inputs"]["low_probe_recovery"]["path"]).read_text())
    assert recovery["status"] == "passed" and recovery["stock_recovered"]
    assert recovery["adc_postflight"]["passed"]
    assert recovery["stock_p8_sha256"] == "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad"
    power = json.loads(Path(manifest["inputs"]["power_baseline"]["path"]).read_text())
    assert power["passed"] and power["summary"]["sample_count"] == 96
    for name in ("rootfs_manifest_sha256", "initramfs_sha256",
                 "kernel_config_sha256", "guard_sha256"):
        file = {"rootfs_manifest_sha256": DEST / "rootfs-manifest.json",
                "initramfs_sha256": DEST / "initramfs.cpio",
                "kernel_config_sha256": DEST / "kernel-build/.config",
                "guard_sha256": DEST / "rootfs/usr/sbin/ram-guard"}[name]
        assert sha(file) == manifest[name]
    assert manifest["guard_sha256"] == base["guard_sha256"]
    old, new = config(BASE / "kernel-build/.config"), config(DEST / "kernel-build/.config")
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    assert changed == {"CONFIG_LOCALVERSION", "CONFIG_INITRAMFS_SOURCE"}
    assert new["CONFIG_REGULATOR_CISCO_PERRIER_VC"] == "y"
    assert new.get("CONFIG_POWER_AVS_OMAP") != "y"
    assert new.get("CONFIG_HOTPLUG_CPU") != "y"
    assert new["CONFIG_OMAP_WATCHDOG"] == new["CONFIG_WATCHDOG_NOWAYOUT"] == "y"
    old_entries = json.loads((BASE / "rootfs-manifest.json").read_text())
    entries = json.loads((DEST / "rootfs-manifest.json").read_text())
    assert {name for name in old_entries if old_entries[name] != entries[name]} == {"etc/init.d/rcS"}
    for name, item in entries.items():
        path = DEST / "rootfs" / name
        if "symlink" in item:
            assert path.is_symlink() and str(path.readlink()) == item["symlink"]
        else:
            assert sha(path) == item["sha256"] and path.stat().st_size == item["bytes"]
    assert (DEST / "rootfs/etc/init.d/rcS").read_text() == \
        (BASE / "rootfs/etc/init.d/rcS").read_text().replace("ram114", "ram116")
    assert stat.S_IMODE((DEST / "rootfs/etc/init.d/rcS").stat().st_mode) == 0o755
    audit_archive(DEST / "initramfs.cpio", entries)
    packed = (DEST / "kernel-build/usr/initramfs_inc_data").read_bytes()
    assert gzip.decompress(packed) == (DEST / "initramfs.cpio").read_bytes()
    assert packed in (DEST / "kernel-build/vmlinux").read_bytes()
    symbols = (DEST / "kernel-build/System.map").read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(" _end"))
    span = image_end - 0xc0000000
    assert 0 < span < 0x02000000
    assert any(line.endswith(" perrier_vc_probe") for line in symbols)
    source = (SRC / "drivers/regulator/cisco-perrier-vc.c").read_text()
    assert "!(observed & VC_VALID)" in source
    assert "(status & VC_STATUS) != VC_ACK" in source
    assert "VC_COMMAND(perrier_mpu_selectors[selector])" in source
    assert "1152100, /* TWL6032 selector 0x24" in source
    assert "static const unsigned int perrier_mpu_selectors[] = { 0x24, 0x29 };" in source
    assert "perrier_vc_state_valid(vc)" in source
    assert "selector >= ARRAY_SIZE(perrier_mpu_voltages)" in source
    original = (ORIGINAL_SRC / "drivers/regulator/cisco-perrier-vc.c").read_text()
    expected = original.replace(
        "1202740, /* TWL6032 selector 0x28, tested at 700 MHz */",
        "1152100, /* TWL6032 selector 0x24, two-second 350 MHz probe passed */"
    ).replace(
        "static bool perrier_vc_state_valid",
        "static const unsigned int perrier_mpu_selectors[] = { 0x24, 0x29 };\n\nstatic bool perrier_vc_state_valid"
    ).replace(
        "VC_COMMAND(selector + 0x28)", "VC_COMMAND(perrier_mpu_selectors[selector])"
    ).replace(
        "selector + 0x28, observed, status, ret", "perrier_mpu_selectors[selector], observed, status, ret"
    )
    assert expected == source
    for name in ("Kconfig", "Makefile"):
        assert sha(SRC / "drivers/regulator" / name) == sha(ORIGINAL_SRC / "drivers/regulator" / name)
    dtb = audit_dtb()
    review = dict(manifest, passed=True, changed_config=sorted(changed),
                  changed_rootfs=["etc/init.d/rcS"], kernel_span_bytes=span,
                  dtb_audit=dtb, mpu_voltage_provider=True,
                  generic_omap_pm_late_init_still_blacklisted=True,
                  watchdog_and_factory_recovery_preserved=True)
    (DEST / "reviewed-image.json").write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps({"passed": True, "kernel": review["kernel"],
                      "kernel_span_bytes": span, "dtb_audit": dtb}, indent=2))


if __name__ == "__main__":
    main()
