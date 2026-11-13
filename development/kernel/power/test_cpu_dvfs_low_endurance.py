#!/usr/bin/env python3
"""Guarded five-minute two-core load at ram115's qualified 350 MHz OPP."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
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
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
reg=''
for p in /sys/class/regulator/regulator*; do
    test -r "$p/name" || continue
    test "$(cat "$p/name")" = perrier-vdd-mpu || continue
    test -z "$reg"; reg=$p
done
test -n "$reg"
test "$(cat "$reg/microvolts")" = 1215400
ina=''
for chip in /sys/class/hwmon/hwmon*; do
    test -r "$chip/name" || continue
    test "$(cat "$chip/name")" = ina3221 || continue
    case "$(readlink -f "$chip/device")" in *3-0041) ina=$chip;; esac
done
test -n "$ina"
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 70000
workers=''
restore() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
echo userspace > "$policy/scaling_governor"
echo 350000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/cpuinfo_cur_freq")" = 350000
test "$(cat "$reg/microvolts")" = 1101460
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
i=0
while test "$i" -le 30; do
    hw=$(cat "$policy/cpuinfo_cur_freq")
    uv=$(cat "$reg/microvolts")
    temp=$(cat /sys/class/thermal/thermal_zone0/temp)
    mv=$(cat "$ina/in1_input")
    ma=$(cat "$ina/curr1_input")
    echo "SAMPLE $i $hw $uv $temp $mv $ma"
    test "$hw" = 350000
    test "$uv" = 1101460
    test "$temp" -lt 75000
    test "$mv" -ge 1060
    test "$mv" -le 1140
    i=$((i + 1))
    if test "$i" -le 30; then sleep 10; fi
done
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
test "$(cat "$reg/microvolts")" = 1215400
echo performance > "$policy/scaling_governor"
if dmesg | grep -q 'VC bypass failed'; then exit 5; fi
echo "GUARD $(cat /run/guard.json)"
echo CPU_DVFS_LOW_ENDURANCE_PASS
'''


def request_recovery() -> None:
    current = json.loads(ram.CURRENT.read_text())
    if current["status"] not in ("interactive", "recovering") or current["profile"] != "cpu-dvfs-low-trial":
        raise RuntimeError("No active ram115 runner")
    target = Path(current["directory"]) / "recover-request.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"mode": "cpu_dvfs_endurance_complete"}) + "\n")
    os.replace(temporary, target)


def parse(stdout: str) -> dict:
    samples = []
    guard = None
    for line in stdout.splitlines():
        if line.startswith("SAMPLE "):
            number, hw, uv, temp, mv, ma = map(int, line.split()[1:])
            samples.append({"number": number, "hardware_khz": hw,
                            "regulator_uv": uv, "cpu_millicelsius": temp,
                            "likely_mpu_millivolts": mv,
                            "likely_mpu_milliamps": ma})
        elif line.startswith("GUARD "):
            guard = json.loads(line.removeprefix("GUARD "))
    assert [s["number"] for s in samples] == list(range(31))
    assert guard and guard["state"] == "feeding" and guard["nowayout"]
    return {"seconds": 300, "sample_count": len(samples),
            "peak_cpu_millicelsius": max(s["cpu_millicelsius"] for s in samples),
            "likely_mpu_voltage_millivolts": [min(s["likely_mpu_millivolts"] for s in samples),
                                               max(s["likely_mpu_millivolts"] for s in samples)],
            "likely_mpu_current_milliamps": [min(s["likely_mpu_milliamps"] for s in samples),
                                              max(s["likely_mpu_milliamps"] for s in samples)],
            "watchdog_pings": guard["pings"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--keep-ram", action="store_true")
    args = parser.parse_args()
    review = json.loads((ROOT / "development/perrier-ramenv/cpu-dvfs-low-trial/reviewed-image.json").read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram115"
    first = json.loads((ROOT / "development/runs/20261113T171335Z-cpu-dvfs-low-trial/result.json").read_text())
    assert first["passed"]
    if not args.execute:
        print("Guarded five-minute ram115 two-core load test is ready.")
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-dvfs-low-endurance")
    directory.mkdir(mode=0o700)
    (directory / "command.sh").write_text(REMOTE)
    result = None
    report: dict = {"passed": False, "boot_id": state["boot_id"], "started": started.isoformat()}
    try:
        result = ram.remote(REMOTE, timeout=390)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("CPU_DVFS_LOW_ENDURANCE_PASS\n"):
            raise RuntimeError("guarded endurance command failed")
        report.update(passed=True, summary=parse(result.stdout))
    except BaseException as exc:
        report["error"] = repr(exc)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        report["returncode"] = result.returncode if result is not None else None
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        if not (report["passed"] and args.keep_ram):
            request_recovery()
    print(json.dumps({"run": str(directory), "passed": report["passed"],
                      "summary": report.get("summary"), "error": report.get("error")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
