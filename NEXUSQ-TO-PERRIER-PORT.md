# Nexus Q Reloaded to Touch 10 Perrier port plan

Status: port planning, 2026-11-08. The owner subsequently authorized
development and RAM-only kexec/watchdog recovery tests. Their passing live
qualification is in [`DEVELOPMENT-WORKFLOW.md`](DEVELOPMENT-WORKFLOW.md).
Persistent boot/firmware changes remain outside those RAM tests.

## Pinned starting point

- Shallow clone: [`nexusQ-reloaded/`](nexusQ-reloaded/), upstream
  `https://github.com/petronijus/nexusQ-reloaded.git`, commit
  `4d79273e07250ef189a41320b4f1e8e28339f635` (2026-11-01). The clone was
  clean after download. Its root license is GPL-2.0; preserve original notices
  if code is copied.
- This repository is a *porting layer*, not a Linux checkout. Its
  [`APKBUILD`](nexusQ-reloaded/pmos/linux-google-steelhead/APKBUILD) downloads
  Linux 6.18.48 and applies 79 patches. It supplies a
  [Steelhead DTS](nexusQ-reloaded/kernel/dts/omap4-steelhead.dts),
  [defconfig](nexusQ-reloaded/kernel/configs/steelhead_defconfig), and
  [patch series](nexusQ-reloaded/kernel/patches/).
- Use Linux 6.18.48 as the initial comparison target, pinned and checked
  against the official source checksum/signature when downloaded. Start with
  **zero Steelhead patches**. Add a patch only for a reproduced Perrier problem;
  in particular, [0050](nexusQ-reloaded/kernel/patches/0050-ARM-OMAP4-HS-configure-CPU1-CP15-via-PPA-on-4460-too.patch)
  is a candidate for later CPU1/SMP testing, not an initial requirement.
- The host has Clang 23.1.4, LLD, LLVM binutils, `dtc`, and `cpio`; it lacks
  an ARM32 cross-GCC. Zig 0.15.2 has now built validated static ARM32 loader
  and watchdog helpers. The separate Linux 6.18.48 Perrier kernel build and
  RAM-only kexec trial are documented in `development/perrier/README.md`.

### Kernel baseline decision (2026-11-08)

