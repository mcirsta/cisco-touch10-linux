# Perrier front keypad RAM trial

Ram52 extends the tested ram51 display, native touch, and timer10 backlight
image with the mainline OMAP4 matrix keypad driver. It remains a RAM-only
kexec trial with the host lease, WDT2 automatic stock recovery, and read-only
eMMC policy.

Stock Linux 3.4 registers `omap4-keypad` at `0x4a31c000`, IRQ 152 in
`/proc/interrupts` (GIC SPI 120), and exposes only key codes 113, 114, and
115. The saved CE9.9.0 kernel's `perrier_keymap` at `0xc04ccc08` has three
32-bit entries:

| Row | Column | Linux key |
| --- | --- | --- |
| 0 | 4 | `KEY_VOLUMEDOWN` (114) |
| 1 | 4 | `KEY_MUTE` (113) |
| 1 | 5 | `KEY_VOLUMEUP` (115) |

Its platform data at `0xc07adda4` contains the two-row, six-column matrix
dimensions. A nearby four-entry keymap belongs to another board; its HOME
code is absent from the Touch 10 stock input capabilities. The separate
factory-reset input uses GPIO138 and is intentionally outside this trial.
Stock advertises `EV_REP` for held buttons, so the DT leaves the mainline
driver's default autorepeat enabled.

The new DT node uses the upstream OMAP4 keypad controller address, clock,
register layout, and interrupt. It adds the exact three-key matrix. No
pinmux, GPIO, regulator, or voltage property is changed. Like the earlier
trials, the inherited state after kexec is not proof of cold-boot setup.
The [stock pad snapshot](../../evidence/perrier-stock-keypad-pads-2026-11-09.txt)
locates this board's alternate matrix route: columns 4 and 5 at CORE pad
offsets `0x184` and `0x186`, rows 0 and 1 at `0x188` and `0x18a`, all mode 1.
The commonly used row pads `0x050` and `0x052` are instead in GPIO mode on
Perrier. A later cold-boot DTS can use the captured raw pin settings after
the pinctrl parent and surrounding board boot sequence are reviewed.

Build and audit:

```sh
python3 development/perrier-ramenv/build_image.py --profile native-keypad
python3 development/perrier-keypad/audit_image.py
python3 tools/touch10_ram.py session --profile native-keypad --minutes 6
```

The [audit](audit_image.py) compares ram52's FDT and kernel configuration
against the tested ram51 image and rejects unrelated changes.

The first RAM run registered the keypad with exactly the stock three-key
capability mask. The physical buttons produced press and release events:
mute 113, volume up 115, and volume down 114. It returned to stock with the
U-Boot environment hash unchanged. That first image inadvertently disabled
autorepeat; the final DT above restores it. The second RAM run reported the
same `EV=100013` (including `EV_REP`) and `KEY=e0000 0 0 0` masks as stock,
while the native touch, DRM connector, backlight, and Ethernet remained
present. Both runs returned to stock with the U-Boot environment hash
unchanged. See the [event record](../../evidence/perrier-ram52-keypad-events-2026-11-09.txt),
[first run](../../development/runs/20261109T184307Z-interactive-cd6d43/result.json),
and [final run](../../development/runs/20261109T184658Z-interactive-a977af/result.json).

Cold-boot keypad pinmux remains untested.

The [Qt RAM test screen](../perrier-qt/README.md) now shows a simulated volume
slider and mute state driven by this keypad. It leaves the ALSA mixer and
audio hardware untouched. The [physical hold test](../../evidence/perrier-ram52-volume-mute-test-2026-11-09.md)
confirmed volume auto-repeat and one mute toggle per press despite repeat
events during a hold.
