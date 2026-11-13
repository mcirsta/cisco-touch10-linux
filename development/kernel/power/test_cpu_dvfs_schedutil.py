#!/usr/bin/env python3
"""Historical sequential-read ram114 test, superseded by paired sampling."""
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
test "$(cat /run/touch10-ram)" = perrier-interactive-ram114
test "$(uname -r)" = 6.18.48-perrier-ram114
test "$(cat /sys/devices/system/cpu/online)" = 0-1
policy=/sys/devices/system/cpu/cpufreq/policy0
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/scaling_cur_freq")" = 700000
reg=''
for p in /sys/class/regulator/regulator*; do
    test -r "$p/name" || continue
    test "$(cat "$p/name")" = perrier-vdd-mpu || continue
    test -z "$reg"; reg=$p
done
test -n "$reg"
test "$(cat "$reg/microvolts")" = 1215400
test "$(cat /sys/block/mmcblk0/ro)" = 1
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
    for chip in /sys/class/hwmon/hwmon*; do
        test -r "$chip/name" || continue
        test "$(cat "$chip/name")" = ina3221 || continue
        case "$(readlink -f "$chip/device")" in *3-0041)
            echo "INA1 $(cat "$chip/in1_input") $(cat "$chip/curr1_input")"
            ;;
        esac
    done
    echo "GUARD $(cat /run/guard.json)"
    echo "END $1"
}
sample before
echo schedutil > "$policy/scaling_governor"
sleep 60
sample idle
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 20
sample two_core_load
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
sleep 10
sample idle_after_load
echo performance > "$policy/scaling_governor"
sleep 2
sample restored
if dmesg | grep -q 'VC bypass failed'; then exit 5; fi
echo CPU_DVFS_SCHEDUTIL_PASS
'''


def request_recovery() -> None:
    current = json.loads(ram.CURRENT.read_text())
    if current["status"] not in ("interactive", "recovering") or current["profile"] != "cpu-dvfs-trial":
        raise RuntimeError("No active ram114 runner")
    target = Path(current["directory"]) / "recover-request.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"mode": "cpu_dvfs_schedutil_complete"}) + "\n")
    os.replace(temp, target)


def parse(stdout: str) -> dict:
    stages: dict[str, dict] = {}
    active = None
    for line in stdout.splitlines():
        words = line.split()
        if words[:1] == ["BEGIN"]:
            active = words[1]
            stages[active] = {}
        elif words[:1] == ["END"]:
            assert active == words[1]
            active = None
        elif active and words[:1] in (["FREQ"], ["REGULATOR"], ["THERMAL"]):
            stages[active][words[0].lower()] = int(words[1])
        elif active and words[:1] == ["INA1"]:
            stages[active]["ina1"] = [int(words[1]), int(words[2])]
        elif active and words[:1] in (["GOVERNOR"], ["CPUS"]):
            stages[active][words[0].lower()] = words[1]
        elif active and words[:1] == ["GUARD"]:
            stages[active]["guard"] = json.loads(line.removeprefix("GUARD "))
    assert list(stages) == ["before", "idle", "two_core_load", "idle_after_load", "restored"]
    expected = [(700000, 1215400, "performance"),
                (350000, 1202740, "schedutil"),
                (700000, 1215400, "schedutil"),
                (350000, 1202740, "schedutil"),
                (700000, 1215400, "performance")]
    for stage, (freq, uv, governor) in zip(stages.values(), expected):
        assert stage["cpus"] == "0-1" and stage["governor"] == governor
        assert stage["freq"] == freq and stage["regulator"] == uv
        assert stage["thermal"] < 80000 and 1150 <= stage["ina1"][0] <= 1250
        assert stage["guard"]["state"] == "feeding" and stage["guard"]["nowayout"]
    assert active is None
    assert abs(stages["restored"]["ina1"][0] - stages["before"]["ina1"][0]) <= 16
    return stages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    review = json.loads((ROOT / "development/perrier-ramenv/cpu-dvfs-trial/reviewed-image.json").read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram114"
    first = json.loads((ROOT / "development/runs/20261113T161454Z-cpu-dvfs-trial/result.json").read_text())
    assert first["passed"]
    if not args.execute:
        print("Superseded by measure_cpu_dvfs_schedutil.py: sequential sysfs reads race with transitions.")
        return
    raise SystemExit("Use measure_cpu_dvfs_schedutil.py --execute for live sampling")
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-dvfs-schedutil")
    directory.mkdir(mode=0o700)
    (directory / "command.sh").write_text(REMOTE)
    result = None
    report: dict = {"passed": False, "boot_id": state["boot_id"], "started": started.isoformat()}
    try:
        result = ram.remote(REMOTE, timeout=150)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("CPU_DVFS_SCHEDUTIL_PASS\n"):
            raise RuntimeError("schedutil command failed")
        report.update(passed=True, stages=parse(result.stdout))
    except BaseException as exc:
        report["error"] = repr(exc)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        report["returncode"] = result.returncode if result is not None else None
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        request_recovery()
    print(json.dumps({"run": str(directory), "passed": report["passed"],
                      "error": report.get("error")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
