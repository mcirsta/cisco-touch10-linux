# Touch 10 kernel development

The complete ram116 image now has a
[standalone build entry point](../standalone/README.md):
`python3 development/standalone/build.py` from the repository root. It uses
the versioned board patch series plus the standalone ram116 CPU-voltage
patch and configuration. Earlier image builders below remain historical
incremental generators; the standalone builder needs no earlier image,
rootfs, private key or live-test log.

Superseded checkpoint source copies are now retained in Git history and
unpublished expanded-tree differences are preserved locally. See the
[source layout and recovery guide](../SOURCE-LAYOUT.md). Historical reports
and measured evidence remain available below.

This is the active Linux 6.18.48 board-support workspace. The qualified
default is `mailbox-audio-dt` ram104, with `native-diagnostics` ram100 as
the immediate fallback. Ram104 packages upstream ALSA `dmix` for concurrent
speaker playback and binds the upstream OMAP mailbox and hardware-spinlock
providers through an isolated L4 DT segment. Both providers remain runtime
suspended with remote processors disabled. One RAM boot verified both
bindings, two simultaneous 48 kHz clients, stable Qt/watchdog and exact
stock recovery without display reset tests. See
[validation-ram104.json](validation-ram104.json) and
[remaining-support.md](remaining-support.md). The
[mainline driver coverage](mainline-driver-coverage.md) records which
hardware blocks use unchanged drivers and which patches still need work.

The validated `network-dualstack` ram105 candidate adds upstream IPv6.
Its Ethernet link-local address matched stock, and it reached the PC over
IPv6. A bounded BusyBox DHCP exchange obtained the PC's fixed lease while
keeping the static RAM SSH address. The system clock accepted host time in
RAM; the unconfigured PMIC RTC was not written. Qt and watchdog stayed up,
and stock recovered with exact factory p8 and approved ADC postflight.
Ram104 remains the default until normal LAN route/DNS and lease-loss handling
are qualified. See [validation-ram105.json](validation-ram105.json) and the
[full-functionality roadmap](FULL-STOCK-ROADMAP.md).

The validated `network-dhcp` ram106 candidate now applies and renews the
fixed isolated DHCP lease. It keeps 10.77.10.11 as a separate rescue address;
key-authenticated SSH worked through both addresses. Qt and watchdog stayed
alive, and stock recovery restored exact factory p8 and ADC sensing state.
Its script deliberately rejects router and DNS options from this test LAN.
Ram104 remains the default while normal production LAN policy is developed.
See [validation-ram106.json](validation-ram106.json).

The validated `network-route-dns` ram107 candidate adds bounded DHCP gateway,
resolver and lease-loss state in the volatile rootfs. Its initial run checked
injected route/DNS state and real lease-loss cleanup. The unchanged script in
ram110 then received real router and DNS options from the isolated PC's
temporary DHCP server, resolved a local test name, and removed both settings
on renewal after the normal server returned. Qt/watchdog and exact stock
recovery passed with no display reset or Qt restart. Arbitrary LAN leases
and a production time source remain open. See the
[ram107 validation](validation-ram107.json),
[real-option validation](validation-ram110-network.json) and
[network record](network-route-dns.md).

An audited ram108 candidate builds the same image with SMP infrastructure,
forces `nosmp`, and keeps CPU1 disabled in the unchanged DTB. Its exact
initramfs archive passed a generic two-core Cortex-A9 QEMU parser boot.
The Touch 10 then passed one ram108 U-Boot RAM boot: `/init`, RAM SSH, mainline
watchdog and one Qt startup worked with CPU1 off. Requested reboot restored
stock, exact factory p8 and ADC sensing state. The
[ram108 validation](validation-ram108.json) and
[test plan](../perrier-smp/ram108-plan.md) record the evidence and watchdog
boundary. This isolates the U-Boot handoff from CPU1 startup; it does not
validate dual-core operation.

The follow-on ram109 candidate passed a one-shot U-Boot RAM boot with CPU1
present in DT, `maxcpus=1`, and CPU hotplug enabled. After the mainline
watchdog was feeding, one request brought CPU1 online. A CPU1-pinned command,
timer interrupts and scheduler counts confirmed execution. Qt stayed up,
eMMC stayed read-only, and requested reboot restored stock, exact factory p8
and approved ADC state. Boot-time CPU1 release remains untested. See the
[ram109 validation](validation-ram109.json) and
[plan](../perrier-smp/ram109-plan.md).

Ram110 removed the `maxcpus=1` limit while preserving ram109's DTB and
hardware policy. Three U-Boot RAM boots started both CPUs before `/init` and
restored exact stock state afterward. The second run kept both CPUs online
for about six minutes, ran a bounded CPU1 load, exercised concurrent ALSA
playback, and checked Ethernet, sensors, EEPROM and the watchdog without
display cycling. See the [initial validation](validation-ram110.json),
[extended validation](validation-ram110-extended.json),
[network validation](validation-ram110-network.json) and
[plan](../perrier-smp/ram110-plan.md). The qualified default remains ram104
while production power policy and longer-term SMP behavior remain open.

