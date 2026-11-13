#!/usr/bin/env python3
"""Compare monitored rail power at ram116's fixed 350 and 700 MHz OPPs."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

REMOTE = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram116
test "$(uname -r)" = 6.18.48-perrier-ram116
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
a=''; b=''
for p in /sys/bus/i2c/devices/3-0040/hwmon/hwmon*; do
    test "$(cat "$p/name")" = ina3221; a=$p
done
for p in /sys/bus/i2c/devices/3-0041/hwmon/hwmon*; do
    test "$(cat "$p/name")" = ina3221; b=$p
done
test -n "$a" && test -n "$b"
workers=''
restore() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
echo userspace > "$policy/scaling_governor"
phase() {
    label=$1; target=$2; expected=$3
    echo "$target" > "$policy/scaling_setspeed"
    sleep 3
    i=0
    while test "$i" -lt 12; do
        hz=$(cat "$policy/cpuinfo_cur_freq")
        uv=$(cat "$reg/microvolts")
        temp=$(cat /sys/class/thermal/thermal_zone0/temp)
        test "$hz" = "$target"
        test "$uv" = "$expected"
        test "$temp" -lt 75000
        line="SAMPLE $label $(cut -d' ' -f1 /proc/uptime) $hz $uv $temp"
        for chip in "$a" "$b"; do
            for channel in 1 2 3; do
                mv=$(cat "$chip/in${channel}_input")
                ma=$(cat "$chip/curr${channel}_input")
                line="$line $mv $ma"
            done
        done
        echo "$line"
        i=$((i + 1))
        if test "$i" -lt 12; then sleep 1; fi
    done
}
phase idle700a 700000 1215400
phase idle350a 350000 1152100
phase idle350b 350000 1152100
phase idle700b 700000 1215400
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 2
phase load700a 700000 1215400
phase load350a 350000 1152100
phase load350b 350000 1152100
phase load700b 700000 1215400
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
test "$(cat "$reg/microvolts")" = 1215400
echo performance > "$policy/scaling_governor"
if dmesg | grep -q 'VC bypass failed'; then exit 5; fi
echo "GUARD $(cat /run/guard.json)"
echo CPU_DVFS_MID_POWER_PASS
'''


def request_recovery() -> None:
    current = json.loads(ram.CURRENT.read_text())
    if current["status"] not in ("interactive", "recovering") or current["profile"] != "cpu-dvfs-mid-trial":
        raise RuntimeError("No active ram116 runner")
    target = Path(current["directory"]) / "recover-request.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"mode": "cpu_dvfs_power_complete"}) + "\n")
    os.replace(temporary, target)


def parse(stdout: str) -> dict:
    samples: dict[str, list[dict]] = defaultdict(list)
    guard = None
    for line in stdout.splitlines():
        if line.startswith("SAMPLE "):
            fields = line.split()
            assert len(fields) == 18
            label = fields[1]
            values = [int(x) for x in fields[3:]]
            hz, uv, temp = values[:3]
            rails = []
            for i in range(3, len(values), 2):
                mv, ma = values[i:i + 2]
                rails.append({"mv": mv, "ma": ma, "mw": mv * ma / 1000})
            assert len(rails) == 6
            samples[label].append({"uptime_s": float(fields[2]),
                                   "hardware_khz": hz, "regulator_uv": uv,
                                   "cpu_millicelsius": temp, "rails": rails})
        elif line.startswith("GUARD "):
            guard = json.loads(line.removeprefix("GUARD "))
    expected = ["idle700a", "idle350a", "idle350b", "idle700b",
                "load700a", "load350a", "load350b", "load700b"]
    assert list(samples) == expected
    for label, data in samples.items():
        assert len(data) == 12
        hz = 350000 if "350" in label else 700000
        uv = 1152100 if hz == 350000 else 1215400
        assert all(s["hardware_khz"] == hz and s["regulator_uv"] == uv and
                   s["cpu_millicelsius"] < 75000 for s in data)
    assert guard and guard["state"] == "feeding" and guard["nowayout"]
    summary = {"sample_count": sum(map(len, samples.values())),
               "peak_cpu_millicelsius": max(s["cpu_millicelsius"]
                                             for data in samples.values() for s in data),
               "watchdog_pings": guard["pings"], "rail_power_mw": {}}
    for mode in ("idle", "load"):
        summary["rail_power_mw"][mode] = {}
        for rail in range(6):
            values = {}
            for hz in (350, 700):
                readings = [s["rails"][rail]["mw"] for label, data in samples.items()
                            if label.startswith(mode) and str(hz) in label for s in data]
                assert len(readings) == 24
                values[str(hz)] = {"mean": round(statistics.mean(readings), 2),
                                   "median": round(statistics.median(readings), 2),
                                   "min": round(min(readings), 2),
                                   "max": round(max(readings), 2)}
            delta = values["700"]["mean"] - values["350"]["mean"]
            values["700_minus_350_mw"] = round(delta, 2)
            values["reduction_percent_of_700"] = round(100 * delta / values["700"]["mean"], 2) if values["700"]["mean"] > 0 else None
            summary["rail_power_mw"][mode][f"3-004{0 if rail < 3 else 1}:channel{rail % 3 + 1}"] = values
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--keep-ram", action="store_true",
                        help="on success, keep the leased RAM session for the low-selector probe")
    args = parser.parse_args()
    review = json.loads((ROOT / "development/perrier-ramenv/cpu-dvfs-mid-trial/reviewed-image.json").read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram116"
    if not args.execute:
        print("96 guarded INA samples across idle/load 350/700 MHz are ready.")
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-dvfs-mid-power")
    directory.mkdir(mode=0o700)
    (directory / "command.sh").write_text(REMOTE)
    result = None
    report: dict = {"passed": False, "boot_id": state["boot_id"], "started": started.isoformat()}
    try:
        result = ram.remote(REMOTE, timeout=350)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("CPU_DVFS_MID_POWER_PASS\n"):
            raise RuntimeError("power measurement command failed")
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