[Kernel.org](https://www.kernel.org/) lists 7.3.3 as stable and 6.18.62 as
longterm; [6.18 is projected to be maintained through December
2028](https://www.kernel.org/releases.html). The upstream
[`omap4460.dtsi` in 6.18](https://github.com/torvalds/linux/blob/v6.18/arch/arm/boot/dts/ti/omap/omap4460.dtsi)
and [7.3](https://github.com/torvalds/linux/blob/v7.3/arch/arm/boot/dts/ti/omap/omap4460.dtsi)
were byte-identical in a selected-file comparison. Both have TC358765 support
through the [`tc358775.c` bridge driver](https://github.com/torvalds/linux/blob/v7.3/drivers/gpu/drm/bridge/tc358775.c).
The [7.3 upstream Cypress I²C driver](https://github.com/torvalds/linux/blob/v7.3/drivers/input/touchscreen/cyttsp_i2c.c)
does not list this panel's CY8CTMA884/CYTTSP4 controller. These checks show no
specific 7.3 gain for the first Perrier boot; they are not a full driver audit.
Start on the Nexus Q project's exact 6.18.48 source revision for comparable
diagnostics, move to the current 6.18 longterm point release after basic RAM
boot is stable, and try 7.3 only for a demonstrated hardware or driver benefit.
The hardware safety gate below applies to every kernel version.

## Board crosswalk

| Subsystem | Nexus Q `steelhead` | Touch 10 `perrier` and porting consequence |
| --- | --- | --- |
| SoC | OMAP4460, 1 GiB RAM | OMAP4460 ES1.1, 1 GiB physical RAM. Start from upstream `omap4460.dtsi`; establish Perrier's usable memory and reservations. |
| Boot | Android `boot.img`, fastboot, Steelhead partitions | Cisco signed ROM/MLO/U-Boot; `bootz` executed a RAM-modified zImage. Do not use Nexus Q `make-bootimg.py`, fastboot flash instructions, or partition numbers. |
| Console | DTS uses `uart3` | Stock service UART is `ttyO2` at `0x48020000`. Map to the modern UART3 node and confirm its Linux 6.18 console name. |
| Power | Steelhead TWL6030/TPS62361 wiring and voltages | Perrier log identifies TWL6032 at I²C1 `0x48`; rail topology, regulator voltages, and GPIO enables require board evidence. Never copy Steelhead voltage/OPP patches. |
| Storage | 16 GiB eMMC, root on p13 | 4 GiB eMMC; stock p14 holds the active ext4 base, p8 is the single U-Boot environment, and p12 is unproven as a fallback. |
| Network | LAN9500A through EHCI, Steelhead-specific PHY power sequence | SMSC95xx USB Ethernet on EHCI. The driver family is useful; clock, reset, and GPIO sequence must be measured on Perrier. |
| Display/input | HDMI, no built-in touchscreen | 1280×800 OMAP DSI → TC358765 LVDS bridge, timer-10 backlight, CYTTSP4 touch at I²C2 `0x67`. Requires new DT/driver integration. |
| Other I²C | Steelhead peripherals | Perrier has PCF8574 at I²C4 `0x24`, EEPROM at I²C4 `0x54`, and TMP102 at I²C3 `0x48`. Do not import Steelhead Wi-Fi, Bluetooth, audio, LED, or HDMI nodes. |

Hardware evidence: [stock boot and kernel log](evidence/console-inventory.log),
[stock kernel configuration](evidence/ce990-kernel-config-2026-11-07.txt),
and [full-device backup manifest](backups/touch10-2026-11-07/manifest.json).
The stock kernel uses legacy C board code (`CONFIG_MACH_OMAP4_PERRIER=y`), not
a published Perrier DT. The log shows early LVDS bridge reset/enable, but
its DSI lanes, bridge timing and reset GPIO, touch IRQ/reset, pinmux, regulator
wiring, and exact reserved-memory map still need reconstruction. The stock
log reports a 16 MiB CMA area at `0xae000000` and an SMC workspace at
`0xbfd00000`; validate all load ranges rather than copying Steelhead's map.

## Hardware safety gate before any RAM boot

**Do not run the Nexus Q `APKBUILD`, image builder, or installer against the
Touch 10.** Its package applies the complete Steelhead patch series. A
successful compile or DTB parse is not evidence that the board is safe to
power or boot. The first Perrier candidate needs a manual review of its
*compiled DTB*, final `.config`, inherited `omap4460.dtsi` nodes, and the
kernel's unconditional OMAP4 clock/power initialization and regulator-core
late-disable behavior. A small Perrier DTS overlay alone does not make those
early paths electrically inert.

| Hazard in the Nexus Q tree | Required Perrier exclusion or proof |
| --- | --- |
| [Patch 0014](nexusQ-reloaded/kernel/patches/0014-ARM-OMAP4460-steelhead-tps62361-vdd-mpu-retask.patch) hands VDD_MPU from TWL6030 VCORE1 to TPS62361 and writes PMIC control registers. Its DTS and patches also set CPU/CORE/GPU voltages and OPPs. | Exclude Steelhead power, regulator, ABB, cpufreq, GPU, SmartReflex, and rail-handover code and properties. The stock Perrier log reports TWL6032 writes, but CPU/CORE rail voltages and topology are **not established**; stock config disables `CONFIG_REGULATOR_TPS62360`. Determine them before enabling dynamic scaling. |
| [Steelhead pinmux and GPIO hogs](nexusQ-reloaded/kernel/dts/omap4-steelhead.dts) drive wakeup GPIOs high and assign numerous pads at probe; its USB PHY, Wi-Fi, NFC, and amplifier nodes drive further GPIOs. | No copied board pinmux group, output GPIO, hog, reset polarity, clock assignment, or peripheral power sequence. Map each Perrier signal from stock code/read-only evidence before enabling it. Stock PCF8574 GPIO numbers are legacy dynamic numbers, not DT specifiers. |
| [Steelhead defconfig](nexusQ-reloaded/kernel/configs/steelhead_defconfig) forces `root=/dev/mmcblk0p13 ... rw`, `mem=1008M`, ramoops at `0xbf000000`, HDMI video, and `panic=30`. Its first-boot scripts can rewrite the Nexus Q partition layout. | Build a new minimal config and command line. Omit eMMC driver/mounts, partition scripts, audio, display, radios, remote processors, watchdog servicing, deep idle, and voltage scaling for the first console trial. Review what remains built in and what inherited DT nodes still probe. |
| Steelhead exposes nearly 1 GiB RAM with its own reservation layout. | The stock Touch 10 [`/proc/iomem`](evidence/perrier-live-iomem-2026-11-08.txt) reports separate RAM ranges, beginning with `0x80000000–0x98ffffff` (400 MiB). Consider only that observed low range for the first DT, after checking kernel decompression and U-Boot load ranges. Do not expose holes or overwrite the stock CMA/SMC reservations by copying the Nexus Q memory node. |
| Perrier's DSI/LVDS bridge, eMMC supply, touch controller, and backlight use board-specific reset, rail, and timing paths not recovered from a public DTS. | Leave them disabled in the first image. Enable one at a time only after verifying pinmux, GPIO polarity, supplies, voltage, clock rate, timing, and driver binding on this board. A stock `dummy regulator` message is not proof of a safe voltage. |

Read-only snapshots captured from the running stock firmware on 2026-11-08:
[`/proc/iomem`](evidence/perrier-live-iomem-2026-11-08.txt),
[`/proc/interrupts`](evidence/perrier-live-interrupts-2026-11-08.txt),
[I²C device list](evidence/perrier-live-i2c-devices-2026-11-08.txt),
[LED class](evidence/perrier-live-leds-2026-11-08.txt), and
[eMMC sysfs entries](evidence/perrier-live-emmc-sysfs-2026-11-08.txt).
`/sys/class/regulator` exposed no entries and debugfs pinctrl/regulator
summaries were unavailable without mounting debugfs, so those snapshots do
**not** resolve the rail or pad mapping. No mount or device write was made.

Before the first live test, the review record must list every enabled DT node,
every output pad/GPIO, every assigned clock or regulator/OPP, all built-in
power-management and storage drivers, the exact boot command line and memory
map, and the planned recovery action. Any unmapped output or unverified rail
is a stop condition, even when the image builds successfully.

The stock-to-RAM kexec handoff now has a proven 120-second watchdog recovery.
For the first new Linux kernel, additionally audit its OMAP hwmod/ti-sysc,
watchdog reset and clock initialization/unused-clock shutdown. It must
preserve the inherited timer until its bounded test can return to stock.
Omitting the watchdog driver alone does not prove its parent module/clock
will stay active. See the
[exact qualification](evidence/kexec-watchdog-recovery-2026-11-08.md).

## Staged work and acceptance gates

1. **Reproducible offline baseline.** Download official Linux 6.18.48 source,
   verify it, record SHA-256, compiler and linker versions, and build commands.
   Create a separate Perrier overlay/config so the cloned Steelhead project
   remains a clean reference. Remove the Steelhead forced command line
   (`root=/dev/mmcblk0p13`), board pinmux, voltage/OPP data, and Android
   packaging. Gate: a clean build produces a raw ARM `zImage` and Perrier DTB
   with a manifest of hashes and load ranges.
2. **Minimum Perrier DT and initramfs.** Start with SoC, verified RAM and
   reservations, `chosen/stdout-path` for UART3, and only the dependencies
   needed for a serial console. Embed a tiny initramfs containing `/init` so
   the first boot needs no external root filesystem or storage driver. Keep
   SMP, display, network, storage, watchdog, and dynamic voltage scaling out
   of the first test. Gate: `dtc` validation, inspected final `.config` and
   *compiled* DTB, an audit of inherited SoC nodes and unconditional early
   OMAP4 init, and no Steelhead compatible strings, active unknown output
   pads, or hard-coded root partition in the artifacts.
3. **New-kernel/FDT handoff through the qualified RAM runner.** Key SSH
   uploads into tmpfs and kexec entry into a reviewed UART/stall payload
   have passed; the watchdog restored factory firmware automatically.
   Use that path for the first new kernel after the safety/clock audit.
   Confirm its compressed/decompressed ranges, initramfs, and FDT cannot
   overlap each other or reserved memory. The DTB handoff and initramfs have
   passed. Remaining gate: an interactive serial shell in RAM and
   automatic return to stock with a new boot ID and unchanged environment.
   U-Boot `bootz`, serial transfer and TFTP remain alternatives requiring
   separate setup; they are no longer prerequisites for routine testing.
4. **Read-only devices.** Enable eMMC, I²C/PMIC, and SMSC95xx USB Ethernet one
   at a time. Compare probed devices, regulators, clocks, and errors with the
   stock log. Do not mount the stock ext4 read-write; a diagnostic mount, if
   needed, should use read-only/no-journal-replay settings. Gate: the same
   RAM image boots repeatedly, sees eMMC read-only, and has working serial
   plus a second access path before display work.
5. **Display and touch.** Inspect the *6.18.48* OMAP DRM, DSI, TC358765,
   panel, backlight, and CYTTSP4 bindings/drivers. Add only properties those
   drivers actually consume. Recover pinmux, GPIO polarity, DSI lane count,
   panel timing, power sequence, and touch transform from stock evidence.
   Gate: visible asymmetric test image and validated touch coordinates at
   center/corners, with serial recovery still available.
6. **Rootfs and persistent boot, later.** Once RAM boots are reliable, package
   a Perrier-specific rootfs (a small postmarketOS device/kernel package is a
   possible route). Stage new kernel/DTB under new filenames, with factory
   files intact. Assess p12 only after confirming its partition, eMMC driver,
   and actual recovery behavior. A one-shot U-Boot selection must restore the
   factory `bootcmd` *before* starting the trial. Persistent eMMC boot and any
   p8/p12/p14 write need their own reviewed plan and scope authorization; the
   current backups do not constitute a tested automatic fallback.

## First implementation deliverable

The minimal Perrier DTB, kernel config, embedded initramfs, build manifest,
and RAM-only kexec trial now pass. A normal software reboot also returns from
the new kernel to stock after 15 seconds of diagnostics, while the watchdog
remains armed. The next device gate is a carefully scoped read-only probe of
eMMC or SMSC95xx USB Ethernet, starting from stock board wiring evidence.
