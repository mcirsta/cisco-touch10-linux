#!/usr/bin/env python3
"""Probe two lower MPU selectors at fixed 350 MHz in the leased RAM kernel."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = HERE / "omap4_mpu_low_step.c"
REVIEW = HERE / "omap4-mpu-low-step-review.json"
TEMP = "/tmp/perrier-mpu-low-step"
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(script: str, timeout: int = 20) -> str:
    result = ram.remote(script, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"RAM SSH failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def request_recovery() -> None:
    current = json.loads(ram.CURRENT.read_text())
    if current["status"] not in ("interactive", "recovering") or current["profile"] != "cpu-dvfs-trial":
        raise RuntimeError("No active ram114 runner for stock recovery")
    target = Path(current["directory"]) / "recover-request.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"mode": "mpu_low_selectors_complete"}) + "\n")
    os.replace(temporary, target)


def parse(stdout: str, selector: int) -> dict:
    stages = {}
    for label, mv, temp, khz in re.findall(
        r"^SAMPLE (\w+) mV=(\d+) temp_mC=(\d+) kHz=(\d+)$",
        stdout, flags=re.M,
    ):
        stages[label] = {"millivolts": int(mv), "cpu_millicelsius": int(temp),
                         "hardware_khz": int(khz)}
    assert list(stages) == ["before", "low", "restored"]
    assert all(s["hardware_khz"] == 350000 and s["cpu_millicelsius"] < 75000
               for s in stages.values())
    observed = [int(s, 16) for s in re.findall(r"^VC selector=([0-9a-f]{2}) ",
                                                  stdout, flags=re.M)]
    assert observed == [selector, 0x28]
    assert abs(stages["restored"]["millivolts"] - stages["before"]["millivolts"]) <= 16
    drop = stages["before"]["millivolts"] - stages["low"]["millivolts"]
    assert drop >= (20 if selector == 0x24 else 60)
    return {"selector": f"0x{selector:02x}", "stages": stages,
            "measured_drop_millivolts": drop}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    review = json.loads(REVIEW.read_text())
    assert review["passed"] and review["source_sha256"] == sha(SOURCE)
    assert review["kernel"] == "6.18.48-perrier-ram114"
    for selector in (0x24, 0x20):
        path = HERE / f"omap4_mpu_low_step_{selector:02x}.arm"
        assert review["binaries"][f"0x{selector:02x}"]["sha256"] == sha(path)
    if not args.execute:
        print(json.dumps({"ready": True, "review": str(REVIEW)}, indent=2))
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-mpu-low-selectors")
    directory.mkdir(mode=0o700)
    report: dict = {"passed": False, "boot_id": state["boot_id"],
                    "started": started.isoformat(), "source_sha256": sha(SOURCE),
                    "stages": []}
    uploaded = False
    try:
        remote('''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram114
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test "$(cat /sys/block/mmcblk0/ro)" = 1
test "$(awk '$2 == "/tmp" {print $3}' /proc/mounts)" = tmpfs
test ! -e /tmp/perrier-mpu-low-step
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor)" = performance
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq)" = 700000
''')
        remote('''set -eu
policy=/sys/devices/system/cpu/cpufreq/policy0
echo userspace > "$policy/scaling_governor"
echo 350000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/cpuinfo_cur_freq")" = 350000
reg=''
for p in /sys/class/regulator/regulator*; do
    test -r "$p/name" || continue
    test "$(cat "$p/name")" = perrier-vdd-mpu || continue
    test -z "$reg"; reg=$p
done
test -n "$reg"
test "$(cat "$reg/microvolts")" = 1202740
''')
        for selector in (0x24, 0x20):
            path = HERE / f"omap4_mpu_low_step_{selector:02x}.arm"
            binary = path.read_bytes()
            upload = subprocess.run(ram.SSH + ["umask 077; cat > " + TEMP],
                                    input=binary, capture_output=True, timeout=20)
            if upload.returncode:
                raise RuntimeError(f"selector {selector:02x} upload failed")
            uploaded = True
            readback = subprocess.run(ram.SSH + ["cat " + TEMP],
                                      capture_output=True, timeout=20)
            if readback.returncode or readback.stdout != binary:
                raise RuntimeError(f"selector {selector:02x} RAM readback differs")
            remote("chmod 700 " + TEMP + "\n")
            for loaded in (False, True):
                command = TEMP + "\n"
                if loaded:
                    command = '''set -eu
workers=''
cleanup() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
}
trap cleanup EXIT HUP INT TERM
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 2
/tmp/perrier-mpu-low-step
'''
                result = ram.remote(command, timeout=35)
                stem = f"{selector:02x}-{'loaded' if loaded else 'idle'}"
                (directory / f"{stem}.stdout.log").write_text(result.stdout)
                (directory / f"{stem}.stderr.log").write_text(result.stderr)
                if result.returncode or not result.stdout.endswith(
                    f"VC_LOW_STEP_PASS target={selector:02x}\n"
                ):
                    raise RuntimeError(f"selector {stem} did not complete its restore path")
                stage = parse(result.stdout, selector)
                stage["two_core_load"] = loaded
                stage["binary_sha256"] = sha(path)
                report["stages"].append(stage)
                remote('''set -eu
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq)" = 350000
for p in /sys/class/regulator/regulator*; do
    test -r "$p/name" || continue
    test "$(cat "$p/name")" = perrier-vdd-mpu || continue
    test "$(cat "$p/microvolts")" = 1202740
done
''')
            remote("rm -f " + TEMP + "\ntest ! -e " + TEMP + "\n")
            uploaded = False
        remote('''set -eu
policy=/sys/devices/system/cpu/cpufreq/policy0
echo 700000 > "$policy/scaling_setspeed"
sleep 2
test "$(cat "$policy/cpuinfo_cur_freq")" = 700000
echo performance > "$policy/scaling_governor"
if dmesg | grep -q 'VC bypass failed'; then exit 5; fi
''')
        report["passed"] = True
    except BaseException as exc:
        report["error"] = repr(exc)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        if uploaded:
            try:
                remote("rm -f " + TEMP + "\ntest ! -e " + TEMP + "\n")
            except Exception:
                pass
        try:
            request_recovery()
        except Exception as exc:
            report["recovery_request_error"] = repr(exc)
            (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"run": str(directory), "passed": report["passed"],
                      "stages": report["stages"], "error": report.get("error")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
