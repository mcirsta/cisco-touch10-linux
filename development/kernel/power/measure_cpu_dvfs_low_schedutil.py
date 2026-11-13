#!/usr/bin/env python3
"""Record paired ram115 CPU clock, regulator and VC states under schedutil."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BINARY = HERE / "omap4_dvfs_low_sampler.arm"
SOURCE = HERE / "omap4_dvfs_low_sampler.c"
REVIEW = HERE / "omap4-dvfs-low-sampler-review.json"
TEMP = "/tmp/perrier-dvfs-sampler"
sys.path.insert(0, str(ROOT / "tools"))
import touch10_ram as ram

REMOTE = r'''set -eu
test "$(cat /run/touch10-ram)" = perrier-interactive-ram115
test "$(cat /sys/devices/system/cpu/online)" = 0-1
test "$(cat /sys/block/mmcblk0/ro)" = 1
policy=/sys/devices/system/cpu/cpufreq/policy0
test "$(cat "$policy/scaling_governor")" = performance
test "$(cat "$policy/scaling_cur_freq")" = 700000
workers=''
restore() {
    for worker in $workers; do kill "$worker" 2>/dev/null || true; done
    echo 700000 > "$policy/scaling_setspeed" 2>/dev/null || true
    echo performance > "$policy/scaling_governor" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
echo schedutil > "$policy/scaling_governor"
sleep 2
echo 'PHASE idle_before'
/tmp/perrier-dvfs-sampler
echo 'END_PHASE idle_before'
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 75000
yes >/dev/null & workers="$!"
yes >/dev/null & workers="$workers $!"
sleep 1
echo 'PHASE load'
/tmp/perrier-dvfs-sampler
echo 'END_PHASE load'
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 80000
for worker in $workers; do kill "$worker" 2>/dev/null || true; done
workers=''
sleep 5
echo 'PHASE idle_after'
/tmp/perrier-dvfs-sampler
echo 'END_PHASE idle_after'
test "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 75000
echo performance > "$policy/scaling_governor"
sleep 2
test "$(cat "$policy/scaling_cur_freq")" = 700000
echo SAMPLER_PASS
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recover() -> None:
    current = json.loads(ram.CURRENT.read_text())
    assert current["status"] in ("interactive", "recovering")
    assert current["profile"] == "cpu-dvfs-low-trial"
    target = Path(current["directory"]) / "recover-request.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"mode": "cpu_dvfs_sampler_complete"}) + "\n")
    os.replace(temporary, target)


def parse(stdout: str) -> dict:
    phases: dict[str, list[dict]] = {}
    current = None
    for line in stdout.splitlines():
        if line.startswith("PHASE "):
            current = line.split()[1]
            phases[current] = []
        elif line.startswith("END_PHASE "):
            assert current == line.split()[1]
            current = None
        elif current and line == "ms,policy_khz,hardware_khz,regulator_uv,vc_before,vc_after,valid_before,valid_after,vc_irq":
            pass
        elif current:
            ms, freq, hw, uv, before, after, valid_before, valid_after, irq = line.split(",")
            phases[current].append({"ms": int(ms), "policy_khz": int(freq),
                                    "hardware_khz": int(hw), "regulator_uv": int(uv),
                                    "vc_before": int(before), "vc_after": int(after),
                                    "valid_before": int(valid_before),
                                    "valid_after": int(valid_after),
                                    "vc_irq": int(irq, 16)})
    assert list(phases) == ["idle_before", "load", "idle_after"] and current is None
    summary = {}
    for phase, samples in phases.items():
        assert len(samples) == 200
        assert all(s["policy_khz"] in (350000, 700000) and
                   s["hardware_khz"] in (350000, 700000) and
                   s["regulator_uv"] in (1101460, 1215400) and
                   s["vc_before"] in (32, 41) and s["vc_after"] in (32, 41) and
                   not (s["vc_irq"] & 0x3800) for s in samples)
        pairs = Counter((s["policy_khz"], s["hardware_khz"],
                         s["regulator_uv"], s["vc_before"], s["vc_after"])
                        for s in samples)
        stable_low_at_700 = sum(s["hardware_khz"] == 700000 and
                                s["vc_before"] == s["vc_after"] == 32 and
                                not s["valid_before"] and not s["valid_after"]
                                for s in samples)
        summary[phase] = {"count": len(samples),
                          "pairs": [{"policy_khz": k[0], "hardware_khz": k[1],
                                     "regulator_uv": k[2], "vc_before": k[3],
                                     "vc_after": k[4], "count": v}
                                    for k, v in pairs.most_common()],
                          "pending_samples": sum(s["valid_before"] or
                                                 s["valid_after"] for s in samples),
                          "stable_low_at_700_samples": stable_low_at_700}
        assert stable_low_at_700 == 0
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    review = json.loads(REVIEW.read_text())
    assert review["passed"] and review["source_sha256"] == sha(SOURCE)
    assert review["binary_sha256"] == sha(BINARY)
    if not args.execute:
        print(json.dumps({"ready": True, "binary_sha256": sha(BINARY)}, indent=2))
        return
    state = ram.ram_state("6.18.48-perrier-ram115")
    assert state["guard"]["backend"] == "linux-watchdog" and state["guard"]["nowayout"]
    started = datetime.now(timezone.utc)
    directory = ROOT / "development/runs" / (started.strftime("%Y%m%dT%H%M%SZ") + "-cpu-dvfs-low-sampler")
    directory.mkdir(mode=0o700)
    (directory / "command.sh").write_text(REMOTE)
    uploaded = False
    result = None
    report: dict = {"passed": False, "boot_id": state["boot_id"],
                    "binary_sha256": sha(BINARY), "started": started.isoformat()}
    try:
        preflight = ram.remote('test "$(awk \'$2 == "/tmp" {print $3}\' /proc/mounts)" = tmpfs\n'
                               'test ! -e /tmp/perrier-dvfs-sampler\n')
        if preflight.returncode:
            raise RuntimeError("RAM tmpfs preflight failed")
        upload = subprocess.run(ram.SSH + ["umask 077; cat > " + TEMP],
                                input=BINARY.read_bytes(), capture_output=True, timeout=20)
        if upload.returncode:
            raise RuntimeError("sampler upload failed")
        uploaded = True
        readback = subprocess.run(ram.SSH + ["cat " + TEMP], capture_output=True, timeout=20)
        if readback.returncode or readback.stdout != BINARY.read_bytes():
            raise RuntimeError("sampler RAM readback differs")
        chmod = ram.remote("chmod 700 " + TEMP + "\n")
        if chmod.returncode:
            raise RuntimeError("sampler chmod failed")
        result = ram.remote(REMOTE, timeout=105)
        (directory / "stdout.log").write_text(result.stdout)
        (directory / "stderr.log").write_text(result.stderr)
        if result.returncode or not result.stdout.endswith("SAMPLER_PASS\n"):
            raise RuntimeError("RAM sampling command failed")
        report.update(passed=True, summary=parse(result.stdout))
    except BaseException as exc:
        report["error"] = repr(exc)
    finally:
        report["finished"] = datetime.now(timezone.utc).isoformat()
        report["returncode"] = result.returncode if result is not None else None
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        if uploaded:
            try:
                ram.remote("rm -f " + TEMP + "\ntest ! -e " + TEMP + "\n")
            except Exception:
                pass
        recover()
    print(json.dumps({"run": str(directory), "passed": report["passed"],
                      "summary": report.get("summary"), "error": report.get("error")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
