# Perrier Ethernet initialization from U-Boot

Ram60 adds DT-managed Ethernet startup to the ram59 image. The first ram59
U-Boot attempt reached Linux and its watchdog but had no USB LAN device:
stock Linux had previously supplied the external PHY clock, reset levels,
and pad muxing across kexec. The unrenewed host lease returned it to stock
with the exact factory p8 hash restored.

## Hardware evidence and implementation

The [stock readback](../../evidence/perrier-stock-coldinit-gpio-clock-2026-11-10.txt)
and saved CE9.9.0 `perrier_init` at `0xc07226b4` agree on:

| Signal | Stock setting | Ram60 owner |
| --- | --- | --- |
| USB PHY reference | `auxclk1_ck`, 19.2 MHz from fixed 38.4 MHz `sys_clkin_ck` | Mainline `usb-nop-xceiv` clock consumer |
| External PHY reset | GPIO110, physical high when released; core pad `0x0f6=0x0003` | Mainline generic PHY, active-low reset |
| LAN reset | GPIO158, physical high; pad `0x162=0x0003` | GPIO hog on the existing GPIO5 controller |
| Reference clock output | Core pad `0x19a=0x0118` | Mainline `pinctrl-single` |
| ULPI port 1 | Stock values at core offsets `0x0c2` through `0x0d8` | Mainline `pinctrl-single` |

The DT changes request only these 15 pads and two reset outputs. The fixed
clock parent avoids retuning a shared PLL. No regulator or supply property is
added. The GPIO5 target preserves its other stock output latches. Touch and
LCD power sequencing are unchanged and are still separate cold-start work.
No mainline USB, pinctrl, GPIO, or clock driver source is modified.

## Verified RAM behavior

The [ram60 kexec test](../runs/20261110T094711Z-interactive-c8d1fe/result.json)
passed on 2026-11-10. The PHY reset re-enumerated USB `0424:9e00` at 480 Mb/s,
the LAN established a 100 Mb/s full-duplex link, and root SSH worked. The
[read-only runtime capture](../runs/20261110T094711Z-interactive-c8d1fe/ethernet-live-check.log)
confirmed both reset lines high, all 15 selected pad values, 19.2 MHz PHY
clock, 38.4 MHz parent, and the unchanged watchdog feeder. Stock returned
automatically with the original p8 hash. The checked evidence is summarized
in `development/perrier-ramenv/cold-ethernet/kexec-validation.json`.

This was a one-time check of the new electrical description. Routine kernel
testing will use the audited one-shot U-Boot path directly, as requested by
the owner; kexec is not a prerequisite for each future image. Qt and other
userspace changes continue live over RAM SSH.

## Build and U-Boot workflow

```sh
python3 development/perrier-cold-ethernet/build_image.py
python3 development/perrier-cold-ethernet/audit_image.py
python3 tools/touch10_uboot.py prepare
python3 tools/touch10_uboot.py session --minutes 30
```

`prepare` is offline. `session` stages two new files on p14, writes and reads
back the one-shot p8 candidate, requests one software reset through U-Boot,
and checks RAM SSH, read-only eMMC, the already-restored factory environment,
Qt startup, and stock return. The mainline watchdog and host lease are the
same as ram59. Very early kernel execution before watchdog probe can still
need manual power recovery. `cold-ethernet` is now the runner's default profile.

## Verified U-Boot behavior

The [ram60 U-Boot run](../runs/20261110T095300Z-uboot-ram60-fd525f/result.json)
passed on 2026-11-10 after a software reset through MLO/U-Boot. The complete
image booted, USB Ethernet enumerated, and root SSH was available. U-Boot had
already restored p8 byte for byte when RAM userspace read it. The eMMC was
read-only and no eMMC filesystem was mounted. The
[runtime capture](../runs/20261110T095300Z-uboot-ram60-fd525f/ethernet-live-check.log)
records the PHY clock, reset levels, selected pin values, and working link.

After more than 120 seconds of healthy operation the host deliberately
stopped watchdog feeding. Hardware reset the panel, and stock SSH/Phoenix
returned 151.6 seconds later with the exact original p8 hash. The proof is
also stored under `development/perrier-ramenv/cold-ethernet/uboot/watchdog-proof.json`.
No manual power cycle or password was needed for this run. A full physical
power-removal test remains separate from this software-reset U-Boot proof.

The remaining cold-start limitations are explicit: the Cypress touch driver
returns I2C `-121`, its board power/reset setup is still missing from this DT, and
the Qt test exits when no touch event device exists. Thermal readings,
framebuffer creation, backlight registration, and keypad registration are
present, but this run does not physically validate LCD visibility, keypad
pinmux, or touch. These are the next board-support changes; Ethernet and the
development/recovery route are now established.

Follow-up: the [restored Gen4 port](../perrier-gen4/README.md) adds the stock
touch power/reset sequence and older loader protocol. Ram62 initialized
the touchscreen and Qt from U-Boot. The separate ram63 candidate adds the
missing backlight 5 V and PWM pad state found during physical validation.
This ram60 image remains the preserved Ethernet-only cold-start baseline.
