# Interactive Touch 10 RAM Linux

For current development, use the
[active kernel workspace](../kernel/README.md) and
[current U-Boot workflow](../../DEVELOPMENT-WORKFLOW.md). Its default is
ram100 (`native-diagnostics`), with ram99 (`speaker-audio`) preserved as the
fallback, native kernel touch and the mainline OMAP watchdog. The older
kexec images and procedures below remain diagnostic
fallbacks.

The newer [ram59 watchdog profile](../perrier-watchdog/README.md) carries the
full ram58 peripheral support and uses the mainline OMAP watchdog API. It has
its own passing hardware-expiry proof and supplied the recovery base for ram60.
Use `--profile native-watchdog` to select it; existing profiles stay available.

Routine kernel tests now use the
[ram60 U-Boot workflow](../perrier-cold-ethernet/README.md), which has working
Ethernet/root SSH and hardware-expiry recovery after U-Boot. Run
`python3 tools/touch10_uboot.py prepare` and then
`python3 tools/touch10_uboot.py session --minutes 30`. A kexec pass is not
required before each image. The commands below retain the older kexec route
for specific diagnostics; RAM SSH, transfer, Qt restart, and recovery controls
also work with the U-Boot session controller.

This image boots the reviewed Perrier Linux 6.18.48 board support through
`kexec` from stock firmware. It uses the audited board DTB and reviewed
kernel patches from the visible LCD trial. The image mounts no eMMC filesystem;
the temporary kernel marks its eMMC block devices read-only. It starts a
key-only root SSH server, a Gen4 touch-to-evdev bridge, BusyBox, `strace`,
`gdbserver`, and the locally built Qt 6.12 runtime. The Qt app can be uploaded
and restarted independently of the kernel.

The [native Gen4 touch image](../perrier-touch/README.md) is a separate RAM
profile. It uses the same watchdog controller and SSH workflow while replacing
the userspace bridge with a kernel input driver. Its build and audit commands
are documented there. The default profile here remains the older userspace
bridge fallback; the native profile has now passed physical alignment and
five-target kernel touch checks on ram50.

## Recovery

The stock watchdog is armed for 120 seconds before `kexec`. RAM Linux keeps
it running by writing only WDT2's trigger register; its kernel watchdog driver
remains disabled. The host controller renews a 60-second lease every 10
seconds. When that lease expires, the RAM feeder requests a normal reboot.
If Linux freezes, the hardware watchdog returns the board to stock.

The first live recovery proof is in [watchdog-proof.json](watchdog-proof.json):
the RAM environment stayed healthy for 130 seconds beyond SSH readiness,
then feeding stopped and stock returned after 153.6 seconds. The stock U-Boot
environment SHA-256 was unchanged. The proof is tied to the feeder binary's
SHA-256; a changed feeder requires another proof before a long session.

## Daily use

From the workspace root, when stock firmware is running:

```sh
python3 development/perrier-ramenv/audit_image.py
python3 tools/touch10_ram.py session --minutes 120
```

The controller prints `RAM_READY` once SSH is available, usually around a
minute after `kexec` while the fresh kernel seeds its random generator. Keep
the controller process running; it renews the watchdog lease and returns the
board to stock at the requested deadline. The current status and logs are
under `development/perrier-ramenv/current-session.json` and the run folder
named there. To request an earlier, checked return to stock:

```sh
python3 tools/touch10_ram.py recover
```

For an interactive root shell and file transfer:

```sh
ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram
python3 tools/touch10_ram.py push ./my-arm-binary /tmp/my-arm-binary
scp -O -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram:/tmp/qt-active.log ./qt-active.log
```

The `touch10-ram` SSH alias pins a **different host key** from stock Linux
at the same IP address. The controller checks the RAM marker, kernel release,
boot ID, and watchdog state before offering file uploads.

To rebuild and restart the Qt grid without rebooting:

```sh
cmake --build development/perrier-qt/build-arm-a9-local
python3 tools/touch10_ram.py qt-restart
ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram 'tail -n 30 /tmp/qt-active.log'
```

`qt-restart` hashes the executable, uploads it into `/tmp`, terminates only
the registered Qt PID, waits for a clean exit, and starts the new binary.
The app reads `/dev/input/event0` directly through Qt's main event loop.
The linuxfb plugin's own evdev input thread caused a repeatable crash during
shutdown; `QT_QPA_FB_DISABLE_INPUT=1` prevents that thread from starting.
The app now exits cleanly after its timer and on SIGTERM, with no `_Exit`
workaround.

The grid shows a red marker using the selected horizontal touch mapping and
a cyan marker using the opposite mapping. Direct touch X/Y is confirmed.
The first RAM kernel's panel scanout rotated framebuffer pixels right by
about 214 pixels. Selecting the stock DISPC core clock aligned the ram44
run, but ram45 wrapped again despite the same steady-state register values.
Ram50 now starts the DSI video channel, configures TC358765, and then starts
scanout; the user confirmed all targets aligned without Qt scene compensation.
The temporary scene-shift and movable-center controls
have been removed. `--x-offset PIXELS` and `--mirror-x` remain optional input
diagnostics; the confirmed default uses neither. Raw and mapped touch
coordinates appear in `/tmp/qt-active.log`. The
[calibration record](../../evidence/perrier-qt-horizontal-calibration-2026-11-09.md)
includes the earlier diagnostic photos, the kernel-fix logs, and physical
confirmation from the 2026-11-09 interactive run.

For debugging, run `/usr/bin/strace` or `/usr/bin/gdbserver` over RAM SSH;
the matching host GDB is
`development/perrier-qt/sources/armv7-eabihf--musl--stable-2026.08-1/bin/arm-buildroot-linux-musleabihf-gdb`.
The example [qt-exit.gdb](qt-exit.gdb) shows GDB's SSH stdio connection.
`/usr/bin/event-dump /dev/input/event0` prints raw evdev records and does not
grab the device, so it can run beside Qt. The controller bridge logs its
decoded I2C coordinates in `/tmp/touch-raw.log`.

## Rebuilding the image

The source inputs and checked hashes are recorded in
[build_tools.py](build_tools.py), [tools-manifest.json](tools-manifest.json),
and [downloads/manifest.json](downloads/manifest.json). The target binaries
use the Cortex-A9 hard-float toolchain from `development/perrier-qt`. To
rebuild the tools and then the RAM kernel image:

```sh
python3 development/perrier-ramenv/build_tools.py
python3 development/perrier-ramenv/build_image.py
python3 development/perrier-ramenv/audit_image.py
```

The audit checks pinned artifacts, the unchanged DTB and kernel patches,
kernel boot bounds, software-only configuration additions, packed initramfs
contents, root key permissions, and required recovery options. Changes to
the Qt app can be iterated live; rebuild the image only when preparing the
next reproducible RAM boot.

The display-clock fix and cleaned Qt app are saved in
[baselines/ram44-clockfix-clean-qt](baselines/ram44-clockfix-clean-qt/validation.json).
Its record separates the physically confirmed kernel run and live app restart
from the subsequent audited image rebuild.
