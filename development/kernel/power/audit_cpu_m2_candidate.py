#!/usr/bin/env python3
"""Independently audit the RAM-only 350/700 MHz clock-divider image."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import stat
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = ROOT / "development/perrier-ramenv/smp-boot-two"
DEST = ROOT / "development/perrier-ramenv/cpu-m2-trial"
THERMAL = HERE / "out/board.dtb"
sys.path.insert(0, str(ROOT / "development/kernel"))
from common import audit_archive, fdt_nodes, sha

CPU0 = "/cpus/cpu@0"
CPU1 = "/cpus/cpu@1"
M2 = "/ocp/interconnect@4a000000/segment@0/target-module@4000/cm1@0/clocks/dpll_mpu_m2_ck@170"
DPLL = "/ocp/interconnect@4a000000/segment@0/target-module@4000/cm1@0/clocks/dpll_mpu_ck@160"
TABLE = "/opp-table-cpu"


def config(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def cell(data: bytes) -> int:
    assert len(data) == 4
    return struct.unpack(">I", data)[0]


def audit_dtb(candidate: Path) -> dict:
    old, new = fdt_nodes(THERMAL.read_bytes()), fdt_nodes(candidate.read_bytes())
    added = {TABLE, TABLE + "/opp-350000000", TABLE + "/opp-700000000"}
    assert set(new) - set(old) == added
    assert not set(old) - set(new)
    old_handles = {cell(props["phandle"]): path for path, props in old.items()
                   if "phandle" in props}
    new_handles = {cell(props["phandle"]): path for path, props in new.items()
                   if "phandle" in props}
    renumber = {value: next(k for k, v in new_handles.items() if v == path)
                for value, path in old_handles.items()}
    assert old_handles[cell(old[CPU0]["clocks"])] == DPLL
    assert new_handles[cell(new[CPU0]["clocks"])] == M2
    assert new_handles[cell(new[CPU0]["operating-points-v2"])] == TABLE
    assert new_handles[cell(new[CPU1]["operating-points-v2"])] == TABLE
    assert "phandle" not in old[M2] and new_handles[cell(new[M2]["phandle"])] == M2
    assert "ti,set-rate-parent" not in new[M2]
    assert new[M2]["compatible"] == b"ti,divider-clock\0"
    assert new_handles[cell(new[M2]["clocks"])] == DPLL
    assert "cpu-supply" not in new[CPU0] and "cpu-supply" not in new[CPU1]
    assert "operating-points" not in new[CPU0]
    assert new[TABLE]["compatible"] == b"operating-points-v2\0"
    assert new[TABLE]["opp-shared"] == b""
    assert set(new[TABLE]) == {"compatible", "opp-shared", "phandle"}
    for frequency in (350000000, 700000000):
        node = new[f"{TABLE}/opp-{frequency}"]
        assert node == {"opp-hz": struct.pack(">Q", frequency)}
    # Everything except the intentional CPU references and M2 phandle must
    # survive the source recompilation unchanged, modulo DTC phandle numbers.
    expected_extra = {CPU0: {"operating-points-v2"},
                      CPU1: {"operating-points-v2"}, M2: {"phandle"}}
    for path, before in old.items():
        after = new[path]
        assert set(after) - set(before) == expected_extra.get(path, set()), path
        assert not set(before) - set(after), path
        for name, value in before.items():
            if path == CPU0 and name == "clocks":
                continue
            updated = after[name]
            if value == updated:
                continue
            assert len(value) == len(updated) and len(value) % 4 == 0, (path, name)
            old_words = struct.unpack(">" + "I" * (len(value) // 4), value)
            new_words = struct.unpack(">" + "I" * (len(value) // 4), updated)
            assert all(x == y or renumber.get(x) == y
                       for x, y in zip(old_words, new_words)), (path, name)
    for path in ("/thermal-zones/cpu_thermal/trips/cpu_alert",
                 "/thermal-zones/cpu_thermal/trips/cpu_crit"):
        assert new[path]["temperature"] == old[path]["temperature"]
    return {"base_dtb_sha256": sha(THERMAL), "candidate_dtb_sha256": sha(candidate),
            "added_nodes": sorted(added), "cpu_clock": M2,
            "opp_hz": [350000000, 700000000], "voltage_control": False}


def main() -> None:
    previous = json.loads((BASE / "reviewed-image.json").read_text())
    manifest = json.loads((DEST / "manifest.json").read_text())
    proof = json.loads((ROOT / "development/perrier-ramenv/native-watchdog/watchdog-proof.json").read_text())
    assert previous["passed"] and previous["kernel"] == "6.18.48-perrier-ram110"
    assert manifest["kernel"] == "6.18.48-perrier-ram112"
    assert manifest["profile"] == "cpu-m2-trial" and manifest["live_tested"] is False
    assert proof["status"] == "passed" and proof["stock_recovered"]
    assert proof["guard_sha256"] == previous["guard_sha256"] == manifest["guard_sha256"]
    for item in list(manifest["artifacts"].values()) + list(manifest["inputs"].values()):
        path = Path(item["path"])
        assert sha(path) == item["sha256"]
        if "size" in item:
            assert path.stat().st_size == item["size"]
    patches = json.loads((ROOT / "development/kernel/patches/manifest.json").read_text())
    source = ROOT / "development/kernel/source"
    work = ROOT / "development/kernel/work/linux-6.18.48"
    for name, item in patches["files"].items():
        assert sha(source / name) == sha(work / name) == item["after_sha256"], name
    for key, path in {
        "rootfs_manifest_sha256": DEST / "rootfs-manifest.json",
        "initramfs_sha256": DEST / "initramfs.cpio",
        "kernel_config_sha256": DEST / "kernel-build/.config",
        "guard_sha256": DEST / "rootfs/usr/sbin/ram-guard",
    }.items():
        assert sha(path) == manifest[key], key
    old = config(BASE / "kernel-build/.config")
    new = config(DEST / "kernel-build/.config")
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    expected = {
        "CONFIG_CMDLINE", "CONFIG_CPUFREQ_DT", "CONFIG_CPUFREQ_DT_PLATDEV",
        "CONFIG_CPU_FREQ", "CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE",
        "CONFIG_CPU_FREQ_GOV_PERFORMANCE", "CONFIG_CPU_FREQ_GOV_USERSPACE",
        "CONFIG_CPU_FREQ_STAT", "CONFIG_INITRAMFS_SOURCE", "CONFIG_LOCALVERSION",
    }
    assert changed == expected, sorted(changed ^ expected)
    assert new["CONFIG_CMDLINE"] == old["CONFIG_CMDLINE"][:-1] + " maxcpus=1\""
    assert new["CONFIG_CMDLINE_FORCE"] == "y"
    assert new["CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE"] == "y"
    assert new["CONFIG_CPU_FREQ_GOV_USERSPACE"] == "y"
    for key in ("CONFIG_ARM_OMAP2PLUS_CPUFREQ", "CONFIG_ARM_TI_CPUFREQ",
                "CONFIG_POWER_AVS_OMAP", "CONFIG_REGULATOR_TWL4030",
                "CONFIG_REGULATOR_TWL6030"):
        assert new.get(key) != "y", key
    for key in ("CONFIG_OMAP_WATCHDOG", "CONFIG_WATCHDOG_NOWAYOUT",
                "CONFIG_SMP", "CONFIG_HOTPLUG_CPU"):
        assert new[key] == "y", key
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
    assert startup.count("ram110") == 2
    assert (DEST / "rootfs/etc/init.d/rcS").read_text() == startup.replace("ram110", "ram112")
    assert stat.S_IMODE((DEST / "rootfs/etc/init.d/rcS").stat().st_mode) == 0o755
    audit_archive(DEST / "initramfs.cpio", entries)
    packed = (DEST / "kernel-build/usr/initramfs_inc_data").read_bytes()
    assert gzip.decompress(packed) == (DEST / "initramfs.cpio").read_bytes()
    assert packed in (DEST / "kernel-build/vmlinux").read_bytes()
    symbols = (DEST / "kernel-build/System.map").read_text().splitlines()
    image_end = next(int(line.split()[0], 16) for line in symbols if line.endswith(" _end"))
    span = image_end - 0xc0000000
    assert 0 < span < 0x02000000
    dtb = audit_dtb(DEST / "board.dtb")
    review = dict(manifest, passed=True, kernel_span_bytes=span,
                  changed_rootfs=["etc/init.d/rcS"],
                  changed_config=sorted(changed), dtb_audit=dtb,
                  thermal_trip_preserved=True, watchdog_proof_preserved=True,
                  stock_boot_fallback_preserved=True,
                  voltage_control_enabled=False)
    (DEST / "reviewed-image.json").write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps({"passed": True, "kernel": review["kernel"],
                      "kernel_span_bytes": span, "dtb_audit": dtb,
                      "changed_config": sorted(changed)}, indent=2))


if __name__ == "__main__":
    main()
