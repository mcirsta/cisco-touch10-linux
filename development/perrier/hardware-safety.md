# Perrier hardware bring-up guardrails

Evidence collected from the running CE9.9.0 kernel and offline analysis of
`development/stock-kernel/ce990-Image.bin` in IDA. Names inferred from
decompilation are provisional until matched to the board's actual electrical
connections. Do not copy a GPIO polarity or regulator setting solely from a
name.

## Already exercised by the RAM kernel

| Circuit | Evidence | Current behavior |
| --- | --- | --- |
| OMAP UART3 | Stock console at `0x48020000` | Serial output; no pinmux change |
| USB host and SMSC95xx LAN | Stock USB `0424:9e00`, factory MAC `24:16:9d:b6:77:bb` | Driver and 100 Mb/s link tested after kexec; factory GPIO and PHY clock state inherited |
| MMC2 eMMC | Stock `omap_hsmmc.1`, MMIO `0x480b4000`, CID `11010030303447413002265429a4c587` | Fixed 2.95 V *description* with no control GPIO; all block areas forced read-only; p14 mounted `ro,noload` |
| WDT2 | Counter advances at `0x4a314028` | Armed by stock before kexec; new kernel does not open or feed it; automatic recovery tested |
| OMAP4460 CPU1 | Stock reports CPU0 and CPU1 online | SMP RAM trials ram53-56 did not complete boot; ram57 retained the proven single-core configuration and booted. See [SMP investigation](../perrier-smp/README.md). |
| OMAP I2C2 | Stock `omap_i2c.2` at `0x48072000` | Adapter registration passed in ram09; no child device or I2C messages |
| OMAP I2C3 | Stock `omap_i2c.3` at `0x48060000`, bridge client `3-000f` | Adapter registration passed in ram10; no child device or I2C messages |

The stock MMC2 controller is runtime suspended when idle. A direct read of its
MMIO registers caused a bus fault in a temporary helper, after which the
factory kernel remained healthy. Do not repeat direct peripheral MMIO reads
without first establishing a safe clock/runtime-power context.

## Display and touch

| Circuit | Stock observation | Board code evidence | Constraint before enabling |
| --- | --- | --- | --- |
| Panel | DRM `LVDS-1`, connected, `1280x800`, framebuffer 32 bpp; stock OMAP display sysfs reports `71078,1280/78/79/3,800/12/10/1`; `display0` is attached to `omapdss_dsi.0` and enabled | The saved kernel's `omap_video_timings` at `0xc07adbf4` matches the stock sysfs tuple | Ram36 displayed a visible 1280×800 pattern through mainline `panel-lvds`; cold boot remains untested |
| Bridge | `tc358765_i2c_driver` at I2C3 address `0x0f` | Stock driver path `panel-tc358765.c`; mainline reads chip ID `0x65` and matches stock VPCTRL/LVCFG/LVPHY0 | Physical supplies are inherited; cold boot untested |
| Display rails | Stock strings `lcd_3_3v_enable` and `lcd_5v_enable` | Stock holds GPIO163 and GPIO157 high while the UI is lit; ram35 left GPIO163 low, and ram36 restored it high through `regulator-fixed` | GPIO163 is proven for the RAM display; GPIO157 remains inherited; cold-boot sequencing and physical voltages are unverified |
| Display reset | Stock string `lcd_reset_gpio`; running stock GPIO102 is high | Mainline bridge controls GPIO102 as active-low reset during the RAM modeset; GPIO151's stock callback writes its latch, but the active stock pad is in safe mode 7 and GPIO direction is input | Do not add GPIO151 control to the RAM image; its physical role during transitions remains unproven |
| Backlight | LED `lcd_backlight` at 255/255; stock timer10 runs at 20 kHz | Stock pad readback routes timer10 PWM through `dpm_emu18` mode 1; ram51 mainline PWM/backlight changed duty on all four slider levels while GPIO157 stayed high | Native timer10 control is validated for kexec; GPIO157 5 V sequencing and cold-boot pinctrl remain open |
| Touch controller | `cyttsp4-i2c` at I2C2 address `0x67`, input event1; factory driver `Rev4-2M-28` dated 2012-03-09 | Ram50 native Gen4 input driver reads the 1280×800, ten-contact descriptor and reports type-B slots through GPIO142 IRQ | Direct touch alignment is validated in RAM; reset and power GPIO141/120/121 are still inherited for cold start |
| Touch rails | Stock strings `tp_5v_en`, `tp_3v3_en` | `perrier_init` at `0xc07226b4` manipulates GPIO 120 and 121 | Verify power order and voltage; keep both absent from the RAM DT |
| Front buttons | Stock `omap4-keypad` at `0x4a31c000` with volume down, mute, and volume up | Ram52 mainline OMAP4 keypad reports the same key and event capability masks; physical press, release, and held repeat events were captured. Stock alternate pad route is CORE offsets `0x184/0x186` columns and `0x188/0x18a` rows, mode 1 | Keypad pad mux remains inherited from stock; cold boot untested |
| Factory reset button | Stock GPIO138 and separate `factoryreset` input | Deliberately absent from the RAM image | Keep recovery control separate from the three-button keypad |
| PMIC | `twl6032` on I2C1 at `0x48`; stock boot log programs VCORE1/2/3 and VMEM | Factory board initialization | No generic PMIC or voltage-scaling policy in the RAM image |
| I2C4 expander | `pcf8574` at `0x24`, GPIO chip base 256, 8 pins | Stock device inventory | Map each output before adding a driver or GPIO consumer |
| Audio | ALSA card `idefix`; TWL6040 at I2C1 `0x4b` | Factory device inventory | Map codec clocks, rails, speaker amplifier and mute GPIO before playback |