Ram100 adds the unmodified mainline TWL6032 ADC and
Cortex-A9 PMU/perf drivers through DT/config changes. Twenty-five internal
voltage conversions delivered 25 interrupts; cycle counting delivered 50
overflow samples without losses. General PMU events still read zero and
remain unqualified. Ram101/102 traced this to disabled CPU debug
authentication; see [the PMU investigation](pmu-investigation.md). Display
and Qt stayed running throughout.

Watchdog recovery took 155.0 seconds. Three sensing enables survived the
warm reset; the owner authorized their exact restoration and future
postflight. The guarded cleanup restored and verified their saved values.
Stock audio, ADC controls/calibration, all 65 supply fields, Phoenix and
factory p8 passed. The controller now checks its approved cleanup before
booting this profile and runs it after stock returns. See
[validation-ram100.json](validation-ram100.json) and
[the native diagnostics record](native-diagnostics.md).

Ram100 retains ram99's normal mono/stereo 48 kHz playback and native Qt
ALSA volume/mute/front-key controls. The owner confirmed tones, volume and
mute. The [application audio record](application-audio.md) and
[audio build notes](../audio/README.md) describe that unchanged support.

Ram99's kernel sources, hardware configuration, board DTB and watchdog helper
match ram97. That earlier baseline mapped stock Perrier supplies, control pads,
GPIO127 and audio routes before using mainline TWL6040 MFD/codec/clocks,
McPDM and SDMA. The card driver has one generic DT-routing correction;
other audio drivers are unmodified. Native 88.2/96 kHz S32_LE DMA timing
and HFR acoustic playback passed. See
[validation-ram97.json](validation-ram97.json) and
[the stock/native audio record](rtc-gpio-audio.md).

EP is a generic codec label, not evidence of a separate physical earpiece.
It remains unused and acoustically unqualified. The ram104 default PCM now
supports simultaneous clients through `dmix`. Stock ABE DSP effects and
production power management remain separate.

The preserved `rtc-gpio` ram96 profile verified native TWL RTC
counter/alarm support, AS-IS reads from the eight-line GPIO expander and
both TWL 32 kHz clock providers. Qt shows RTC and GPIO status. The RTC alarm
state was restored exactly; GPIO and clock settings matched the stock
baseline before and after recovery. Testing used zero display cycles and
zero Qt restarts. Hardware-watchdog recovery took 151.8 seconds with exact
factory p8 restored. See [validation-ram96.json](validation-ram96.json) and
[the RTC, GPIO and audio record](rtc-gpio-audio.md). GPIO outputs/pin functions, physical clock-frequency measurement
and suspend wakeup remain unqualified.

The preserved `peripherals` ram95 profile combines the white PMIC PWM indicator,
all six INA3221 voltage/current channels and read-only AT24 EEPROM using
unmodified mainline drivers. The EEPROM matches its 256-byte stock baseline;
the sensor shunts/config/alert policy match stock. Qt shows all six channels
and controls the white indicator, which the owner confirmed. Testing used
one RAM boot with zero display cycles and zero Qt restarts. Watchdog recovery
returned to stock in 153.7 seconds, with exact factory p8 and all sampled
PMIC settings restored. See [validation-ram95.json](validation-ram95.json).

The earlier `native-leds` ram94 profile adds the red and green mute indicators
through unmodified mainline `gpio-leds` and the board DT. Stock board data
and live pad readback confirm GPIO122/119, active-high, output/pull-down
mode 3. Both are off at kernel startup. Qt uses their standard LED sysfs
devices and restores their initial state on exit. Twenty physical mute
presses produced matching red/green readback; the owner confirmed both
colors, clean display, touch and brightness. Hardware watchdog recovery
returned to stock in 153.8 seconds with exact factory p8 restored.
See [validation-ram94.json](validation-ram94.json) and the
[remaining support plan](remaining-support.md).

The `display-stop-fix` ram93 profile remains the preserved
display baseline. It keeps the mainline OMAP4460 bus layout,
normal PLL search (N=19/M=211), pristine DISPC/DSS, ONOFF=1, ALIGN=1 and
the mainline PRCM core-clock source. It uses mainline HSYNC, porch and pad
configuration, with generic PHY-only
pre-enable and post-disable phases. The bridge releases reset before asking
the host to start HS clock through a normal NULL transfer. Regmap checks I2C
errors, completion callbacks track the requested channel, and common-DCO
divider arithmetic avoids rounded-Hz line comparisons.
At shutdown the video VC stays disabled while the command VC remains
available. This removed the host HS transmit timeout. Six display/Qt
restart cycles reported zero display errors; the owner confirmed clean
alignment, touch and brightness. Hardware watchdog recovery returned
to stock in 152.6 seconds with the exact factory environment restored.
Temporary ram92 timing instrumentation is removed. See
[validation-ram93.json](validation-ram93.json) and
[SESSION-CHECKPOINT.md](SESSION-CHECKPOINT.md).

