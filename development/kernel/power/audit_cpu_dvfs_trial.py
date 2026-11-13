#!/usr/bin/env python3
"""Independently audit ram114's regulator, OPP, boot image and recovery."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import stat
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "development/kernel/work/linux-6.18.48"
BASE = ROOT / "development/perrier-ramenv/cpu-m2-smp-safe"
DEST = ROOT / "development/perrier-ramenv/cpu-dvfs-trial"
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
    assert set(new) - set(old) == {supply}
    assert not set(old) - set(new)
    props = new[supply]
    assert props["compatible"] == b"cisco,perrier-omap4-mpu-vc\0"
    assert props["reg"] == struct.pack(">II", 0x4a306000, 0x2000)
    assert props["regulator-name"] == b"perrier-vdd-mpu\0"
    assert cell(props["regulator-min-microvolt"]) == 1202740
    assert cell(props["regulator-max-microvolt"]) == 1215400
    assert props["regulator-always-on"] == b""
    assert set(props) == {"compatible", "reg", "regulator-name",
                          "regulator-min-microvolt", "regulator-max-microvolt",
                          "regulator-always-on", "phandle"}
    old_handles = {cell(p["phandle"]): path for path, p in old.items()
                   if "phandle" in p}
    new_handles = {cell(p["phandle"]): path for path, p in new.items()
                   if "phandle" in p}
    renumber = {handle: next(k for k, path in new_handles.items() if path == name)
                for handle, name in old_handles.items()}
    for cpu in ("/cpus/cpu@0", "/cpus/cpu@1"):
        assert "cpu-supply" not in old[cpu]
        assert new_handles[cell(new[cpu]["cpu-supply"])] == supply
    for hz, uv in ((350000000, 1202740), (700000000, 1215400)):
        path = f"/opp-table-cpu/opp-{hz}"
        assert "opp-microvolt" not in old[path]
        assert cell(new[path]["opp-microvolt"]) == uv
        assert new[path]["opp-hz"] == old[path]["opp-hz"] == struct.pack(">Q", hz)
    expected_extra = {"/cpus/cpu@0": {"cpu-supply"},
                      "/cpus/cpu@1": {"cpu-supply"},
                      "/opp-table-cpu/opp-350000000": {"opp-microvolt"},
                      "/opp-table-cpu/opp-700000000": {"opp-microvolt"}}
    for path, before in old.items():
        after = new[path]
        assert set(after) - set(before) == expected_extra.get(path, set()), path
        assert not set(before) - set(after), path
        for key, value in before.items():
            updated = after[key]
            if value == updated:
                continue
            assert len(value) == len(updated) and len(value) % 4 == 0, (path, key)
            a = struct.unpack(">" + "I" * (len(value) // 4), value)
            b = struct.unpack(">" + "I" * (len(updated) // 4), updated)
            assert all(x == y or renumber.get(x) == y for x, y in zip(a, b)), (path, key)
    return {"qualified_mpu_selectors": [0x28, 0x29],
            "opp_hz_uv": [[350000000, 1202740], [700000000, 1215400]],
            "unrelated_dt_properties_preserved": True}


def main() -> None:
    base = json.loads((BASE / "reviewed-image.json").read_text())
    manifest = json.loads((DEST / "manifest.json").read_text())
    assert base["passed"] and manifest["kernel"] == "6.18.48-perrier-ram114"
    assert manifest["profile"] == "cpu-dvfs-trial" and not manifest["live_tested"]
    for item in list(manifest["artifacts"].values()) + list(manifest["inputs"].values()):
        path = Path(item["path"])
        assert sha(path) == item["sha256"], path
        if "size" in item:
            assert path.stat().st_size == item["size"], path
    for name in ("vc_idle_recovery", "vc_loaded_recovery"):
        recovery = json.loads(Path(manifest["inputs"][name]["path"]).read_text())
        assert recovery["status"] == "passed" and recovery["stock_recovered"]
        assert recovery["adc_postflight"]["passed"]
        assert recovery["stock_p8_sha256"] == "f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad"
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
    assert changed == {"CONFIG_LOCALVERSION", "CONFIG_INITRAMFS_SOURCE",
                       "CONFIG_REGULATOR_CISCO_PERRIER_VC"}
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
        (BASE / "rootfs/etc/init.d/rcS").read_text().replace("ram113", "ram114")
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
    assert "VC_COMMAND(selector + 0x28)" in source
    assert "perrier_vc_state_valid(vc)" in source
    assert "selector >= ARRAY_SIZE(perrier_mpu_voltages)" in source
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
