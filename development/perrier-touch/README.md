# Native Gen4 touch in the Perrier RAM kernel

Linux 6.18.48 provides Cypress Gen3 and Gen5 drivers, but the upstream Gen4
driver was [removed in 2024](https://lkml.iu.edu/hypermail/linux/kernel/2408.0/03439.html)
because it only supported platform data and had no in-tree users. The
unmodified Linux 6.10 Gen4 sources are saved in [reference](reference/manifest.json).
They define the Gen4 system-information layout, touch records, host-mode
transition, and interrupt handshake used by the smaller Perrier driver.

The [stock touch identity](../../evidence/perrier-touch-sysfs-2026-11-08.txt)
is firmware 1.1, product 1, at I2C2 address `0x67`. A bounded
[live descriptor capture](../../evidence/perrier-touch-sysinfo-2026-11-09.txt)
reported a 1280×800 panel, ten contacts, seven-byte records, and an 82-byte
maximum frame. The capture returned the controller to operational mode.
The old bridge read 64 bytes every 50 ms and reported only its first contact.
Captured frames include two records where the first contact is released and
the second is pressed. That case is now covered by the parser replay.

The kernel driver uses standard I2C transfers, a threaded GPIO interrupt,
Linux type-B multitouch slots, and `touchscreen_report_pos()`. It discovers
and validates the controller's descriptor on each RAM boot. Its operations
are restricted to the already-running controller inherited through kexec:
system-information mode, operational reports, and host handshakes. The
board DT adds only GPIO142's falling-edge IRQ; GPIO141 reset, GPIO120/121
touch power, GPIO151, GPIO157, pinmux, and voltage settings are inherited.
The separate native image omits the userspace touch bridge and `/dev/uinput`.
Cold-start initialization and firmware management are future board-support
work and are outside this RAM-only driver.

## Build and test

From the workspace root:

```sh
python3 development/perrier-touch/test_protocol.py
python3 development/perrier-native/verify_patchset.py --patches development/perrier-touch/kernel-patches
cmake --build development/perrier-qt/build-arm-a9-local
python3 development/perrier-qt/stage_runtime.py
python3 development/perrier-qt/preflight_qemu.py
python3 development/perrier-ramenv/build_image.py --profile native-touch
python3 development/perrier-touch/audit_image.py
python3 tools/touch10_ram.py session --profile native-touch --minutes 120
```

When the controller prints `RAM_READY`, use a second terminal:

```sh
python3 tools/touch10_ram.py qt-restart
ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram 'cat /proc/bus/input/devices; cat /proc/interrupts; cat /run/guard.json'
ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram 'tail -n 30 /tmp/qt-active.log'
```

The host controller creates a fresh 64-byte random seed for each native RAM
boot and passes it through the standard `/chosen/rng-seed` device-tree
property. Linux consumes and clears that property at boot. Without this
seed, the new kernel waits for entropy and Dropbear may not open its SSH
listener before the watchdog's boot grace expires. The derived DTB is
verified against the audited original, used once, and deleted from the host.
No seed is logged or added to the saved image.

The image keeps the existing 120-second WDT2 watchdog, 60-second renewed
host lease, key-only SSH, and eMMC read-only setting. A failed RAM boot
returns to stock. The first two native boots proved this recovery path when
SSH timed out; both returned Linux 3.4 and Phoenix with the U-Boot environment
hash unchanged. The seeded RAM boot
[20261109T162416Z-interactive-17a1c1](../runs/20261109T162416Z-interactive-17a1c1/result.json)
reached SSH and ran Qt on `/dev/input/event0`. A read-only
[framebuffer capture](../../evidence/perrier-native-qt-frame-2026-11-09.png)
shows the Qt grid at 1280×800 with its center and four corner targets in the
expected positions, but the user's [panel photo](../../evidence/perrier-ram45-initial-wrap-2026-11-09.jpg)
showed the image horizontally wrapped after scanout. One controlled
framebuffer off/on cycle changed the wrap, as shown in the
[second photo](../../evidence/perrier-ram45-cycle-wrap-2026-11-09.jpg).
The RAM test returned to stock with the boot-environment hash unchanged.
That first native image did not permit physical validation of the kernel
touch path.

Stock CE9.9.0 programs and latches TC358765 before enabling pixel scanout.
Mainline's bridge-chain enable order started DSI video before the downstream
bridge was programmed. Early bridge programming in `ram46` failed with an
I2C NACK. `ram47` first enabled the DSI host, and `ram48` kept reset
deasserted, but both still got the NACK. The `ram49` trace showed DSI host
startup had finished and the reset pin was physically high before the NACK;
the bridge became available only after the later video stage.

`ram50` prepares the DSI video channel without starting the DISPC pixel
manager, then programs TC358765 in its `atomic_pre_enable`, and finally
starts scanout. The bridge responded with ID `0x6500` before scanout. The
[live register capture](../../evidence/perrier-ram50-bridge-live-2026-11-09.txt)
matches all stock configuration registers; only interrupt/error status
differs. The [RAM framebuffer capture](../../evidence/perrier-ram50-qt-fb0-2026-11-09.png)
shows the expected unshifted grid. The user confirmed that all five targets
appeared at their correct physical positions. The
[native event log](../../evidence/perrier-ram50-native-touch-qt-2026-11-09.log)
contains direct kernel X/Y reports near CENTER `(640,400)`, UL `(84,132)`,
UR `(1177,146)`, LL `(88,712)`, and LR `(1180,707)` against targets
`(640,400)`, `(90,130)`, `(1190,130)`, `(90,710)`, and `(1190,710)`.
[All ten tracking slots](../../evidence/perrier-ram50-native-touch-slot-state-2026-11-09.txt)
were idle after the taps. This is a RAM handoff path;
the stock-initialized bridge remains out of reset, and cold-start support is
separate work.
