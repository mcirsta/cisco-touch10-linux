# Perrier RAM kernel bring-up, 2026-11-08

## Current scope and safety boundary

The current Linux 6.18.48 image is a temporary kexec trial. Its DT enables
UART, USB Ethernet, OMAP SDMA, MMC2, I2C2/I2C3, and a passive mainline
`simplefb` handoff of the stock display buffer pool. The eMMC block driver is
board-gated read-only, and the ext4 base partition is mounted with `ro,noload`
to prevent journal replay. The three factory SquashFS application images are
mounted through read-only loop devices. The hardware watchdog stays armed;
PID 1 requests a normal reboot after 30 seconds. The test runner verifies
return to the stock kernel, `phoenix` process, and unchanged boot environment.

The [ram04 result](../runs/20261108T103437Z-perrier-trial-ca92e1/result.json)
identified all 16 GPT partitions and matched the saved backup's first-sector
CRC, `f5c4e784`, while all eMMC areas reported read-only. The
[ram05 result](../runs/20261108T103938Z-perrier-trial-12b97c/result.json)
mounted p14 read-only without journal replay and read the installed
`ce9.9.0` version. The [ram06 capture](../runs/20261108T104449Z-perrier-trial-d02244/serial.log)
shows read-only mounts of `/extra`, `/gui`, and `/apps`, and healthy stock
recovery. Its automated checker reported failure because a kernel message
interleaved with one serial proof line; the raw capture and result record are
preserved. The [ram07 result](../runs/20261108T104804Z-perrier-trial-9f27fe/result.json)
passed the full checker with SquashFS extended attributes enabled: all three
mounts were read-only, no xattr warnings appeared, Ethernet answered 3/3
pings, and stock returned with the boot environment hash unchanged.
The [ram08 capture](../runs/20261108T110556Z-perrier-trial-6fef7f/serial.log)
first registered the I2C2 adapter, but its checker used the obsolete sysfs
path and reported a false failure. The [ram09 result](../runs/20261108T110924Z-perrier-trial-8d4027/result.json)
passed with the corrected check. It registered only the I2C2 adapter; no
touch child was created and PID 1 sent no I2C messages. Ethernet and all
read-only storage checks passed, and stock returned with the environment
hash unchanged.
The [ram10 result](../runs/20261108T111549Z-perrier-trial-b5db48/result.json)
passed with both I2C2 and I2C3 adapters registered. Their device-tree buses
have no children, and PID 1 made no I2C transfers. All read-only storage and
Ethernet checks passed, the panel returned to the factory kernel and running
`phoenix` application, and the boot-environment hash was unchanged.
The [ram11 result](../runs/20261108T113208Z-perrier-trial-fa13ef/result.json)
passed a single touchscreen transport check. PID 1 selected register zero
at I2C address `0x67` and read 16 bytes,
`80006603000000000302000000000000`; it cached and reported the result twice
without another I2C transfer. The factory kernel returned with the same
boot-environment hash. Its touchscreen driver reported `ACTIVE` and the same
firmware identity afterward, and the display remained enabled. This proves
basic I2C communication, not touch event decoding or a working input driver.

The [ram13 result](../runs/20261108T115707Z-perrier-trial-76ca6e/result.json)
passed a framebuffer memory test. Stock DRM exposed three adjacent
`1280x800@AR24` Phoenix buffers at `0x7ec78000`, `0x7f060000`, and
`0x7f448000`; the active GFX plane switched between them. A host preflight
confirmed those exact addresses before kexec. Mainline `simplefb` registered
one `/dev/fb0` mapping their contiguous 12,288,000-byte TILER view. PID 1
saved a 96x48 rectangle in each buffer, drew a green rectangle with magenta
border for 10 seconds, read it back, and restored all pixels. This verifies
CPU access to inherited scanout memory. No one was watching the panel during
the test, so that simplefb marker's visibility was unconfirmed. The stock
kernel, `phoenix`,
touch driver `ACTIVE`, and enabled display returned; the boot environment
hash did not change. The first ram12 run failed to obtain a resource because
`/chosen` lacked address translation. The corrected ram12 run registered
`simplefb` but had no `/dev/fb0` because `CONFIG_FB_DEVICE` was omitted.
Both failures recovered stock normally; their logs remain in `development/runs`.
The [ram14 result](../runs/20261108T120521Z-perrier-trial-cd7f63/result.json)
passed a 30-second idle touch capture while the display marker was present.
PID 1 selected register zero and read 64 bytes every 100 ms for 300 samples;
all reads succeeded and the report remained identical; no tap was coordinated
for this baseline. The marker was restored, stock booted normally, the
factory display stayed enabled, the touch driver reported `ACTIVE`, and the
boot environment hash matched. A physical tap during a repeat capture is
needed to identify event bytes; the stock driver remains the only proven
source of decoded touch input.