The Linux 6.18 tree contains a TC358765-compatible variant in
`drivers/gpu/drm/bridge/tc358775.c` and an OMAP4 DSI host driver. The
`toshiba,tc358775.yaml` binding requires explicit 1.2 V `vdd`, 1.8 V `vddio`,
reset GPIO, and DSI input/output graph. The driver enables those supplies and
toggles reset during bridge startup. Stock sysfs lists `display0` under
`omapdss_dsi.0`; the second DSI controller has no attached display. The saved
bridge platform-data block at `0xc07adce8` starts with a value of four that
the stock driver uses in lane setup. Factory regulator sysfs exposes only
dummy, LDOUSB, VANA, CLK32KAUDIO, SYSEN, REGEN1, and CLK32KG names, so the
bridge supplies cannot yet be mapped from that interface. Subsequent register
and disassembly evidence established the stock
`DSI_COMPLEXIO_CFG1=0x2a054321` lane mapping and VESA 24-bit bridge mapping.
The native ram23 image registered a connected `LVDS-1`; ram24 read the bridge
ID and completed a guarded KMS modeset. Ram31 matches the stock video-channel
register and has an empty transmit FIFO throughout its pattern window. See
[perrier-native/README.md](../perrier-native/README.md). The 1.2 V and 1.8 V
bridge regulator declarations are logical only, with no control GPIO. Ram36
uses a fixed regulator to restore GPIO163 to the stock-high LCD 3.3 V enable
level; timer10 PWM and GPIO157 are still inherited. No cold-boot power
sequence has been validated.
The saved factory boot log prints `Reset and enable LVDS bridge` at 0.213 s;
later, at 2.527 s, DSI0 reports that `vdds_dsi` and `panel_supply` are absent
and substitutes dummy regulators. Kallsyms identifies the calls in the
board helper at `0xc072196c` as `gpio_direction_output` and
`__gpio_set_value`: it sets GPIO 163 and 157 as outputs with value zero,
toggles GPIO 102 through zero, one, zero, sets GPIO 151 to zero, and then
registers the I2C3 bridge information. These are software-visible levels,
not verified electrical rail voltages or complete power sequencing.
The kernel's generic CYTTSP driver describes Txx3xx parts, while CYTTSP5 is
for Generation 5. Neither establishes compatibility with this stock
`cyttsp4` unit; that requires a separate protocol and binding review. The
archived GPL [Cypress Gen4 source](../reference/cyttsp4-android-common-4a2c9b037a08/README.md)
provides a protocol reference, but its symbols differ from the installed
`Rev4-2M-28` driver, so it is not a drop-in board driver. The ram11 read
selected register zero and returned `80006603000000000302000000000000`.
That confirms I2C communication only; no GPIO, regulator, reset, firmware
update, or touch-event operation was performed. After factory recovery,
the driver remained `ACTIVE`, its reported firmware identity was unchanged,
and `display0` remained enabled.

The factory timing tuple has been cross-checked against the
[Linux 3.4 `omap_video_timings` layout](https://github.com/torvalds/linux/blob/v3.4/include/video/omapdss.h):
pixel clock 71.078 MHz; active 1280 × 800; horizontal sync/front/back
3/78/79 pixels; vertical sync/front/back 1/12/10 lines. The totals are
1440 × 823, approximately 59.98 Hz. This identifies the panel mode but says
nothing about safe supply or reset behavior.

The ram13 `simplefb` handoff maps the three contiguous TILER aliases already
allocated by stock Phoenix. It programs no display register or supply. The
bounded pixel marker was written and restored with matching CPU readback in
each buffer, and the stock display remained enabled after recovery. A later
observed repeat showed no visible marker. The temporary-kernel screen was
black during a later ram18 trial; the normal stock UI returned afterward.
The ram18 RAM trial read `DISPC_CONTROL=0x308` with LCD manager bit 0
clear, versus stock `0x309`; `LINE_STATUS` did not advance over 10 ms. Thus
the simple framebuffer mapping does not provide live scanout after this kexec
path. It is not a cold-boot display path. The mainline OMAP DRM, DSI,
TC358765 bridge, and panel drivers have since been enabled in the isolated
native candidate. Ram31 and ram33 remained black despite stock-matching
video registers. Read-only GPIO capture then found GPIO163 low during the
temporary kernel, versus high in stock. Ram36 restored that output with a
fixed regulator and displayed a visible color pattern in two runs. Both
runs returned to stock with the U-Boot environment hash unchanged. No
permanent boot configuration changed.

## Next validation sequence

1. Extract timing, GPIO polarity, rail ordering, and DSI lane configuration
   from the saved stock kernel and passive factory sysfs/boot logs.
2. Review the exact mainline drivers and DT bindings against that evidence.
3. Add one circuit at a time to a RAM-only image. Keep the watchdog and
   automatic stock return, and never enable an unmapped rail or GPIO.
4. Only after independent display, touch, and audio proofs should the stock
   userland be tried under the new kernel. Its writable configuration volumes
   need a separate backup and rollback design first.

The saved CE9.9.0 initramfs contains an `/init` link to SysV init. Its
`/etc/rc.sysinit` runs `/etc/early.d/S10basemount` and `S14loopmount`.
`S10basemount` invokes `fsck -y`, mounts the base volume without a read-only
option, and clears its upgrade temporary directory. `S14loopmount` can remove
files from `lost+found`. Therefore the stock initramfs must not be substituted
directly into a RAM trial whose storage safety depends on read-only access.
