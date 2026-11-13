# OMAP4460 mainline bus migration

The ram66 board description uses the existing nodes from `omap4460.dtsi`,
`omap4.dtsi` and `omap4-l4.dtsi`. The former root-level copies of the UART,
GPIO, I2C, DMA, MMC, USB, display, keypad, timer, watchdog, bandgap and
pinctrl nodes have been removed. Board overrides describe wiring and actual
board devices. RAM-only restrictions stay in `omap4-cisco-perrier-ram.dts`.

## Mapping

| Function | Existing mainline node |
| --- | --- |
| Service UART | `uart3` under L4 PER |
| Touch and bridge/board sensor | `i2c2` and `i2c3` under L4 PER |
| GPIO banks | `gpio3`, `gpio4`, `gpio5`, `gpio6` under L4 PER |
| eMMC and DMA | `mmc2` under L4 PER; `sdma` under L4 CFG |
| USB Ethernet | `usbhshost` and `usbhsehci` under L4 CFG |
| LCD | `dss`, DISPC and `dsi1` under the OCP DSS target |
| Backlight timer | `timer10` under L4 PER |
| Front keypad | `keypad` under L4 WKUP |
| Recovery watchdog | `wdt2` under L4 WKUP |
| Pinmux | `omap4_pmx_core` under L4 CFG |
| CPU thermal sensor | OMAP4460's existing `bandgap` node |

The exact path mapping and allowed 24-target set are recorded in
[configs/bus-layout.json](configs/bus-layout.json). The physical GPIO bank
and offset determine the wire; Linux's dynamically assigned gpiochip number
can change when the bus probe order changes.

## Preserved board behavior

`audit_bus.py` translates each bus-relative `reg` through its `ranges` and
resolves phandles before comparison. It compared 72 physical register ranges
and 406 existing properties with ram65, including GPIO offsets/polarities,
pad mux values, fixed supplies, PWM, IRQs, panel timing, clocks and DMA.
The keypad target now uses the upstream `ti,sysc-omap2` description rather
than the old copied `ti,sysc-omap4` compatible; its register addresses and
keymap are unchanged.

UART interrupts now use upstream `interrupts-extended` through WUGEN. The
auditor follows WUGEN's parent and checks the same GIC interrupt specifier.
Peripheral IRQs, aliases and I2C bus numbers retain their intended meaning.

The RAM DT disables 66 unused target/bus branches and unused siblings of
shared control/display/USB modules. GPIO banks retain `ti,no-reset-on-init`.
WDT2 retains no-reset/no-idle-on-init; the running system timer keeps the
upstream no-reset/no-idle protection. Newly populated pinctrl/control/clock
infrastructure is also protected against initialization resets.

The RAM policy removes runtime `power-domains` links from OCP, the three L4
buses and the outer DSS target while retaining their upstream hierarchy,
clocks and address translations. This preserves the earlier power policy
for this layout-only step. PMIC control, ABB, CPU operating points and CPU1
remain disabled. Runtime domain integration, production suspend and rail
power-down are separate work.

## Verification

The normal Kbuild target `ti/omap/omap4-cisco-perrier-ram.dtb` produced a
byte-identical DTB to the image used in the live trial. The builder now uses
that target directly. All five exported patches pass checkpatch, and the
Gen4 binding and actual touch node pass DT schema validation. Captured-data
and I2C transport tests pass under ASan/UBSan. `tests/test_bus_audit.py`
accepts the real migrated DT and rejects ten changed GPIO, pad, voltage,
timing, IRQ, watchdog and enabled-target cases.

The owner confirmed the visible/aligned Qt screen, touch tracking and
brightness in ram66. Live logs show native touch, keypad, thermal, Ethernet,
read-only eMMC and the feeding mainline watchdog. Qt close/reopen resumed
native touch on the same boot. Final watchdog return and exact factory p8
verification are recorded in [validation-ram66.json](validation-ram66.json).
The full live record is
[ram66 run](../runs/20261110T120143Z-uboot-ram66-25e9df/result.json).

The timer1 target's `-EBUSY` probe result is intentional: `ti-sysc` refuses
to take ownership of a system timer tagged no-reset/no-idle. Clockevent IRQs
continue to advance. The SRAM-pool/erratum-I688 warning also occurs in the
ram65 baseline and is outside this migration; no SRAM workaround was added.

Ram65 remains unchanged in `development/perrier-ramenv/mainline-ram`;
its source, configuration, patch and tool snapshot is in
[baselines/ram65](baselines/ram65/). The earlier physically confirmed ram64
image remains available as the `gen4-touch` profile.
