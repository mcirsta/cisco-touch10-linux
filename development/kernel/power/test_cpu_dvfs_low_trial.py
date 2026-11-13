#!/usr/bin/env python3
"""Bounded ram115 two-core 350/700 MHz voltage-and-clock transition."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

REMOTE = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram115
test "$(uname -r)" = 6.18.48-perrier-ram115
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test "$(cat /sys/block/mmcblk0/ro)" = 1
policy=/sys/devices/system/cpu/cpufreq/policy0
test "$(cat "$policy/scaling_driver")" = cpufreq-dt
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/scaling_cur_freq")" = 700000
test "$(cat "$policy/scaling_available_frequencies")" = '350000 700000 '
reg=''
for p in /sys/class/regulator/regulator*; do
    test -r "$p/name" || continue
    test "$(cat "$p/name")" = perrier-vdd-mpu || continue
    test -z "$reg"
    reg=$p
done
test -n "$reg"
test "$(cat "$reg/microvolts")" = 1215400
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 70000
workers=''
restore() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
sample() {
    echo "BEGIN $1"
    echo "CPUS $(cat /sys/devices/system/cpu/online)"
    echo "GOVERNOR $(cat "$policy/scaling_governor")"
    echo "FREQ $(cat "$policy/scaling_cur_freq")"
    echo "REGULATOR $(cat "$reg/microvolts")"
    echo "THERMAL $(cat /sys/class/thermal/thermal_zone0/temp)"
    awk '$1 == "dpll_mpu_ck" || $1 == "dpll_mpu_m2_ck" || $1 == "mpuss-clkctrl:0000:0" { print "CLOCK " $1 " " $5 }' /sys/kernel/debug/clk/clk_summary
    for chip in /sys/class/hwmon/hwmon*; do
        test -r "$chip/name" || continue
        test "$(cat "$chip/name")" = ina3221 || continue
        case "$(readlink -f "$chip/device")" in *3-0041)
            echo "INA1 $(cat "$chip/in1_input") $(cat "$chip/curr1_input")"
            echo "INA3 $(cat "$chip/in3_input") $(cat "$chip/curr3_input")"
            ;;
        esac
    done
    echo "GUARD $(cat /run/guard.json)"
    echo "END $1"
}
sample before
echo userspace > "$policy/scaling_governor"
echo 350000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 350000
test "$(cat "$reg/microvolts")" = 1101460
sample low_idle
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 20
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
test "$(cat "$reg/microvolts")" = 1101460
sample low_load
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 700000
test "$(cat "$reg/microvolts")" = 1215400
sample restored
echo performance > "$policy/scaling_governor"
sleep 1
sample final
if dmesg | grep -q 'VC bypass failed'; then exit 5; fi
echo CPU_DVFS_LOW_TRIAL_PASS
'''


def request_recovery() -> None:
    current = json.loads(ram.CURRENT.read_text())
    if current["status"] not in ("interactive", "recovering") or current["profile"] != "cpu-dvfs-low-trial":
        raise RuntimeError("No active ram115 runner for recovery")
    target = Path(current["directory"]) / "recover-request.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"mode": "cpu_dvfs_trial_complete"}) + "\n")
    os.replace(temp, target)


def parse(stdout: str) -> dict:
    stages: dict[str, dict] = {}
    active = None
    for line in stdout.splitlines():
        words = line.split()
        if words[:1] == ["BEGIN"]:
            active = words[1]
            stages[active] = {"clocks": {}}
        elif words[:1] == ["END"]:
            assert active == words[1]
            active = None
        elif active and words[:1] == ["CLOCK"]:
            stages[active]["clocks"][words[1]] = int(words[2])
        elif active and words[:1] == ["GUARD"]:
            stages[active]["guard"] = json.loads(line.removeprefix("GUARD "))
        elif active and words[:1] in (["FREQ"], ["REGULATOR"], ["THERMAL"]):
            stages[active][words[0].lower()] = int(words[1])
        elif active and words[:1] in (["INA1"], ["INA3"]):
            stages[active][words[0].lower()] = [int(words[1]), int(words[2])]
        elif active and words[:1] in (["GOVERNOR"], ["CPUS"]):
            stages[active][words[0].lower()] = words[1]
    assert list(stages) == ["before", "low_idle", "low_load", "restored", "final"] and active is None
    expected_freq = [700000, 350000, 350000, 700000, 700000]
    expected_uv = [1215400, 1101460, 1101460, 1215400, 1215400]
    for stage, freq, uv in zip(stages.values(), expected_freq, expected_uv):
        assert stage["cpus"] == "0-1" and stage["freq"] == freq
        assert stage["regulator"] == uv and stage["thermal"] < 80000
        assert stage["guard"]["state"] == "feeding" and stage["guard"]["nowayout"]
        assert stage["clocks"]["dpll_mpu_ck"] == 700000000
        assert stage["clocks"]["dpll_mpu_m2_ck"] == freq * 1000
        assert stage["clocks"]["mpuss-clkctrl:0000:0"] == freq * 1000
        assert (1050 <= stage["ina1"][0] <= 1150 if freq == 350000 else 1150 <= stage["ina1"][0] <= 1250)
    assert stages["final"]["governor"] == "performance"
    assert abs(stages["final"]["ina1"][0] - stages["before"]["ina1"][0]) <= 16
    return stages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    review = json.loads((ROOT / "development/perrier-ramenv/cpu-dvfs-low-trial/reviewed-image.json").read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram115"
    if not args.execute:
        print("Audited ram115 low-voltage transition is ready.")
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-dvfs-low-trial")
    directory.mkdir(mode=0o700)
    (directory / "command.sh").write_text(REMOTE)
    result = None
    report: dict = {"passed": False, "boot_id": state["boot_id"],
                    "started": started.isoformat()}
    try:
        result = ram.remote(REMOTE, timeout=90)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("CPU_DVFS_LOW_TRIAL_PASS\n"):
            raise RuntimeError("CPU DVFS test command failed")
        stages = parse(result.stdout)
        report.update(passed=True, stages=stages,
                      low_voltage_drop_mv=stages["before"]["ina1"][0] - stages["low_idle"]["ina1"][0])
    except BaseException as exc:
        report["error"] = repr(exc)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        report["returncode"] = result.returncode if result is not None else None
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        request_recovery()
    print(json.dumps({"run": str(directory), "passed": report["passed"],
                      "error": report.get("error"),
                      "low_voltage_drop_mv": report.get("low_voltage_drop_mv")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
