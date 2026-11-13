# Touch 10 kernel development

This is the active Linux 6.18.48 board-support workspace. It replaces the
chain of experimental `perrier-*` build directories. The last physical
baseline is [ram64](working-baseline.json): the owner confirmed the display,
native Gen4 touch and brightness slider, and hardware-watchdog recovery
returned to stock in 154.4 seconds with the exact factory environment hash.
The organized ram65 image passed the same U-Boot RAM route, native input,
Qt reopen and hardware-expiry recovery in 153.7 seconds. It is now the
default U-Boot profile; see [validation-ram65.json](validation-ram65.json).

## Layout

| Path | Purpose |
| --- | --- |
| `source/drivers/input/touchscreen/` | Restored Cypress Gen4 core and I2C transport; edit these normal kernel files directly |
| `source/Documentation/devicetree/bindings/` | DT binding with supplies, reset, IRQ and standard touchscreen properties |
| `source/arch/arm/boot/dts/ti/omap/omap4-cisco-perrier.dtsi` | Consolidated hardware wiring, regulators, pinctrl and peripheral nodes |
| `source/arch/arm/boot/dts/ti/omap/omap4-cisco-perrier-ram.dts` | RAM memory/CPU/power policy and disabled duplicate SoC targets |
| `source/drivers/gpu/drm/` | Explicit Perrier display changes to existing mainline drivers |
| `patches/series` | Ordered, reproducible patches against the pristine kernel archive |
| `patches/ram-only/` | Experimental clock/PMIC-initialization and eMMC read-only safeguards, separate from driver support |
| `configs/perrier-ram.config` | Reproducible development kernel configuration; the builder fills in the initramfs path |
| `tests/` | Captured-data and I2C transport sanitizer tests; generated files stay in `tests/out/` |
| `work/linux-6.18.48/` | Disposable build source tree; recreated/synchronized from the archive and canonical overrides |
| `out/` | Logs, schema checks and source-verification reports |

Image outputs are in `development/perrier-ramenv/mainline-ram`. The confirmed
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
python3 tools/touch10_uboot.py prepare --profile mainline-ram
python3 tools/touch10_uboot.py session --profile mainline-ram --minutes 30
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
full-board schema conformance remains part of the interconnect migration.

The image audit checks every packed file and the actual embedded initramfs,
the unchanged watchdog feeder, read-only storage policy, source hashes,
configuration, and load span. It compares the DT against working ram64:
every active node/property must match, allowing phandle renumbering. The
disabled legacy simple-framebuffer is the only removed node. The Gen4
descriptor/report and I2C transport tests run under ASan/UBSan.

U-Boot stages and verifies immutable image files, saves the factory boot
path before the handoff, and opens the RAM environment over the existing
key-only SSH connection. The host renews its watchdog lease. Kernel tests
use U-Boot directly; Qt/userspace changes continue over RAM SSH without
rebuilding or rebooting the kernel. `python3 tools/touch10_ram.py recover`
returns to stock, and `recover --hardware` tests watchdog expiry. Use
`--profile gen4-touch` to select the preserved ram64 baseline explicitly.

## Organization versus upstream submission

The source paths, binding and patch separation follow normal kernel
organization. The restored driver uses the 6.18 GPIO, regulator, IRQ,
touchscreen/input and timer APIs. Binding documentation and the actual
touch node are checked with DT schema tools. The local binding maintainer
is taken from the owner's configured Git identity; no patch was published.

This is a working board-support patch set, not a claim of upstream
acceptance. The existing bring-up SoC bus layout and board-gated display
quirks are deliberately retained. Migrating those nodes to the complete
upstream interconnect hierarchy, reducing the display quirks individually,
and production power management are separate reviews. The RAM DT keeps
the LCD/backlight rails on; PWM/GPIO151 control brightness and blanking.
Full rail power-down sequencing, SMP and a physical power-removal test of
the full image remain follow-ups. No speculative PMIC voltage change was
introduced during this cleanup.

The stock GPIO151 pad-address correction and the exact rail/reset/loader
protocol evidence are in the bring-up record and
[`perrier-backlight-pad-erratum-2026-11-10.md`](../../evidence/perrier-backlight-pad-erratum-2026-11-10.md).
The [archived Gen4 record](../archive/2026-11-10-gen4-bringup/README.md)
retains upstream source URLs, stock disassembly references and individual
trial results. [Patch notes](patches/README.md) describe the remaining
upstream-submission work without changing the verified electrical setup.
