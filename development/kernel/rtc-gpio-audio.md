# RTC, expander and audio prerequisites

The ram96 `rtc-gpio` image groups three independent additions in one U-Boot
RAM boot. Display source, timing and existing wiring are unchanged from
ram95. The tests keep Qt running and perform no display blank/unblank or
Qt restart. The immediate fallback is qualified ram95 `peripherals`.

## RTC

The existing mainline `rtc-twl` driver binds to the TWL6032 child using
`ti,twl4030-rtc` and PMIC interrupt 11. The stock kernel uses the same RTC
and interrupt offset. HCTOSYS, SYSTOHC and RTC NVMEM are disabled in the RAM
configuration. The clock is unconfigured, showing 2000-01-01 under both
stock and RAM; the test never sets its calendar or the system clock.

The native RTC API advanced two seconds over a two-second interval. One
alarm set five seconds ahead delivered `RTC_AF` after 4.238 seconds of
monotonic time. The helper restored the original disabled alarm cache and
the exact six hardware alarm bytes and interrupt-enable byte. Readback
confirmed restoration. The driver also clears its handled alarm status.

Sources and fixed-address helper inputs are frozen under `baselines/ram96`.
Live evidence is in
`../runs/20261112T094548Z-uboot-ram96-0df43b/rtc-alarm.log` and `aux-checks.json`.
This proves an awake alarm interrupt, not suspend wakeup or retention across
loss of external power.

## PCF8574-compatible GPIO expander

Stock registers a `pcf8574` at I2C4/0x24, base 256, eight lines. Its platform
data has `n_latch=0` and no setup callback. Both stock and current mainline
probe initialize only a software output shadow, then read the port; they
do not write it. Earlier project notes that probe would write all-high were
incorrect. The read-only evidence and stock function addresses are saved in
`out/rtc-expander-audio/stock-expander-analysis.json`.

The new kernel uses the existing `gpio-pcf857x` driver and GPIO v2 character
device. Qt and the helper request all eight lines with **flags=0 (AS IS)**,
read and release them. They do not select input/output, bias, drive or
initial values. The ioctl trace confirms flags=0. Native GPIO and a direct
I2C read both return `0x11`; Qt shows the byte and its binary representation.
The pin functions and actual output latches remain unmapped. A port read
does not establish physical pin direction or a safe value to drive.

The generic driver's normal shutdown writes all ones. To preserve this
board's unknown latches, a small optional `retain-state-shutdown` binding
and driver guard skip that write. Boards without the property keep existing
behavior. The actual shutdown function passed ASan/UBSan tests for all 256
eight-bit latch states, five sixteen-bit patterns and both default shutdown
widths. Hardware-watchdog expiry bypasses device shutdown; the retention
branch is therefore verified offline, rather than claimed as a live
orderly-shutdown test. No reset GPIO, line hog or output consumer is enabled.

## PMIC 32 kHz clock providers

Unmodified `clk-twl` registers `clk32kg` and `clk32kaudio`, both 32768 Hz.
There are no consumers or assigned clocks, and both CCF prepare/enable
counts are zero. These providers retain `CLK_IGNORE_UNUSED`; global RAM
clock/power-domain retention remains unchanged. This adds their standard
clock API without changing clock hardware state.

PMIC 0x48 registers 0xbc through 0xc1 match the stock baseline before and
after the RAM checks: `00 01 01 00 01 01`. No enable, disable or rate-change
operation was tested. The returned rate is the driver's declared rate;
physical frequency measurement remains separate. PMIC internal oscillator
initialization is still skipped. No regulator, analog, charger, power-off
or audio child is enabled by this image.

## Audio evidence gathered before ram97

Read-only stock inspection saved 83 ALSA controls for card `idefix`, their
enumerations and current values. It also captured the McPDM pinmux and
GPIO127 (`audpwron`, currently high):

| Stock pad | Value | Signal |
| --- | --- | --- |
| 0x106 | 0x0100 | abe_pdm_ul_data |
| 0x108 | 0x0108 | abe_pdm_dl_data |
| 0x10a | 0x0118 | abe_pdm_frame |
| 0x10c | 0x0108 | abe_pdm_lb_clk |
| 0x120 | 0x0003 | GPIO127 audpwron |
| 0x1a0 | 0xc118 | sys_nirq2 |

Evidence: `stock-alsa-controls.log`, `stock-inventory.log` and
`stock-audio-pads-gpio-clock-index.log` under `out/rtc-expander-audio`.
Current mixer values do not establish physical speaker/microphone wiring.
The Qt volume control remains simulated.

The target kernel already supplies `drivers/mfd/twl6040.c`,
`sound/soc/codecs/twl6040.c`, `sound/soc/ti/omap-mcpdm.c`,
`sound/soc/ti/omap-dmic.c` and `sound/soc/ti/omap-abe-twl6040.c`.
The card compatible is `ti,abe-twl6040`, documented in
`Documentation/devicetree/bindings/sound/omap-abe-twl6040.txt`.
That existing McPDM/codec path is the starting point; stock ABE DSP controls
and effects are not automatically reproduced by it.

