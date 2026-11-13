#!/usr/bin/env python3
"""Run one hash-pinned, one-selector-step MPU VC test in audited RAM Linux."""
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
BINARY = HERE / "omap4_mpu_bypass_step.arm"
SOURCE = HERE / "omap4_mpu_bypass_step.c"
REVIEW = HERE / "omap4-mpu-bypass-step-review.json"
TEMP = "/tmp/perrier-mpu-bypass-step"
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(script: str, timeout: int = 15) -> str:
    result = ram.remote(script, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"RAM SSH failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def request_recovery() -> None:
    current = json.loads(ram.CURRENT.read_text())
    if current["status"] not in ("interactive", "recovering") or current["profile"] != "cpu-m2-smp-safe":
        raise RuntimeError("Cannot locate the exact ram113 runner for recovery")
    target = Path(current["directory"]) / "recover-request.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"mode": "mpu_vc_step_complete"}) + "\n")
    os.replace(temp, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--load", action="store_true",
                        help="hold both CPUs busy during the same bounded step")
    args = parser.parse_args()
    review = json.loads(REVIEW.read_text())
    assert review["passed"] and review["kernel"] == "6.18.48-perrier-ram113"
    assert review["source_sha256"] == sha(SOURCE)
    assert review["binary_sha256"] == sha(BINARY)
    if not args.execute:
        print(json.dumps({"ready": True, "binary_sha256": sha(BINARY),
                          "test": review["scope"]}, indent=2))
        return
    state = ram.ram_state(review["kernel"])
    assert state["guard"]["backend"] == "linux-watchdog"
    assert state["guard"]["nowayout"] and state["guard"]["timeout_seconds"] == 120
    remote('''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram113
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor)" = performance
test "$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq)" = 700000
test "$(cat /sys/block/mmcblk0/ro)" = 1
test "$(awk '$2 == "/tmp" {print $3}' /proc/mounts)" = tmpfs
test ! -e /tmp/perrier-mpu-bypass-step
''')
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-ram113-mpu-vc-step")
    directory.mkdir(mode=0o700)
    uploaded = False
    result = None
    failure = None
    try:
        transfer = subprocess.run(ram.SSH + ["umask 077; cat > " + TEMP],
                                  input=BINARY.read_bytes(), capture_output=True, timeout=20)
        if transfer.returncode:
            raise RuntimeError("RAM helper transfer failed: " + transfer.stderr.decode(errors="replace"))
        uploaded = True
        readback = subprocess.run(ram.SSH + ["cat " + TEMP], capture_output=True, timeout=20)
        if readback.returncode or readback.stdout != BINARY.read_bytes():
            raise RuntimeError("RAM helper readback differs from the audited binary")
        remote("chmod 700 " + TEMP + "\n")
        command = TEMP + "\n"
        if args.load:
            command = '''set -eu
workers=''
cleanup() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
}
trap cleanup EXIT HUP INT TERM
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 2
/tmp/perrier-mpu-bypass-step
'''
        result = ram.remote(command, timeout=25)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("VC_BYPASS_STEP_PASS\n"):
            raise RuntimeError("VC helper did not finish its restore path")
        stages: dict[str, dict[str, int]] = {}
        for label, volts, temp, clock in re.findall(
            r"^SAMPLE (\w+) mV=(\d+) temp_mC=(\d+) kHz=(\d+)$",
            result.stdout, flags=re.M,
        ):
            stages[label] = {"voltage_mv": int(volts), "temp_mc": int(temp),
                             "frequency_khz": int(clock)}
        assert list(stages) == ["before", "same", "low", "restored"]
        assert all(stage["frequency_khz"] == 700000 and stage["temp_mc"] < 75000
                   for stage in stages.values())
        assert len(re.findall(r"^VC selector=29 ", result.stdout, flags=re.M)) == 2
        assert len(re.findall(r"^VC selector=28 ", result.stdout, flags=re.M)) == 1
        assert abs(stages["restored"]["voltage_mv"] - stages["before"]["voltage_mv"]) <= 16
        report = {"passed": True, "transport_acknowledged": True,
                  "two_core_load": args.load,
                  "rail_drop_observed_mv": stages["same"]["voltage_mv"] - stages["low"]["voltage_mv"],
                  "source_sha256": sha(SOURCE), "binary_sha256": sha(BINARY),
                  "boot_id": state["boot_id"], "stages": stages}
    except BaseException as exc:
        failure = exc
        report = {"passed": False, "error": repr(exc), "boot_id": state["boot_id"],
                  "two_core_load": args.load,
                  "source_sha256": sha(SOURCE), "binary_sha256": sha(BINARY)}
    finally:
        report["started"] = started.isoformat()
        report["finished"] = datetime.now(timezone.utc).isoformat()
        report["returncode"] = result.returncode if result is not None else None
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        if uploaded:
            try:
                remote("rm -f " + TEMP + "\ntest ! -e " + TEMP + "\n")
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                print("RAM helper cleanup deferred to stock reboot: " + repr(exc), file=sys.stderr)
        request_recovery()
    print(json.dumps({"run": str(directory), **report}, indent=2))
    if failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
