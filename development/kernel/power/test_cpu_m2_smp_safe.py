#!/usr/bin/env python3
"""Bounded two-core 350 MHz and schedutil trial; never hotplug a CPU.

Run only inside the separately audited ram113 U-Boot session. The remote
shell returns to the 700 MHz performance governor on every normal exit.
The host session maintains the nowayout watchdog and restores stock boot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
IMAGE = ROOT / "development/perrier-ramenv/cpu-m2-smp-safe"
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

REMOTE = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram113
test "$(uname -r)" = 6.18.48-perrier-ram113
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test ! -e /sys/devices/system/cpu/cpu1/online
policy=/sys/devices/system/cpu/cpufreq/policy0
test "$(cat "$policy/scaling_driver")" = cpufreq-dt
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/scaling_cur_freq")" = 700000
set -- $(cat "$policy/scaling_available_frequencies")
test "$#" -eq 2
case "$1:$2" in 350000:700000|700000:350000) ;; *) exit 3;; esac
grep -qw schedutil "$policy/scaling_available_governors"
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 75000
workers=''
restore() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
sample() {
    echo "SAMPLE $1"
    echo "CPUS $(cat /sys/devices/system/cpu/online)"
    echo "GOVERNOR $(cat "$policy/scaling_governor")"
    echo "FREQ $(cat "$policy/scaling_cur_freq")"
    echo "THERMAL $(cat /sys/class/thermal/thermal_zone0/temp)"
    awk '$1 == "dpll_mpu_ck" || $1 == "dpll_mpu_m2_ck" || $1 == "mpuss-clkctrl:0000:0" { print "CLOCK " $1 " " $5 }' /sys/kernel/debug/clk/clk_summary
    for chip in /sys/class/hwmon/hwmon*; do
        test -r "$chip/name" || continue
        test "$(cat "$chip/name")" = ina3221 || continue
        device=$(readlink -f "$chip/device")
        case "$device" in *3-0041)
            for channel in 1 2 3; do
                echo "RAIL $channel $(cat "$chip/in${channel}_input") $(cat "$chip/curr${channel}_input")"
            done
            ;;
        esac
    done
    echo "GUARD $(cat /run/guard.json)"
}
sample before
echo userspace > "$policy/scaling_governor"
echo 350000 > "$policy/scaling_setspeed"
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 20
test "$(cat "$policy/scaling_cur_freq")" = 350000
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
sample fixed_350_load
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
echo 700000 > "$policy/scaling_setspeed"
sleep 2
sample fixed_restored
echo schedutil > "$policy/scaling_governor"
sleep 5
sample dynamic_idle
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 10
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
sample dynamic_load
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
sleep 5
sample dynamic_restored
echo performance > "$policy/scaling_governor"
sleep 1
sample final
echo CPU_M2_SMP_SAFE_PASS
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(stdout: str) -> dict:
    samples: dict[str, dict] = {}
    current = None
    for line in stdout.splitlines():
        fields = line.split()
        if fields[:1] == ["SAMPLE"] and len(fields) == 2:
            current = fields[1]
            samples[current] = {"clocks": {}, "rails": {}}
        elif current and fields[:1] == ["CPUS"] and len(fields) == 2:
            samples[current]["cpus"] = fields[1]
        elif current and fields[:1] == ["GOVERNOR"] and len(fields) == 2:
            samples[current]["governor"] = fields[1]
        elif current and fields[:1] == ["FREQ"] and len(fields) == 2:
            samples[current]["frequency_khz"] = int(fields[1])
        elif current and fields[:1] == ["THERMAL"] and len(fields) == 2:
            samples[current]["thermal_millicelsius"] = int(fields[1])
        elif current and fields[:1] == ["CLOCK"] and len(fields) == 3:
            samples[current]["clocks"][fields[1]] = int(fields[2])
        elif current and fields[:1] == ["RAIL"] and len(fields) == 4:
            samples[current]["rails"][fields[1]] = {"millivolt": int(fields[2]),
                                                      "milliamp": int(fields[3])}
    assert list(samples) == ["before", "fixed_350_load", "fixed_restored",
                             "dynamic_idle", "dynamic_load", "dynamic_restored", "final"]
    assert all(sample["cpus"] == "0-1" for sample in samples.values())
    assert all(sample["thermal_millicelsius"] < 80000 for sample in samples.values())
    assert [samples[name]["frequency_khz"] for name in
            ("before", "fixed_350_load", "fixed_restored", "final")] == \
           [700000, 350000, 700000, 700000]
    assert [samples[name]["governor"] for name in
            ("before", "fixed_350_load", "dynamic_load", "final")] == \
           ["performance", "userspace", "schedutil", "performance"]
    for name, rate in (("before", 700000000), ("fixed_350_load", 350000000),
                       ("fixed_restored", 700000000), ("final", 700000000)):
        clocks = samples[name]["clocks"]
        assert clocks["dpll_mpu_ck"] == 700000000
        assert clocks["dpll_mpu_m2_ck"] == clocks["mpuss-clkctrl:0000:0"] == rate
    for sample in samples.values():
        assert 350000 <= sample["frequency_khz"] <= 700000
        assert sample["clocks"]["dpll_mpu_ck"] == 700000000
        assert len(sample["rails"]) == 3
        assert 1100 <= sample["rails"]["1"]["millivolt"] <= 1300
    return {"samples": samples,
            "dynamic_frequency_observed_khz": [samples[name]["frequency_khz"] for name in
                                               ("dynamic_idle", "dynamic_load", "dynamic_restored")]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    review = json.loads((IMAGE / "reviewed-image.json").read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram113"
    assert review["runtime_cpu_hotplug_disabled"] and not review["voltage_control_enabled"]
    for item in review["artifacts"].values():
        assert sha(Path(item["path"])) == item["sha256"]
    if not args.execute:
        print("Audited ram113 two-core test is ready; --execute requires its RAM session.")
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    assert state["guard"]["timeout_seconds"] == 120
    started = datetime.now(timezone.utc)
    result = ram.remote(REMOTE, timeout=90)
    finished = datetime.now(timezone.utc)
    run = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-m2-smp-safe")
    run.mkdir(mode=0o700)
    (run / "stdout.log").write_text(result.stdout)
    (run / "stderr.log").write_text(result.stderr)
    passed = result.returncode == 0 and "CPU_M2_SMP_SAFE_PASS" in result.stdout
    interpretation = None
    if passed:
        try:
            interpretation = inspect(result.stdout)
        except (AssertionError, KeyError, ValueError) as exc:
            passed, interpretation = False, {"failed_check": repr(exc)}
    report = {"passed": passed, "kernel": review["kernel"],
              "review_sha256": sha(IMAGE / "reviewed-image.json"),
              "boot_id": state["boot_id"], "started": started.isoformat(),
              "finished": finished.isoformat(), "returncode": result.returncode,
              "stdout_sha256": sha(run / "stdout.log"),
              "stderr_sha256": sha(run / "stderr.log"),
              "interpretation": interpretation}
    (run / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"run": str(run), "passed": passed,
                      "dynamic_frequency_observed_khz":
                      interpretation.get("dynamic_frequency_observed_khz") if passed else None}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
