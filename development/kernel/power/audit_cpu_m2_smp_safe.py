#!/usr/bin/env python3
"""Independently audit the two-core, no-hotplug RAM CPUfreq image."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "development/perrier-ramenv/cpu-m2-trial"
DEST = ROOT / "development/perrier-ramenv/cpu-m2-smp-safe"
sys.path.insert(0, str(ROOT / "development/kernel"))
from common import audit_archive, sha


def config(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def main() -> None:
    base = json.loads((BASE / "reviewed-image.json").read_text())
    manifest = json.loads((DEST / "manifest.json").read_text())
    observed = json.loads((ROOT / "development/kernel/validation-cpu-m2-trial.json").read_text())
    assert base["passed"] and base["kernel"] == "6.18.48-perrier-ram112"
    assert observed["clock_transition"]["passed"] and not observed["hotplug_cleanup"]["passed"]
    assert manifest["profile"] == "cpu-m2-smp-safe"
    assert manifest["kernel"] == "6.18.48-perrier-ram113" and not manifest["live_tested"]
    assert not manifest["voltage_policy"].startswith("variable")
    assert sha(DEST / "board.dtb") == sha(BASE / "board.dtb")
    for item in list(manifest["artifacts"].values()) + list(manifest["inputs"].values()):
        path = Path(item["path"])
        assert sha(path) == item["sha256"]
        if "size" in item:
            assert path.stat().st_size == item["size"]
    for key, path in {
        "rootfs_manifest_sha256": DEST / "rootfs-manifest.json",
        "initramfs_sha256": DEST / "initramfs.cpio",
        "kernel_config_sha256": DEST / "kernel-build/.config",
        "guard_sha256": DEST / "rootfs/usr/sbin/ram-guard",
    }.items():
        assert sha(path) == manifest[key], key
    assert manifest["guard_sha256"] == base["guard_sha256"]
    old, new = config(BASE / "kernel-build/.config"), config(DEST / "kernel-build/.config")
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    expected = {
        "CONFIG_CMDLINE", "CONFIG_INITRAMFS_SOURCE", "CONFIG_LOCALVERSION",
        "CONFIG_HOTPLUG_CPU", "CONFIG_HOTPLUG_CORE_SYNC",
        "CONFIG_HOTPLUG_CORE_SYNC_DEAD", "CONFIG_GENERIC_IRQ_MIGRATION",
        "CONFIG_CPU_FREQ_GOV_ATTR_SET", "CONFIG_CPU_FREQ_GOV_SCHEDUTIL",
    }
    assert changed == expected, sorted(changed ^ expected)
    assert old["CONFIG_CMDLINE"].endswith(" maxcpus=1\"")
    assert new["CONFIG_CMDLINE"] == old["CONFIG_CMDLINE"].replace(" maxcpus=1\"", "\"")
    assert "maxcpus=" not in new["CONFIG_CMDLINE"]
    assert new["CONFIG_CMDLINE_FORCE"] == "y"
    assert new.get("CONFIG_HOTPLUG_CPU") != "y"
    assert new["CONFIG_SMP"] == "y"
    assert new["CONFIG_CPUFREQ_DT"] == "y"
    assert new["CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE"] == "y"
    assert new["CONFIG_CPU_FREQ_GOV_USERSPACE"] == "y"
    assert new["CONFIG_CPU_FREQ_GOV_SCHEDUTIL"] == "y"
    for key in ("CONFIG_ARM_OMAP2PLUS_CPUFREQ", "CONFIG_ARM_TI_CPUFREQ",
                "CONFIG_POWER_AVS_OMAP", "CONFIG_REGULATOR_TWL4030",
                "CONFIG_REGULATOR_TWL6030"):
        assert new.get(key) != "y", key
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
    startup = (BASE / "rootfs/etc/init.d/rcS").read_text()
    assert startup.count("ram112") == 2
    assert (DEST / "rootfs/etc/init.d/rcS").read_text() == startup.replace("ram112", "ram113")
    assert stat.S_IMODE((DEST / "rootfs/etc/init.d/rcS").stat().st_mode) == 0o755
    audit_archive(DEST / "initramfs.cpio", entries)
    packed = (DEST / "kernel-build/usr/initramfs_inc_data").read_bytes()
    assert gzip.decompress(packed) == (DEST / "initramfs.cpio").read_bytes()
    assert packed in (DEST / "kernel-build/vmlinux").read_bytes()
    symbols = (DEST / "kernel-build/System.map").read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(" _end"))
    span = image_end - 0xc0000000
    assert 0 < span < 0x02000000
    review = dict(manifest, passed=True, kernel_span_bytes=span,
                  changed_rootfs=["etc/init.d/rcS"], changed_config=sorted(changed),
                  board_dtb_identical_to_ram112=True, two_cpus_boot_enabled=True,
                  runtime_cpu_hotplug_disabled=True, schedutil_available_but_not_default=True,
                  watchdog_proof_preserved=True, stock_boot_fallback_preserved=True,
                  voltage_control_enabled=False)
    (DEST / "reviewed-image.json").write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps({"passed": True, "kernel": review["kernel"],
                      "kernel_span_bytes": span, "changed_config": sorted(changed)}, indent=2))


if __name__ == "__main__":
    main()
