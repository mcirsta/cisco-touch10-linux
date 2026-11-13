#!/usr/bin/env python3
"""Compare read-only OMAP VC/VP words in a ram113 700/350 MHz session.

The pinned helper maps one PRM page read-only. This script changes only the
already-qualified M2 clock temporarily and never issues a voltage command.
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
DIAGNOSTICS = ROOT / "development/kernel/diagnostics"
HELPER = DIAGNOSTICS / "omap4_prm_power_read.arm"
REVIEW = DIAGNOSTICS / "omap4-prm-power-read-review.json"
TEMP = "/tmp/perrier-omap4-prm-power-read"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DIAGNOSTICS))
import touch10_ram as ram
from analyze_omap4_prm_power import decode
from audit_omap4_prm_power_read import EXPECTED


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(script: str, timeout: int = 12) -> str:
    result = ram.remote(script, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"RAM SSH command failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    binary = HELPER.read_bytes()
    review = json.loads(REVIEW.read_text())
    assert review["passed"] and review["binary_size"] == len(binary) == 45244
    assert sha(binary) == review["binary_sha256"]
    if not args.execute:
        print(json.dumps({"ready": True, "helper_sha256": sha(binary),
                          "register_count": len(EXPECTED), "voltage_command": False}, indent=2))
        return
    state = ram.ram_state("6.18.48-perrier-ram113")
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    assert state["guard"]["timeout_seconds"] == 120
    checked('''set -eu
test "$(awk '$2 == "/tmp" {print $3}' /proc/mounts)" = tmpfs
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test "$(cat /sys/block/mmcblk0/ro)" = 1
test ! -e /tmp/perrier-omap4-prm-power-read
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor)" = performance
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq)" = 700000
''')
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-ram113-prm-read")
    directory.mkdir(mode=0o700)
    uploaded = False
    try:
        transfer = subprocess.run(ram.SSH + ["umask 077; cat > " + TEMP],
                                  input=binary, capture_output=True, timeout=20)
        if transfer.returncode:
            raise RuntimeError("RAM helper upload failed: " + transfer.stderr.decode(errors="replace"))
        uploaded = True
        readback = subprocess.run(ram.SSH + ["cat " + TEMP], capture_output=True, timeout=20)
        if readback.returncode or readback.stdout != binary:
            raise RuntimeError("RAM helper readback differs from the pinned binary")
        checked("chmod 700 " + TEMP + "\n")
        command = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram113
test "$(cat /sys/devices/system/cpu/online)" = 0-1
policy=/sys/devices/system/cpu/cpufreq/policy0
restore() {
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
sample() {
    echo "BEGIN $1"
    /tmp/perrier-omap4-prm-power-read
    echo "FREQ $(cat "$policy/scaling_cur_freq")"
    echo "TEMP $(cat /sys/class/thermal/thermal_zone0/temp)"
    for chip in /sys/class/hwmon/hwmon*; do
        test -r "$chip/name" || continue
        test "$(cat "$chip/name")" = ina3221 || continue
        case "$(readlink -f "$chip/device")" in *3-0041)
            echo "INA1 $(cat "$chip/in1_input") $(cat "$chip/curr1_input")"
            echo "INA3 $(cat "$chip/in3_input") $(cat "$chip/curr3_input")"
            ;;
        esac
    done
    echo "END $1"
}
sample before
echo userspace > "$policy/scaling_governor"
echo 350000 > "$policy/scaling_setspeed"
sleep 3
test "$(cat "$policy/scaling_cur_freq")" = 350000
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
sample low
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 700000
sample restored
echo performance > "$policy/scaling_governor"
echo PRM_RAM_READ_PASS
'''
        (directory / "command.sh").write_text(command)
        result = ram.remote(command, timeout=25)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("PRM_RAM_READ_PASS\n"):
            raise RuntimeError("RAM PRM read failed; see captured stdout/stderr")
        stages: dict[str, list[str]] = {}
        active = None
        for line in result.stdout.splitlines():
            if line.startswith("BEGIN "):
                active = line.split()[1]
                assert active not in stages
                stages[active] = []
            elif line.startswith("END "):
                assert active == line.split()[1]
                active = None
            elif active:
                stages[active].append(line)
        assert list(stages) == ["before", "low", "restored"] and active is None
        decoded = {}
        for name, lines in stages.items():
            raw = [line for line in lines if line.count(",") == 2]
            assert len(raw) == len(EXPECTED)
            path = directory / (name + "-prm-raw.csv")
            path.write_text("\n".join(raw) + "\n")
            detail = decode(path)
            (directory / (name + "-prm-decoded.json")).write_text(json.dumps(detail, indent=2) + "\n")
            summary = {"freq_khz": int(next(x.split()[1] for x in lines if x.startswith("FREQ "))),
                       "temp_mc": int(next(x.split()[1] for x in lines if x.startswith("TEMP "))),
                       "ina1_mv_ma": [int(v) for v in next(x.split()[1:] for x in lines if x.startswith("INA1 "))],
                       "ina3_mv_ma": [int(v) for v in next(x.split()[1:] for x in lines if x.startswith("INA3 "))],
                       "mpu_vp_selector": detail["domains"]["mpu"]["vp_current_selector"],
                       "mpu_vp_enabled": detail["domains"]["mpu"]["vp_enabled"],
                       "vc_map_matches_cisco": detail["expected_cisco_twl6032_address_map_matches"]}
            decoded[name] = summary
        assert [decoded[k]["freq_khz"] for k in decoded] == [700000, 350000, 700000]
        assert all(v["temp_mc"] < 80000 for v in decoded.values())
        assert all(v["vc_map_matches_cisco"] for v in decoded.values())
        (directory / "result.json").write_text(json.dumps({"passed": True,
            "boot_id": state["boot_id"], "helper_sha256": sha(binary),
            "started": started.isoformat(), "finished": datetime.now(timezone.utc).isoformat(),
            "voltage_commanded": False, "stages": decoded}, indent=2) + "\n")
        print(json.dumps({"run": str(directory), "passed": True, "stages": decoded}, indent=2))
    finally:
        if uploaded:
            checked("rm -f " + TEMP + "\ntest ! -e " + TEMP + "\n")


if __name__ == "__main__":
    main()