Before enabling it, extract stock machine routes, codec revision, VIO/V2V1
supplies, GPIO power sequence, interrupt configuration and MCLK source/rate.
Check the actual driver as well as its old text binding: probe enables
supplies and takes the audpwron GPIO, so it is not a read-only identification
step. In particular, the actual probe requests `ti,audpwron` as output-low
for supported codec revisions; do not copy the older text binding's GPIO
property spelling without checking the descriptor lookup and upstream DTs.
Map the amplifier and microphone endpoints before playback, capture
or a gain change. Once supported by this evidence, test native ALSA devices
in a combined RAM boot with bounded levels, no display cycling and the
unchanged watchdog recovery.

## Ram97 native speaker playback

The stock Perrier initializer is at `0xc07226b4`; it registers the audio
device at `0xc07aeb48` using data at `0xc07aeeb8`. Its handsfree channel mask
is 2 (right only), EP flag is 1, microphones/DMIC/headset/jack flags are zero
and nominal MCLK is 19.2 MHz. The codec platform data at `0xc07ae5c4` selects
GPIO127 and the automatic power sequence. Live stock confirms dummy vio/v2v1
consumers, enabled VANA at 2.1 V and an already-on 32 kHz audio clock. Dummy
consumer data does not identify the physical VIO net; the RAM image retains
those supplies without adding regulator programming.

The source/ABI bit definitions can be compared with the
[upstream machine-data header](https://cos.googlesource.com/third_party/kernel/+/934e18b5cb4531cc6e81865bf54115cfd21d1ac6/include/linux/platform_data/omap-abe-twl6040.h).
Cisco's extended structure also has an ABE flag; offsets were checked against
the actual stock instructions. The
[TI part documentation](https://www.ti.com/product/TWL6040) describes the
codec's generic speaker and differential EP outputs. Those names do not
establish which transducers the board actually populates.

Ram97 uses the existing TWL6040 MFD, codec and PDM-clock drivers, TWL PMIC
clock provider, OMAP McPDM and SDMA/ALSA PCM. All these drivers are unchanged.
One small generic card-driver correction removes the duplicate hardcoded
all-endpoint route table: the driver already requires DT audio-routing.
Perrier DT supplies HFR and EP according to the stock flags. Other ABE
peripheral targets remain disabled. The clock/power initialization uses
ordinary driver APIs, not userspace MMIO or GPIO bit-banging.

Native PCM advertises S32_LE at 88.2/96 kHz. A direct 48 kHz input was rejected
as advertised; the test inputs were corrected over SSH without rebooting.
Both native families passed silent PCM and DMA timestamp tests (about
88,124 and 96,024 frames/s). Four interleaved channels reach HFR in slot 3.
Three bounded tones at about -24 dBFS PCM and -24 dB HFR gain were heard
by the owner. This qualifies the internal HFR speaker path.

EP is a generic codec/DAPM label, not a physical earpiece identified on this
unit. The owner confirms only built-in speaker(s), with no external accessory.
EP PCM, DAPM and DAC/amp register activation passed, but minimum and modest
gain comparisons were inaudible. EP remains acoustically unqualified.
The active stock route is HFR and its EP playback switch is off.

Offline inspection of Cisco's alsafifo confirms mono 48 kHz S16_LE playback.
That plus the HFR channel mask supports a mono internal-speaker software
path, without proving the number of physical speaker transducers. Saved
decompilation and the stock/live interpretation are in the run directory.
At ram97, normal application audio still needed userspace rate conversion
and channel mapping, and Qt audio controls were simulated. The later
[ram99 application-audio work](application-audio.md) supplies both.

All 65 sampled PMIC rail fields matched ram95 before audio probe and stayed
unchanged through the tests. PMIC clock bytes stayed `00 01 01 00 01 01`,
the GPIO expander stayed 0x11, and all audio test gains/routes were restored.
Qt PID 113 stayed running: one RAM boot, zero display cycles, zero Qt
restarts. Hardware-watchdog recovery took 150.6 seconds. Stock Phoenix,
exact factory p8, the original 83 controls, HFR routing and all 65 stock
rail fields passed post-recovery checks; temporary helpers were removed.

Validation: [validation-ram97.json](validation-ram97.json). Immutable source
snapshot: `baselines/ram97` (121 files, eleven patches). Live evidence:
`../runs/20261112T102852Z-uboot-ram97-4a52f1/`. Ram96 is the immediate fallback.
The final diagnostic scripts, corrected-rate PCM inputs and Cisco userspace
analysis were created after the snapshot; executed copies and hashes are
archived in the live run. [Audio tools and next userspace work](../audio/README.md).
