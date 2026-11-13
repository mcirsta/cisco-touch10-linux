#!/usr/bin/env python3
"""Build an isolated ALSA-lib candidate with upstream dmix for RAM trials."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLCHAIN = ROOT / "development/perrier-qt/sources/armv7-eabihf--musl--stable-2026.08-1"
BUILD = HERE / "shared-build/alsa-lib"
INSTALL = HERE / "shared-install"
LOG = ROOT / "development/kernel/out/application-audio"
PIN = "f44e0abd5382f519cc6fa69850c34e6e9c09d5f5"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    LOG.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    assert subprocess.check_output(["git", "-C", str(HERE / "alsa-lib"), "rev-parse", "HEAD"],
                                   text=True).strip() == PIN
    assert not subprocess.check_output(["git", "-C", str(HERE / "alsa-lib"),
                                        "diff", "--name-only"], text=True).strip()
    args = json.loads((HERE / "alsa-configure-args.json").read_text())
    plugins = [arg for arg in args if arg.startswith("--with-pcm-plugins=")]
    assert len(plugins) == 1 and "dmix" not in plugins[0].split("=", 1)[1].split(",")
    args[args.index(plugins[0])] = plugins[0] + ",dmix"
    compiler = TOOLCHAIN / "bin/arm-buildroot-linux-musleabihf-gcc"
    strip = TOOLCHAIN / "bin/arm-buildroot-linux-musleabihf-strip"
    env = dict(os.environ, PATH=str(TOOLCHAIN / "bin") + ":" + os.environ["PATH"],
               CC=str(compiler), CFLAGS="-Os -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard")
    def run(command, cwd, log):
        with (LOG / log).open("w") as stream:
            subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
    run(args, BUILD, "dmix-configure.log")
    run(["make", "-j" + str(os.cpu_count() or 1)], BUILD, "dmix-build.log")
    run(["make", "DESTDIR=" + str(INSTALL), "install"], BUILD, "dmix-install.log")
    source = INSTALL / "usr/lib/libasound.so.2.0.0"
    candidate = HERE / "shared-install/libasound-dmix.so.2"
    shutil.copy2(source, candidate)
    subprocess.run([str(strip), "--strip-unneeded", str(candidate)], check=True)
    report = {"source_commit": PIN, "source_unmodified": True,
              "configure": args[1:], "candidate": str(candidate),
              "sha256": sha(candidate), "bytes": candidate.stat().st_size,
              "baseline_library_sha256": sha(ROOT / "development/perrier-qt/runtime/lib/libasound.so.2")}
    (LOG / "dmix-build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
