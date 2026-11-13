# Touch 10 kernel development

This is the active Linux 6.18.48 board-support workspace. The current
`display-pll-only` ram69 profile keeps the mainline OMAP4460 bus layout and
removes the board-specific PLL N>=38 floor. The normal clock search selects
N=19/M=211 with the same output rates. The owner confirmed a clean aligned
display, native touch and brightness after blank/unblank and Qt restart.
Hardware watchdog recovery returned to stock in 152.7 seconds with the
exact factory environment restored. See
[validation-ram69.json](validation-ram69.json).

Ram66 remains the `mainline-bus` fallback, with its sources in
`baselines/ram66` and [bus migration record](bus-migration.md). The ram67 and
ram68 DISPC-removal trials showed a red column after display cycling and
were not promoted. Ram69 retains ram66's DISPC sync policy. See
[the controlled comparison](display-reduction.md).

The ram65 image is preserved as `mainline-ram`, with its source/patch/tool
snapshot in `baselines/ram65`. The earlier ram64 image remains available as
`gen4-touch`; its physical confirmation is in
[working-baseline.json](working-baseline.json).

## Layout

| Path | Purpose |
| --- | --- |
| `source/drivers/input/touchscreen/` | Restored Cypress Gen4 core and I2C transport; edit these normal kernel files directly |
| `source/Documentation/devicetree/bindings/` | DT binding with supplies, reset, IRQ and standard touchscreen properties |
| `source/arch/arm/boot/dts/ti/omap/omap4-cisco-perrier.dtsi` | Consolidated hardware wiring, regulators, pinctrl and peripheral nodes |
| `source/arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dts` | RAM memory/CPU/power policy and disabled unused peripherals |
| `source/drivers/gpu/drm/` | Explicit Perrier display changes to existing mainline drivers |
| `patches/series` | Ordered, reproducible patches against the pristine kernel archive |
| `patches/ram-only/` | Experimental clock/PMIC-initialization and eMMC read-only safeguards, separate from driver support |
| `configs/perrier-ram.config` | Reproducible development kernel configuration; the builder fills in the initramfs path |
| `tests/` | Captured-data and I2C transport sanitizer tests; generated files stay in `tests/out/` |
| `work/linux-6.18.48/` | Disposable build source tree; recreated/synchronized from the archive and canonical overrides |
| `out/` | Logs, schema checks and source-verification reports |

Image outputs are in `development/perrier-ramenv/display-pll-only`. The confirmed
ram64 image remains untouched in `development/perrier-ramenv/gen4-touch`.
Historical development directories and evidence remain available; they are
not inputs to the active board DTS. Original Cypress references, first-port
generators and failed ram61–63 trials belong to the bring-up archive.

## Build and test

From `/home/marius/ext_proj/touch10`:

```sh
python3 development/kernel/build_image.py
python3 development/kernel/audit_image.py
python3 development/kernel/check_sources.py
python3 tools/touch10_uboot.py prepare --profile display-pll-only
python3 tools/touch10_uboot.py session --profile display-pll-only --minutes 30
```

The build exports the patch series, checks clean application to pristine
Linux, verifies the full work tree, and builds the initramfs/kernel/DTB.
Unrecorded edits in the work tree stop the build instead of being silently
overwritten. Change files under `source/`, then rebuild. The regular ARM
DT Makefile also contains the `omap4-cisco-perrier-ram.dtb` target.

`check_sources.py` uses the kernel's `checkpatch.pl` plus the upstream
`dtschema` command-line tools (`dt-doc-validate`, `dt-mk-schema` and
`dt-validate`) from `PATH`. Install dtschema in a Python virtual environment
if needed. It validates the touchscreen binding and actual touch node;
full-board schema conformance remains a separate validation task.

This PC's existing schema-tool environment is `/tmp/touch10-dtschema`.
Add `/tmp/touch10-dtschema/bin` to `PATH` before running the source checks
when it is not already present.

The image audit checks every packed file and the actual embedded initramfs,
the unchanged watchdog feeder, read-only storage policy, source hashes,
configuration, and load span. The DT audit resolves bus address translations
and phandles against ram65, checking GPIOs, supplies, PWM, clocks, DMA, IRQs
and panel timings. It restricts enabled upstream targets to the reviewed
set in `configs/bus-layout.json`. The Gen4 descriptor/report and I2C
transport tests run under ASan/UBSan. A further ten negative DT mutations
must be rejected by the bus auditor.

U-Boot stages and verifies immutable image files, saves the factory boot
path before the handoff, and opens the RAM environment over the existing
key-only SSH connection. The host renews its watchdog lease. Kernel tests
use U-Boot directly; Qt/userspace changes continue over RAM SSH without
rebuilding or rebooting the kernel. `python3 tools/touch10_ram.py recover`
returns to stock, and `recover --hardware` tests watchdog expiry. Use
`--profile mainline-bus` for ram66, `--profile mainline-ram` for ram65, or
`--profile gen4-touch` for ram64.

## Organization versus upstream submission

The source paths, binding and patch separation follow normal kernel
organization. The restored driver uses the 6.18 GPIO, regulator, IRQ,
touchscreen/input and timer APIs. Binding documentation and the actual
touch node are checked with DT schema tools. The local binding maintainer
is taken from the owner's configured Git identity; no patch was published.

This is a working board-support patch set, not a claim of upstream
acceptance. The upstream OMAP bus layout is now in use, while the verified
board-gated display quirks remain. Reducing those quirks, integrating
runtime power domains and production power management are separate
reviews. The RAM DT keeps the LCD/backlight rails on; PWM/GPIO151 control
brightness and blanking. Full rail power-down sequencing, SMP and a
physical power-removal test of the full image remain follow-ups. No PMIC
voltage programming was added during the migration.

The stock GPIO151 pad-address correction and the exact rail/reset/loader
protocol evidence are in the bring-up record and
[`perrier-backlight-pad-erratum-2026-11-10.md`](../../evidence/perrier-backlight-pad-erratum-2026-11-10.md).
The [archived Gen4 record](../archive/2026-11-10-gen4-bringup/README.md)
retains upstream source URLs, stock disassembly references and individual
trial results. [Patch notes](patches/README.md) describe the remaining
upstream-submission work without changing the verified electrical setup.