The separate [simpledrm RAM candidate](../perrier-simpledrm/README.md)
reached a synthetic connected 1280×800@60 KMS mode. The temporary-kernel
screen was black in ram18; a read-only DISPC snapshot found the LCD manager
disabled after kexec. The newer [native LCD candidate](../perrier-native/README.md)
uses mainline OMAP DRM, DSI, the TC358765 bridge variant and `panel-lvds`.
Ram36 displayed a visible 1280×800 pattern after restoring stock-high
GPIO163 through a fixed regulator. The clean rebuild was also observed
working, and both runs returned to stock with the boot environment unchanged.
Current touch evidence is in [touchscreen.md](touchscreen.md).

The baseline kernel keeps the display drivers disabled; the native candidate
enables the display controller, I2C3 bridge, GPIO102 reset and the GPIO163
LCD rail. Neither image initializes the display from a cold boot. The fixed
2.95 V eMMC regulator node has no control GPIO and describes a rail
established by stock firmware before kexec; a cold boot with this DT has not
been tested. The stock panel uses a TWL6032 PMIC, a
CYTTSP4 touchscreen on I2C2, a TC358765 display bridge on I2C3, a PCF8574
GPIO expander on I2C4, and a 1280x800 LVDS panel. Their power sequencing,
pin states, and reset lines must be mapped from stock before activation.
The current evidence and GPIO/rail guardrails are in
[hardware-safety.md](hardware-safety.md).
The display/GPU driver choice is recorded in [graphics-stack.md](graphics-stack.md).

Ram50 now has a native Gen4 touch driver and physically aligned display.
Ram51 adds native timer10 PWM/backlight control and a Qt touch slider.
Ram52 adds the mainline OMAP4 matrix keypad for the three bezel buttons;
all three generated the expected events, and the final image matches the
stock key and repeat capability masks. See the
[keypad trial](../perrier-keypad/README.md).
The [SMP investigation](../perrier-smp/README.md) tested mainline CPU1 support
under RAM kexec. The dual-core image did not reach serial output; one-core SMP
variants reached kernel init but panicked while unpacking their built-in
initramfs. A non-SMP comparison with the same current Qt archive booted and
exposed Ethernet, display, touch, keypad, and backlight. All trials returned
to stock with the boot environment unchanged. Continue from the proven
single-core image while the SMP handoff and archive corruption are diagnosed.
GPIO157 5 V sequencing, pinctrl, and cold-start power remain to be ported,
followed by one-change-at-a-time reduction of the board-gated display
patches against the saved visible baseline.
Persistent boot or eMMC changes are outside this bring-up sequence.

## Ethernet RAM trial

Linux `6.18.48-perrier-ram02` now boots the OMAP EHCI host and the panel's
SMSC95xx USB Ethernet controller. The UART capture shows USB enumeration on
port 1, the LAN8710/LAN8720 PHY, and a 100 Mb/s full-duplex link. The
initramfs assigns `10.77.10.10/24`; the directly attached PC at `10.77.10.1`
received ICMP replies. The first trial used a generated MAC because the
controller lacks a usable EEPROM address. A USB device-tree child now supplies
this unit's factory address, `24:16:9d:b6:77:bb`, and the second trial
confirmed that the kernel uses it.

The first network proof is
[`development/runs/20261108T101111Z-perrier-trial-1c11e9/result.json`](../../development/runs/20261108T101111Z-perrier-trial-1c11e9/result.json),
with driver and link messages in its `serial.log`. The factory kernel and
`phoenix` application returned, and the boot environment hash was unchanged.
The [second trial result](../../development/runs/20261108T101408Z-perrier-trial-5f9354/result.json)
confirms the factory MAC and healthy stock recovery.

The DT exposes only the USB host target module, EHCI controller, and this USB
LAN device while the generic OMAP peripheral bus remains disabled. Its port
and external PHY are already powered and muxed by the factory kernel before
RAM kexec. A cold boot of this DT without the factory firmware's setup has
not been tested. No GPIO or pad register is written by this build. The
watchdog remains armed and PID 1 requests a normal reboot after 30 seconds.
Reviewed images are preserved in `development/perrier/baselines/ram01/`
through `development/perrier/baselines/ram11/`, plus the passing ram13 and ram14
builds.

## First serial and timer trial

