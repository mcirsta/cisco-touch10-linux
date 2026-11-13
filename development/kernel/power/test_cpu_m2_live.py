#!/usr/bin/env python3
"""One bounded 700 -> 350 -> 700 MHz RAM-kernel clock-only test.

Run only while the audited cpu-m2-trial U-Boot session is interactive. The
remote shell restores the 700 MHz performance policy on every normal exit.
The host must still keep the nowayout watchdog lease and stock recovery.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
IMAGE = ROOT / "development/perrier-ramenv/cpu-m2-trial"
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

REMOTE = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram112
test "$(uname -r)" = 6.18.48-perrier-ram112
test "$(cat /sys/devices/system/cpu/cpu1/online)" = 0
policy=/sys/devices/system/cpu/cpufreq/policy0
test -d "$policy"
test "$(cat "$policy/scaling_driver")" = cpufreq-dt
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/scaling_cur_freq")" = 700000
set -- $(cat "$policy/scaling_available_frequencies")
test "$#" -eq 2
case "$1:$2" in 350000:700000|700000:350000) ;; *) echo BAD_OPPS "$1:$2"; exit 3;; esac
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
clock_state() {
    awk '$1 == "dpll_mpu_ck" || $1 == "dpll_mpu_m2_ck" || $1 == "mpuss-clkctrl:0000:0" { print "CLOCK " $1 " " $5 }' /sys/kernel/debug/clk/clk_summary
}
rails() {
    for chip in /sys/class/hwmon/hwmon*; do
        test -r "$chip/name" || continue
        name=$(cat "$chip/name")
        test "$name" = ina3221 || continue
        device=$(readlink -f "$chip/device")
        for channel in 1 2 3; do
            value=$(cat "$chip/in${channel}_input")
            echo "RAIL $device channel=$channel millivolt=$value"
        done
    done
}
sample() {
    echo "SAMPLE $1"
    echo "FREQ $(cat "$policy/scaling_cur_freq")"
    echo "THERMAL $(cat /sys/class/thermal/thermal_zone0/temp)"
    clock_state
    rails
    echo "UPTIME $(cat /proc/uptime)"
    echo "GUARD $(cat /run/guard.json)"
}
restore() {
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
sample before
echo userspace > "$policy/scaling_governor"
echo 350000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 350000
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
sample low
sleep 5
test "$(cat "$policy/scaling_cur_freq")" = 350000
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 700000
sample restored
echo performance > "$policy/scaling_governor"
echo CPU_M2_TRIAL_PASS
'''


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interpret(output: str, elapsed: float) -> dict:
    samples: dict[str, dict] = {}
    current = None
    for line in output.splitlines():
        fields = line.split()
        if fields[:1] == ["SAMPLE"] and len(fields) == 2:
            current = fields[1]
            assert current not in samples
            samples[current] = {"clocks": {}, "rails": {}}
        elif current and fields[:1] == ["FREQ"] and len(fields) == 2:
            samples[current]["frequency_khz"] = int(fields[1])
        elif current and fields[:1] == ["CLOCK"] and len(fields) == 3:
            samples[current]["clocks"][fields[1]] = int(fields[2])
        elif current and fields[:1] == ["RAIL"] and len(fields) == 4:
            assert fields[2].startswith("channel=") and fields[3].startswith("millivolt=")
            key = fields[1] + ":" + fields[2].split("=", 1)[1]
            samples[current]["rails"][key] = int(fields[3].split("=", 1)[1])
        elif current and fields[:1] == ["UPTIME"] and len(fields) == 3:
            samples[current]["uptime_seconds"] = float(fields[1])
        elif current and fields[:1] == ["THERMAL"] and len(fields) == 2:
            samples[current]["thermal_millicelsius"] = int(fields[1])
    assert list(samples) == ["before", "low", "restored"], list(samples)
    assert [samples[s]["frequency_khz"] for s in samples] == [700000, 350000, 700000]
    for s, expected in (("before", 700000000), ("low", 350000000),
                        ("restored", 700000000)):
        clocks = samples[s]["clocks"]
        assert clocks["dpll_mpu_m2_ck"] == expected, (s, clocks)
        assert clocks["mpuss-clkctrl:0000:0"] == expected, (s, clocks)
        assert clocks["dpll_mpu_ck"] == 700000000, (s, clocks)
        assert samples[s]["thermal_millicelsius"] < 80000
    rails = samples["before"]["rails"]
    assert len(rails) >= 6
    assert rails.keys() == samples["low"]["rails"].keys() == samples["restored"]["rails"].keys()
    monitored = [key for key, value in rails.items() if 800 <= value <= 1400]
    assert len(monitored) >= 2
    for s in ("low", "restored"):
        assert all(abs(samples[s]["rails"][key] - rails[key]) <= 75 for key in monitored)
    ram_elapsed = samples["restored"]["uptime_seconds"] - samples["before"]["uptime_seconds"]
    assert 8 <= ram_elapsed <= 20, ram_elapsed
    assert abs(ram_elapsed - elapsed) <= 3, (ram_elapsed, elapsed)
    return {"samples": samples, "monitored_rails": monitored,
            "ram_elapsed_seconds": round(ram_elapsed, 2),
            "host_elapsed_seconds": round(elapsed, 2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="make the one temporary CPU clock transition")
    args = parser.parse_args()
    review = json.loads((IMAGE / "reviewed-image.json").read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram112"
    assert review["voltage_control_enabled"] is False
    for item in review["artifacts"].values():
        assert digest(Path(item["path"])) == item["sha256"]
    if not args.execute:
        print("Reviewed clock-only trial is ready; pass --execute during its RAM session.")
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog"
    assert state["guard"]["nowayout"] is True
    assert state["guard"]["timeout_seconds"] == 120
    started = datetime.now(timezone.utc)
    result = ram.remote(REMOTE, timeout=45)
    finished = datetime.now(timezone.utc)
    run = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-m2-clock-only")
    run.mkdir(mode=0o700)
    (run / "stdout.log").write_text(result.stdout)
    (run / "stderr.log").write_text(result.stderr)
    passed = result.returncode == 0 and "CPU_M2_TRIAL_PASS" in result.stdout
    interpretation = None
    if passed:
        try:
            interpretation = interpret(result.stdout, (finished - started).total_seconds())
        except (AssertionError, KeyError, ValueError) as exc:
            interpretation = {"failed_check": repr(exc)}
            passed = False
    report = {"passed": passed, "kernel": review["kernel"],
              "review_sha256": digest(IMAGE / "reviewed-image.json"),
              "boot_id": state["boot_id"], "started": started.isoformat(),
              "finished": finished.isoformat(), "returncode": result.returncode,
              "stdout_sha256": digest(run / "stdout.log"),
              "stderr_sha256": digest(run / "stderr.log"),
              "voltage_control_enabled": False,
              "interpretation": interpretation}
    (run / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"run": str(run), **report}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