Ram70 is the preserved `display-onoff` fallback, including its frozen
sources under `baselines/ram70`. Ram69 remains `display-pll-only`, with
sources under `baselines/ram69`. Ram66 remains `mainline-bus`, with sources in
`baselines/ram66` and [bus migration record](bus-migration.md). The ram67 and
ram68 DISPC-removal trials showed a red column after display cycling and
were not promoted. The ram71 ALIGN trial failed with the earlier pipeline;
upstream ALIGN and core clock subsequently passed independently and
together with the corrected sequence and arithmetic. See
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

The confirmed image is in `development/perrier-ramenv/native-audio`,
with frozen source, eleven patches and tools under `baselines/ram97`.
New builds go to the profile selected by `DEST` in `build_image.py`;
the output manifest and reviewed-image record identify its profile and
kernel version. Use that matching profile after reviewing its audit. The confirmed
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
# Set this to the profile in the newly built reviewed-image.json.
touch10_profile=native-audio
python3 tools/touch10_uboot.py prepare --profile "$touch10_profile"
python3 tools/touch10_uboot.py session --profile "$touch10_profile" --minutes 60
```

The build exports the patch series, checks clean application to pristine
Linux, verifies the full work tree, and builds the initramfs/kernel/DTB.
Unrecorded edits in the work tree stop the build instead of being silently
overwritten. Change files under `source/`, then rebuild. The regular ARM
DT Makefile also contains the `omap4-cisco-perrier-ram.dtb` target.

`check_sources.py` uses the kernel's `checkpatch.pl` plus the upstream
`dtschema` command-line tools (`dt-doc-validate`, `dt-mk-schema` and
`dt-validate`). It prefers the workspace-local `.venv-dtschema/bin`, then
falls back to `PATH`. It validates the touched bindings and the selected
touch, LED, sensor, EEPROM, PMIC and expander nodes; full-board schema conformance remains a
separate validation task.
The separate hardware audit checks the exact RTC IRQ and clock-provider
properties against the reviewed board wiring.

The schema environment lives in `development/kernel/.venv-dtschema` so it
survives temporary-directory cleanup. Recreate it with `python3 -m venv`
and install `dtschema` using that environment's Python if needed. Install
records are kept under `out/display-finalization/schema-install-20261111.*`.

The image audit checks every packed file and the actual embedded initramfs,
the unchanged watchdog feeder, read-only storage policy, source hashes,
configuration, and load span. The DT audit resolves bus address translations
and phandles against ram65, checking GPIOs, supplies, PWM, clocks, DMA, IRQs
and panel timings. It restricts enabled upstream targets to the reviewed
set in `configs/bus-layout.json`. The Gen4 descriptor/report and I2C
transport tests run under ASan/UBSan. A further ten negative DT mutations
must be rejected by the bus auditor.
The LED extension also rejects nine unsafe GPIO, polarity, pad, startup
and unrelated-property mutations against the exact ram93 DT.
The ram95, ram96 and ram97 extensions reject another thirteen, twelve and
fourteen mutations respectively, for 58 total. The actual PCF857x shutdown function is tested
under ASan/UBSan for retained latch states and unchanged default behavior.

U-Boot stages and verifies immutable image files, saves the factory boot
path before the handoff, and opens the RAM environment over the existing
key-only SSH connection. The host renews its watchdog lease. Kernel tests
use U-Boot directly; Qt/userspace changes continue over RAM SSH without
rebuilding or rebooting the kernel. `python3 tools/touch10_ram.py recover`
returns to stock, and `recover --hardware` tests watchdog expiry. Use
`--profile rtc-gpio` for the immediate ram96 fallback,
`--profile peripherals` for ram95,
`--profile native-leds` for ram94,
`--profile display-stop-fix` for ram93,
`--profile display-onoff` for ram70, `--profile display-pll-only` for ram69,
`--profile mainline-bus` for ram66,
`--profile mainline-ram` for ram65, or
`--profile gen4-touch` for ram64.

Group independent, reviewed peripheral additions into one RAM image when
practical. For work outside the display path, carry forward the qualified
display evidence if its drivers and DT are unchanged. Keep Qt running and
do not add blank/unblank cycles, Qt restarts or repeated alignment/touch
qualification to unrelated peripheral checks. Capture screenshots by reading
the framebuffer. A regression or an actual display change justifies a new
display-specific test.

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
