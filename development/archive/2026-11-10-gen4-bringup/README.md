# Archived Gen4 bring-up

The active driver, board DTS and build workflow are now in
[development/kernel](../../kernel/README.md). This directory preserves the
original upstream references, first-port generator, failed ram61–63 trials,
and the confirmed ram64 sources. These scripts are historical records;
use the active workspace for future changes. The old `perrier-gen4` path
is a compatibility symlink so immutable image manifests still resolve.

# Perrier restored Cypress Gen4 driver

This ports the Cypress CYTTSP4 core last present in Linux v6.10 to the
Touch 10's Linux 6.18.48 development kernel. The separate
`development/perrier-touch` operational-handoff driver and ram60 Ethernet
image are preserved. The new image lives in
`development/perrier-ramenv/gen4-touch`; its isolated kernel source is
`linux-source/`. The original shared Linux tree has not been overwritten.

## Source and scope

`reference/` contains the archived upstream core, header, I2C adapter and
matching platform-data/I2C-common sources, with official source URLs and
SHA-256 manifests. Gen4 means the touchscreen protocol generation, not a
Linux 4.x kernel requirement. The driver was removed in v6.11 after being
unused in-tree and retaining platform-data-only board integration; see the
[maintainer's removal explanation](https://lkml.iu.edu/hypermail/linux/kernel/2408.0/03439.html).

The restored core retains upstream startup/mode-change handling, threaded
interrupts, descriptor-based decoding, controller watchdog, recovery work,
and sleep/resume structure. The port replaces platform callbacks and the
axis framework with GPIO descriptors, regulators, the DT interrupt and
`touchscreen_parse_properties()` / `touchscreen_report_pos()`. The I2C
adapter uses the modern probe/remove APIs and reserves both device
addresses. The match is deliberately limited to `cisco,perrier-cyttsp4`:
other Gen4 controllers have different loader framing and descriptors.

## Stock hardware and protocol evidence

The exact CE9.9.0 kernel is
`development/stock-kernel/ce990-Image.bin`; its kallsyms list is
`evidence/ce990-kallsyms-2026-11-08.txt`. IDA analysis and live readback
establish:

| Item | Exact evidence / behavior |
| --- | --- |
| Touch supplies | `perrier_init` at `0xc07226b4`: GPIO120 `tp_5v_en` high, then GPIO121 `tp_3v3_en` high |
| Reset/IRQ setup | `idefix_touch_init` at `0xc0722590`: GPIO141 output high, GPIO142 input with pull-up/off-wake mux flags |
| Reset pulse | `cyttsp4_hw_reset` at `0xc0032618`: physical high 20 ms, low 40 ms, high 20 ms |
| Application address | I2C board-info at `0xc07ae618`: `0x67` |
| Loader address | Platform data at `0xc07ae640 + 0x409`: `0x69` |
| Loader transport | `_cyttsp4_send_cmd` `0xc02eecdc`, write helper `0xc02ee534`, I2C write `0xc02f2478`: no register/subaddress prefix |
| Existing-app launch | `_cyttsp4_ldr_exit` `0xc02effbc`: `01 3b 00 00 4f 6d 17`; CRC checked offline |
| Descriptor | Captured firmware 1.1, product 1, 1280×800, ten contacts, seven-byte records; 23-byte base opcfg |

The live stock mux/GPIO inventory is
[`perrier-stock-touch-power-mux-2026-11-10.txt`](../../../evidence/perrier-stock-touch-power-mux-2026-11-10.txt).
Only writable IRQ pad bits `0x731b` are set: the observed `0xf31b` also
contains the wake-event status bit. The I2C pads are stock `0x0100`.

The later upstream Gen4 driver's `00 ff ...` loader framing does not apply
to this unit. Its assumptions about extended nine-byte descriptors also
cannot be applied to this older seven-byte layout. The Perrier profile
uses the measured addresses, raw seven-byte launch, base descriptor and
the stock ten-second system-information startup allowance. It launches
the controller's existing application; it contains no touch firmware
flash/update path.

`cyttsp4_hw_recov` at `0xc0032684` supports reset and also a legacy wake
method which temporarily drives IRQ142 low. An I2C read did not wake this
unit in ram61. Resume now uses the verified reset/application-launch path
while keeping IRQ142 configured as an input. This costs about two seconds
and avoids changing IRQ direction. Both supplies remain on during the
controller's deep sleep. Full board suspend-to-RAM is outside this test.

## Memory and input handling

The port checks system-information offsets and minimum block sizes before
allocating/reading, zero-extends the old base opcfg, and validates field
offsets/bit widths. Touch count is checked **before** the I2C read into the
contact buffer. Duplicate IDs, unsupported object types, and out-of-range
positions are rejected before publishing a frame. Transfer lengths are
16-bit so a 256-byte map cannot silently truncate to zero.

Input slots and standard DT transforms replace the old platform axis
array. Perrier has no inversion, swapping or scene-offset workaround.
Its physical keys remain on the existing mainline OMAP keypad driver.
The timer API is updated for 6.18; ordinary controller-watchdog pauses use
reusable timer deletion, and removal stops IRQ/work before freeing input
and transfer buffers.

`test_core.py` extracts the actual ported descriptor/axis/report functions,
replays 20 captured reports and compares their contacts with the proven
handoff decoder under ASan/UBSan. It also tests ten contacts, pre-read count
bounds and 5,888 descriptor mutations. `test_i2c.py` tests the actual adapter
functions' addresses, framing, exact launch CRC, short/error transfers and
bounds under the same sanitizers. These do not replace a physical tap test.

## U-Boot trials

Ram61 initialized the controller from U-Boot, enumerated native input, and
started Qt. Its one-second startup deadline caused retries and the I2C
wake path timed out. Hardware-watchdog expiry restored stock in 155.8
seconds, with the exact factory p8 hash. See the
[run](../../runs/20261110T102438Z-uboot-ram61-d21d89/result.json).

Ram62 fixed the startup allowance and reset-based resume. Both completed
without driver errors, and Qt opened `/dev/input/event1` at 1280×800.
The original runner sampled readiness after only two seconds, before the
resume finished; the later
[Qt/GPIO/DRM capture](../../runs/20261110T103103Z-uboot-ram62-d9ad83/gen4-first-check.log)
confirms readiness. The runner now polls the actual EVDEV_READY marker
for up to 15 seconds. The owner reported a black screen, and the
[GPIO readback](../../runs/20261110T103103Z-uboot-ram62-d9ad83/gpio-output-readback.log)
showed touch rails/reset high but GPIO157 LCD/backlight 5 V low. A normal
software return to stock passed. Images/sources for both trials are saved
under `baselines/`.

Ram63 adds the missing LCD/backlight supply and PWM pinmux. Stock
`idefix_backlight_set_power` at `0xc0032330` drives GPIO157 high and makes
eleven 1 ms waits before PWM programming. The delay follows the exact
`CONFIG_HZ=128` stock build and the
[Linux 3.4 ARM delay conversion](https://raw.githubusercontent.com/torvalds/linux/v3.4/arch/arm/include/asm/delay.h).
The stock pin capture identifies GPIO157 at pad `0x160`, mode 3, and
timer10 output at `dpm_emu18`, pad `0x1d2`, mode 1.

The new DT uses an ordinary fixed regulator on GPIO157 with an 11 ms
startup delay, connected to the existing PWM backlight. It holds this
rail on during bring-up, establishing supply-before-PWM order without
forking either mainline driver. PWM still controls brightness/blanking;
switching the 5 V rail off with blanking remains future power-management
work. The owner still saw black in ram63 despite the correct power/PWM
readback. DSI, DISPC, the bridge and clock registers matched the visible
ram50 run. The difference was traced further before another screen request.

The fresh stock inventory exposed a wrong address in the historical pad
inspector: MCSPI4_CLK/GPIO151 is `0x154`, stock GPIO mode 3; `0x156` is
MCSPI4_SIMO. Stock left GPIO151 as input with a high output latch, while
ram63 inherited it as an output driven low. Cisco's backlight callback sets
that latch high on power-on and low on power-off. Ram64 models the correct
pad and active-high GPIO151 through the existing backlight driver's
`enable-gpios`, which is asserted after PWM programming. See the
[erratum](../../../evidence/perrier-backlight-pad-erratum-2026-11-10.md) and
[fresh GPIO/pad capture](../../../evidence/perrier-stock-backlight-enable-corrected-2026-11-10.txt).

A speculative DSI regulator change was ruled out: stock also uses a dummy
DSI supply, and the exact PMIC is TWL6032. No PMIC driver/voltage change
or shared PLL setting was added. `CONTROL_DSIPHY` already matched the
stock board initializer through mainline's existing syscon handling.

The ram64 preflight also rejected a one-byte mismatch between a packed Qt
library and its source before any device staging. Two independent repacks
agreed; the cause was not established. The builder now verifies each
payload against the baseline, validates the complete archive before
compilation, checks that compilation leaves it intact, and verifies that
the embedded compressed initramfs exactly matches. The corrected image
passes both protocol sanitizer suites and the image audit.

## Build, audit and run

```sh
python3 development/perrier-gen4/port_core.py
python3 development/perrier-gen4/build_image.py
python3 development/perrier-gen4/audit_image.py
python3 tools/touch10_uboot.py prepare --profile gen4-touch
python3 tools/touch10_uboot.py session --profile gen4-touch --minutes 30
```

The builder synchronizes the three canonical driver files into the isolated
source tree. It refuses to overwrite unrecorded edits made directly there.
The built-in composite is `cyttsp4_core + cyttsp4_i2c`; the previous small
`cyttsp4.c` is absent from this isolated tree.

The DT audit permits only the listed touch/backlight pads, supplies and
reset properties relative to ram60. Kernel configuration changes are the
image version and initramfs path; the rootfs differs only in its version
markers. eMMC stays read-only in the RAM kernel. The standard watchdog
feeder and its expiry proof are unchanged. U-Boot restores the factory
environment before loading the kernel. No kexec step, power cycle or
password is needed for this software-reset test.

Qt-only updates continue over the live RAM SSH connection. The runner
maintains the watchdog lease; `python3 tools/touch10_ram.py recover` requests
stock return, and `recover --hardware` verifies expiry. Keep the host
runner alive while using the RAM environment.
