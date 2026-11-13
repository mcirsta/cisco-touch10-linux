# Cisco Touch 10 / Perrier Linux development

Public source repository: [mcirsta/cisco-touch10-linux](https://github.com/mcirsta/cisco-touch10-linux).
See [publication and rebuild notes](PUBLICATION.md) for pinned dependencies,
local-only artifacts and the current full-image bootstrap requirements.

To build the standalone ram116 profile from a clean clone:

```sh
python3 development/standalone/build.py
```

The [standalone build guide](development/standalone/README.md) lists host
dependencies, optional SSH access and output paths. This builds the complete
image from source without earlier project binaries or private device files.
After its audits, it automatically preserves unpublished source changes,
removes temporary sources and build caches, and keeps two compact image bundles.

Compact ram116 and ram117 image bundles are retained locally
under `development/standalone/out/`. Duplicate source trees and build caches
have been consolidated, with unpublished differences preserved. See the
[source layout and recovery guide](development/SOURCE-LAYOUT.md).
Historical commands below may require rebuilding their inputs before use.

The active kernel workspace is [development/kernel](development/kernel/README.md).
It contains normal Linux source paths, a reproducible patch series against
Linux 6.18.48, the board DT, configuration, tests and build/audit tools.

Ram93 was the qualified `display-stop-fix` test profile, with pristine mainline
DISPC and DSS. It follows the DRM bridge power sequence: prepare the DSI PHY, release
bridge reset, start HS clock through a normal NULL transfer, configure the
bridge, then enable video. It also uses exact line-clock arithmetic,
regmap I2C and corrected virtual-channel completion handling. The owner
confirmed clean output, touch and brightness after six display/Qt restarts.
Keeping the stopped video channel disabled eliminated the host shutdown
timeouts. Hardware watchdog recovery took 152.6 seconds and restored the
exact factory environment. The panel returned to stock firmware; ram70
provided the `display-onoff` fallback, and ram91/ram85 source checkpoints remain.
See the [validation](development/kernel/validation-ram93.json),
[display comparison](development/kernel/display-reduction.md) and
[checkpoint](development/kernel/SESSION-CHECKPOINT.md). Ram69,
ram66, ram65 and ram64 also remain available as `display-pll-only`,
`mainline-bus`, `mainline-ram` and `gen4-touch`.

## Current board support

| Component | Implementation and evidence |
| --- | --- |
| SoC | TI OMAP4460 ES1.1; RAM tests currently use one Cortex-A9 CPU |
| Display | OMAP DRM/DSS/DSI, TC358765 support in `tc358775`, standard `panel-lvds`; 1280 × 800 aligned output |
| Touch | Restored upstream CYTTSP4 Gen4 core, modern DT/GPIO/regulator/input APIs, Perrier's older report/loader profile |
| Backlight | Standard `pwm-backlight`, timer10 PWM, GPIO151 enable and GPIO157 5 V supply; slider physically verified |
| Front keys | Mainline OMAP4 keypad; volume hold/repeat and single-toggle mute verified in Qt |
| Ethernet | Mainline OMAP EHCI and SMSC95xx; direct isolated link and root SSH |
| Thermal | Existing board thermal support and Qt readout; see the historical kernel-support records for individual sensor validation |
| Development | U-Boot RAM boot, initramfs, key-only SSH/file transfer/debug tools, Qt built from source |
| Recovery | Mainline hardware watchdog with nowayout, host lease and automatic return to stock |
| Storage | RAM tests force eMMC read-only and mount no eMMC filesystem |

The source/binding/patch layout follows mainline conventions. Remaining
work includes production runtime power domains, suspend/power management
and SMP. The bridge retains the measured TC358765 panel/PHY profile. See the
[active workspace](development/kernel/README.md) for the exact limits and
[current workflow](DEVELOPMENT-WORKFLOW.md) for test commands.

## Records and access

- [Root access and this unit's backup](ROOT-AND-BACKUP.md)
- [Original confirmed ram64 baseline](development/kernel/working-baseline.json)
- [Gen4 bring-up archive](development/archive/2026-11-10-gen4-bringup/README.md)
- [Backlight pad-address correction](evidence/perrier-backlight-pad-erratum-2026-11-10.md)
- [U-Boot one-shot qualification](development/perrier-coldboot/README.md)
- [Qt/toolchain record](development/perrier-qt/README.md)
- [Historical initial investigation](development/archive/README-investigation-before-kernel-cleanup.md)

Device access uses `ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10`
for stock, or `touch10-ram` for the temporary environment. The dedicated LAN
is 10.77.10.0/24; the PC is 10.77.10.1 and the panel is 10.77.10.10.
The USB FT230X service UART runs at 115200 baud. Raw backups and private
configuration stay local under `backups/` and `access/`.

Historical `perrier-*` directories and `development/runs/` retain evidence
from earlier stages. Use the active kernel workspace for new board changes;
old bring-up generators are no longer the source of the current patches.
