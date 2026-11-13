#!/usr/bin/env python3
"""Check that two quiet application streams can share the RAM speaker PCM."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[2]
SSH_CONFIG = ROOT / "access/ssh_config"
MIX_CONFIG = ROOT / "development/audio/asound-mix.conf"
MIX_LIBRARY = ROOT / "development/audio/shared-install/libasound-dmix.so.2"
ALSA_BASE = ROOT / "development/audio/app-install/etc/alsa/alsa.conf"
SSH = ["ssh", "-F", str(SSH_CONFIG), "touch10-ram"]
PUSH = ["python3", str(ROOT / "tools/touch10_ram.py"), "push"]


def pair(config=None, new_library=False):
    environment = "LD_LIBRARY_PATH=/tmp:/qt/lib " if new_library else ""
    config_path = f"ALSA_CONFIG_PATH={config} " if config else ""
    command = (f"{environment}{config_path}/usr/bin/aplay -q -D default "
               "/tmp/perrier-silent.wav")
    started = time.monotonic()
    first = subprocess.Popen(SSH + [command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        time.sleep(1)
        second = subprocess.Popen(SSH + [command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            second_out, second_err = second.communicate(timeout=20)
            first_out, first_err = first.communicate(timeout=20)
        finally:
            if second.poll() is None:
                second.kill()
    finally:
        if first.poll() is None:
            first.kill()
    return {
        "first_exit": first.returncode,
        "second_exit": second.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "first_output": (first_out + first_err).decode(errors="replace")[-1000:],
        "second_output": (second_out + second_err).decode(errors="replace")[-1000:],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packaged", action="store_true",
                        help="test the installed /etc/asound.conf and library")
    args = parser.parse_args()
    kernel = subprocess.check_output(SSH + ["uname -r"], text=True, timeout=10).strip()
    assert kernel in (("6.18.48-perrier-ram103", "6.18.48-perrier-ram104",
                       "6.18.48-perrier-ram110")
                      if args.packaged else ("6.18.48-perrier-ram100",)), kernel
    with tempfile.TemporaryDirectory(prefix="perrier-mix-") as temporary:
        silent = Path(temporary) / "perrier-silent.wav"
        with wave.open(str(silent), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(48000)
            out.writeframes(bytes(48000 * 2 * 8))
        subprocess.run(PUSH + [str(silent), "/tmp/perrier-silent.wav"],
                       check=True, capture_output=True, timeout=20)
        if args.packaged:
            mixed = pair()
            report = {"kernel": kernel, "packaged": mixed,
                      "passed": mixed["first_exit"] == 0 and
                      mixed["second_exit"] == 0 and
                      mixed["elapsed_seconds"] < 13}
            print(json.dumps(report, indent=2))
            if not report["passed"]:
                raise SystemExit(1)
            return
        subprocess.run(PUSH + [str(MIX_CONFIG), "/tmp/asound-mix.conf"],
                       check=True, capture_output=True, timeout=20)
        subprocess.run(PUSH + [str(MIX_LIBRARY), "/tmp/libasound.so.2"],
                       check=True, capture_output=True, timeout=20)
        base = ALSA_BASE.read_text()
        start = base.index("@hooks [")
        end = base.index("\n]\n", start) + len("\n]\n")
        # ALSA_CONFIG_PATH replaces the global file. Include its timer and
        # card definitions, but omit only its top-level /etc/asound.conf hook.
        # Production uses that hook to load asound-mix.conf from /etc.
        full = Path(temporary) / "asound-full.conf"
        full.write_text(base[:start] + base[end:] + "\n" + MIX_CONFIG.read_text())
        subprocess.run(PUSH + [str(full), "/tmp/asound-full.conf"],
                       check=True, capture_output=True, timeout=20)
        control = pair("/etc/asound.conf")
        mixed = pair("/tmp/asound-full.conf", new_library=True)
    report = {"kernel": kernel, "baseline": control, "dmix": mixed,
              "passed": control["first_exit"] == 0 and control["second_exit"] != 0
              and mixed["first_exit"] == 0 and mixed["second_exit"] == 0
              and mixed["elapsed_seconds"] < 13}
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