The first minimal Perrier kernel, Linux `6.18.48-perrier-ram01`, booted through
the stock Linux 3.4 kexec path. The embedded PID 1 reported its kernel version,
zero block devices, and an advancing watchdog counter. An initial test let the
watchdog restore stock after about 120 seconds. That serial-only init requested
a normal reboot after 15 seconds, leaving the watchdog armed as fallback. Root
SSH and the factory `phoenix` application returned. The boot-environment p8
SHA-256 remained `f0fefd27f1ca21360dfe437919e03c5a6ee4c119df3e6070301a8f3879d181ad`.

The timing and watchdog proof is
[`development/runs/20261108T095058Z-perrier-trial-6970be/result.json`](../../development/runs/20261108T095058Z-perrier-trial-6970be/result.json),
and the software-return test is
[`development/runs/20261108T095904Z-perrier-trial-4bbf91/result.json`](../../development/runs/20261108T095904Z-perrier-trial-4bbf91/result.json),
with timestamped UART output in the sibling `serial.log`. The immediately
preceding `perrier-load-check` passed. Earlier recovered trials found and
fixed omitted ARM physical address handling and kernel NEON support. None
changed installed firmware or boot configuration.

The source is the official Linux 6.18.48 archive in `development/sources/`,
SHA-256 `5ebdadb10a4b5708fc6b1c457764a110bc49f8150cc3502c59b921ead8c6fc8c`.
It matched the kernel.org signed checksum list. Its tar signature verified
against Greg Kroah-Hartman's key fingerprint
`647F28654894E3BD457199BE38DBBDC86092693E` in an isolated keyring.
`build.py` records all resulting artifact hashes in `manifest.json`; `audit.py`
checks the resolved config and compiled DTB, then pins the three loaded files
in `reviewed-trial.json`. The build uses Clang/LLD 23.1.4 for the kernel and
Zig 0.15.2/ARM musl for the static init program.

The DTB limits RAM to the stock-observed low 400 MiB, exposes the known UART,
and disables platform population of the generic OMAP peripheral bus. Both watchdog
target modules and child nodes are disabled. Early clock and timer metadata
remain available. The board-compatible source patches avoid USB/audio PLL
policy changes and late voltage/PM policy. The initramfs contains only `/init`,
`/dev/console`, `/dev/mem`, and mount-point directories. It reads the watchdog
counter at `0x4a314028`; it never opens `/dev/watchdog`.

The stock 3.4 kexec handoff provides a legacy ATAG-style r2 address. The
opt-in `TOUCH10_LEGACY_ARM_FDT=1` loader adds a 16-byte RAM trampoline that
sets r2 to the loaded DTB and branches to the zImage. The original qualified
loader is preserved at `development/ram/kexec-qualified`. All loaded segments
were in separate regions of the verified low RAM range.

The first initramfs appeared to show a fast timer: its unchecked `sleep()`
returned at once. Both stock and RAM kernels had TIMER1 source selection
`CM_WKUP_TIMER1_CLKCTRL=0x01000002`, choosing 32 kHz. The actual fault was
`CONFIG_COMPAT_32BIT_TIME=n`, which removed the legacy 32-bit time syscalls
used by the ARM musl initramfs. Restoring that option gives a successful
`sleep(1)` with 33,091 watchdog ticks of progress, then five-second serial
markers at five-second wall intervals. A trial with the stock-style ARM local
timer also exhibited the same immediate-return behavior, confirming TIMER1
was not the cause. The final image returns to the smaller single-CPU config.
The first image had no network or storage drivers. Later images added Ethernet
and read-only storage. This remains an early bring-up candidate, not a complete
firmware replacement.

The stock panel's LAN adapter is USB vendor `0424`, product `9e00`, at
`/sys/bus/usb/devices/1-1`, 480 Mb/s on OMAP EHCI. Stock serial logs identify
the `smsc95xx` driver and EHCI MMIO at `0x4a064c00`. The factory
`perrier_init` configures GPIO 137 (`pca9500_write_enable`), GPIO 158
(`lan_reset`), a 19.2 MHz auxiliary PHY clock, and GPIO 110 (`usb_phy_reset`) before
starting USB host. The RAM trial inherits those settings across kexec.

Build and verify with:

```sh
python3 development/perrier/build.py
python3 development/perrier/audit.py
PYTHONPATH=tools python3 -m unittest tools/test_touch10_dev.py
python3 tools/touch10_dev.py perrier-load-check
python3 tools/touch10_dev.py perrier-trial --timeout 600
```

The last two commands access the panel by the dedicated SSH key, use passive
UART capture, and arm the hardware watchdog before executing the RAM image.
