#!/usr/bin/env python3
"""Compare one CPU-bound worker at 700 and 350 MHz in ram112."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

REMOTE = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram112
test "$(cat /sys/devices/system/cpu/cpu1/online)" = 0
policy=/sys/devices/system/cpu/cpufreq/policy0
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/scaling_cur_freq")" = 700000
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
worker=
restore() {
    if [ -n "$worker" ]; then kill "$worker" 2>/dev/null || true; wait "$worker" 2>/dev/null || true; fi
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
sample() {
    echo "SAMPLE $1"
    echo "FREQ $(cat "$policy/scaling_cur_freq")"
    echo "THERMAL $(cat /sys/class/thermal/thermal_zone0/temp)"
    awk '$1 == "dpll_mpu_ck" || $1 == "dpll_mpu_m2_ck" || $1 == "mpuss-clkctrl:0000:0" {print "CLOCK " $1 " " $5}' /sys/kernel/debug/clk/clk_summary
    for chip in /sys/class/hwmon/hwmon*; do
        test -r "$chip/name" || continue
        test "$(cat "$chip/name")" = ina3221 || continue
        device=$(readlink -f "$chip/device")
        for channel in 1 2 3; do
            voltage=$(cat "$chip/in${channel}_input")
            current=$(cat "$chip/curr${channel}_input")
            echo "POWER $device channel=$channel millivolt=$voltage milliamp=$current"
        done
    done
    echo "UPTIME $(cat /proc/uptime)"
}
echo userspace > "$policy/scaling_governor"
yes > /dev/null &
worker=$!
sleep 8
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
test "$(cat "$policy/scaling_cur_freq")" = 700000
sample high_load
echo 350000 > "$policy/scaling_setspeed"
sleep 8
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
test "$(cat "$policy/scaling_cur_freq")" = 350000
sample low_load
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 700000
sample restored
echo CPU_M2_LOAD_PASS
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    review_path = ROOT / "development/perrier-ramenv/cpu-m2-trial/reviewed-image.json"
    review = json.loads(review_path.read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram112"
    if not args.execute:
        print("RAM load comparison ready")
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    result = ram.remote(REMOTE, timeout=45)
    finished = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-m2-load")
    directory.mkdir(mode=0o700)
    (directory / "command.sh").write_text(REMOTE)
    (directory / "stdout.log").write_text(result.stdout)
    (directory / "stderr.log").write_text(result.stderr)
    passed = result.returncode == 0 and "CPU_M2_LOAD_PASS" in result.stdout
    lines = result.stdout.splitlines()
    assert result.returncode != 0 or [line for line in lines if line.startswith("SAMPLE ")] == [
        "SAMPLE high_load", "SAMPLE low_load", "SAMPLE restored"]
    report = {"passed": passed, "kernel": review["kernel"], "boot_id": state["boot_id"],
              "review_sha256": sha(review_path), "started": started.isoformat(),
              "finished": finished.isoformat(), "returncode": result.returncode,
              "stdout_sha256": sha(directory / "stdout.log"),
              "stderr_sha256": sha(directory / "stderr.log")}
    (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"run": str(directory), **report}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
