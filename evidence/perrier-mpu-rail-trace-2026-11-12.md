# Perrier MPU rail trace (2026-11-12)

The channel-map uncertainty recorded in the 2026-11-12 live cross-check
was superseded by the [stock VP and saved RAM-boot comparison](perrier-omap-vp-stock-2026-11-13.md). Its high-confidence mapping is INA channel
1 to MPU and channel 3 to CORE; the physical PCB nets remain unmeasured.

## Conclusion and limits

Cisco's CE9.9.0 MLO programs the TWL6032 SMPS1 voltage register, and its
Linux 3.4 kernel registers that same register as the `mpu` voltage domain.
The two stages independently identify **TWL6032 SMPS1 / VCORE1 as the
intended software-controlled VDD_MPU supply** on this Perrier image. This is
strong board-specific evidence, substantially better than inferring wiring
from TI's generic OMAP4460 design. It does not electrically prove the PCB
connection or measure the actual MPU package voltage.
TI's [OMAP4460 errata, section 3.9](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf)
explicitly distinguishes boards where a TPS62361B powers VDD_MPU from boards
where the TWL6030/6032 supplies it; the latter topology is valid for this
SoC family.

All live commands in this investigation only read stock state. No clock,
voltage, regulator, PMIC, U-Boot or storage setting was changed.

## Exact Cisco images

| Image | Saved file | SHA-256 |
| --- | --- | --- |
| MLO | `firmware/codec-ce9.9.0/analysis/touch10-ce990-mlo-isw.bin` | `45b80e799a7e0874001269e52a33c0b17421c0c1555b004631685f6dcfc5eab1` |
| U-Boot code | `firmware/codec-ce9.9.0/analysis/touch10-ce990-uboot-code.bin` | `dc6c33ff20c0a490cba102298249ba0b0383edd8992f55a2ad57d2ef322a4844` |
| Stock Linux | `development/stock-kernel/ce990-Image.bin` | `ba6d9c510b6c4fe864d1f29ccd32d5b36b081169e3b130125bc8d412af3b1e18` |

The addresses below refer to the saved images' existing IDA databases. The
installed MLO/U-Boot copies were matched to the CE package in
`evidence/recovery-safety-review-2026-11-07.md`.

## Early MLO voltage writes

The MLO entry path calls its voltage setup at `0x403044d0` -> `0x403047e8`.
At `0x40304854` it obtains a SoC revision code. Its OMAP4460 ES1.1 path
returns `0x11` at `0x40304608`, so it takes the `0x10..0x2f` branch at
`0x4030486c..0x40304878`. The branch issues three calls through
`0x403044e4`, whose instruction sequence places a data byte in bits 23:16,
register in bits 15:8, and slave address `0x12` in bits 7:0 of
`PRM_VC_VAL_BYPASS` (`0x4a307ba0`).

| Call site | PMIC register | Data | TI TWL6032 rail | Nominal voltage from TI's 709 mV + (code - 1) × 12.66 mV conversion |
| --- | --- | --- | --- | --- |
| `0x40304880` | `0x5b` | `0x22` | SMPS2 / VCORE2 | 1.12678 V |
| `0x4030488c` | `0x55` | `0x28` | SMPS1 / VCORE1 | 1.20274 V |
| `0x40304898` | `0x49` | `0x14` | SMPS5 | 0.94954 V |

TI's [OMAP4 register definitions](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/include/asm/arch-omap4/clock.h?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8)
identify `0x55`, `0x5b`, and `0x49` as TWL6032 SMPS1, SMPS2, and SMPS5,
and `0x12` as the PMIC's voltage-controller slave address. The conversion
above follows the TWL6030/6032 data in TI's
[OMAP4 U-Boot source](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/omap4/hw_data.c?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8);
it is an expected selector voltage, not a measurement.
The voltage-controller address `0x12` is distinct from the Linux I2C
client address `0x48` used to enumerate the TWL6032; comparing those
numbers as though they were one I2C client address would be misleading.

## Stock Linux domain mapping

The stock kernel's `omap_twl4030_init` at `0xc071d20c` detects SoC family
`0x446` and rewrites three PMIC data entries before registering its domain
table at `0xc0749320` through `omap_pmic_register_data` (`0xc071ca10`).
The table contains the strings `mpu`, `core`, and `iva` and the following
data pointers:

| Domain | Data pointer | Voltage register / command register | Stock range |
| --- | --- | --- | --- |
| `mpu` | `0xc079a948` | `0x55` / `0x56` | 750,000–1,380,000 µV |
| `core` | `0xc079a8d8` | `0x5b` / `0x5c` | 750,000–1,250,000 µV |
| `iva` | `0xc079a910` | `0x49` / `0x4a` | 750,000–1,370,000 µV |

Each entry contains PMIC slave `0x12`. Thus the kernel's `mpu/core/iva`
order exactly matches MLO's SMPS1/SMPS2/SMPS5 addresses. Perrier's board
initializer at `0xc072251c` registers `twl6032`; the stock boot log shows
VCORE1 and VCORE2 setup at 0.238 seconds.

The image also contains `CONFIG_OMAP_TPS6236X=y` and
`omap_tps6236x_board_setup` at `0xc071d80c`. IDA found no direct call or
data reference to that board-setup function; its associated initializer
starts with an unset GPIO configuration. Compiled support alone therefore
does not establish a TPS62361 on Perrier. An unresolved indirect call cannot
be categorically excluded from static analysis.

## Why the U-Boot TPS table is not board evidence

The bundled U-Boot's `0x80e81b48` revision dispatch selects TI's generic
OMAP4460 voltage table beginning at `0x80eaaba0` for `0x44600100` or
`0x44600110`: MPU nominal value 1203 mV, register `0x01`, and a pointer to
TPS62361-style conversion data at `0x80eaac1c`. The same data has
`i2c_slave_addr = 0x12`. U-Boot's voltage-scaling call is gated by a
boot-context test at `0x80e81038`; this static inspection did not establish
that predicate's value on a normal Perrier boot.
TI's [generic OMAP4 U-Boot source](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/omap4/hw_data.c?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8)
has this combination, while TI's
[TPS62361B datasheet](https://www.ti.com/lit/ds/symlink/tps62360.pdf)
specifies 7-bit address `0x60`. The selected table's presence does not show
a Perrier TPS device or a successful runtime write to one. The MLO and
kernel's matching TWL mapping are more specific to the shipped board
behavior.

## Read-only live cross-check

Stock identifies as OMAP4460 ES1.1/Perrier, Linux 3.4.113+, with `twl6032`
at I2C1 address `0x48`. Stock `/sys/class/regulator` exposes no VCORE1
regulator, so its absence there says nothing about a voltage-controller
managed rail. CPUfreq reports `omap2plus`, `userspace`, and 700 MHz during
this check; stock lists 700, 920 and 1200 MHz.

The second INA3221 monitor at I2C4 address `0x41` repeatedly read bus
voltages 0.992, 1.216, and 0.960 V on channels 1–3 during 700 MHz
samples. The 1.216 V reading resembles MLO's initial 1.203 V MPU selector,
but the stock kernel may change the selector after MLO. The monitor
channels have no saved board labels, so voltage resemblance is not a net
assignment. The other INA3221 at `0x40` and all six channels are exposed
in stock sysfs.

### Read-only current correlation

A bounded `/dev/zero` to `gzip` workload kept stock CPUfreq at 700 MHz.
Three six-sample idle/load pairs in
[`perrier-ina-interleaved-labeled-2026-11-12.csv`](perrier-ina-interleaved-labeled-2026-11-12.csv)
gave the following current changes on the `0x41` monitor, in mA:

| Channel, idle bus voltage | Pair 1 | Pair 2 | Pair 3 |
| --- | ---: | ---: | ---: |
| 1, 0.992 V | +106 | +104 | +61 |
| 2, 1.216 V | +22 | +45 | +28 |
| 3, 0.960 V | +72 | -85 | -29 |

The first longer load trace also showed channel 1 rising by about 91 mA
relative to a separate 12-sample idle baseline. Raw captures are
[`perrier-ina-cpu-load-2026-11-12.csv`](perrier-ina-cpu-load-2026-11-12.csv),
[`perrier-ina-idle-2026-11-12.csv`](perrier-ina-idle-2026-11-12.csv), and
[`perrier-ina-interleaved-2026-11-12.csv`](perrier-ina-interleaved-2026-11-12.csv).
Channel 1 is the most consistently load-correlated of these three.
The workload also stresses memory and interconnects, so this does not
distinguish a direct MPU supply from a CORE supply. A separate
[decode of the exact stock OPP table](perrier-stock-opp-2026-11-12.md)
shows 700 MHz MPU at 1.203 V, CORE's lower point at 0.962 V, and IVA's
lower point at 0.950 V. These align with monitor channels 2, 1, and 3,
respectively, within 10–30 mV. Together with the current response, this
originally suggested channel 2 as a VDD_MPU candidate. A separate
[bounded arithmetic test](perrier-ina-arithmetic-2026-11-12.md) at the
same 700 MHz setting showed channel 1 rising +120 mA with one CPU worker
and +190 mA with two workers, while channel 2 fell about 40–46 mA.
This conflicts with assigning channels from nominal voltage alone. The
channel mapping is **unresolved**; channel 1 is clearly sensitive to CPU
work, but memory/interconnect power can explain that without making it
VDD_MPU.

## Mainline consequence and next evidence

Pristine Linux 6.18.48's `drivers/regulator/twl6030-regulator.c` and
`Documentation/devicetree/bindings/mfd/ti,twl.yaml` support TWL6032
SMPS3/SMPS4/VIO but do not expose SMPS1, SMPS2 or SMPS5. Its older
TWL6030 VDD1–VDD3 voltage callbacks return `-ENODEV`. The common Perrier
DT has no CPU `vcc-supply`, and the RAM kernel keeps `CONFIG_CPU_FREQ`
off. Adding a supply phandle alone would not create a working voltage
path. A read-only SMPS1 observer was built as ram111 but
[retired before device use](../development/kernel/smps1-observe.md): its
control-I2C read returned zero for powered rails. It is absent from the
active source and DT patch series.

The [one-time stock I2C read](perrier-smps-selector-stock-2026-11-13.md)
returned `0x00` at the three voltage offsets on control I2C `0x48`. It did
not read the separate SmartReflex interface used by the OMAP voltage
controller at slave `0x12`. The subsequent
[stock VP snapshot](perrier-omap-vp-stock-2026-11-13.md) read a current
requested MPU selector of `0x18` (1.00018 V) and CORE selector of `0x16`
(0.97486 V), very close to INA channel 1 at 1.000 V and channel 3 at
0.976 V. Combined with channel 1's CPU-load current response, this is
strong software evidence for the monitor assignment. The saved ram110
peripheral log strengthens it: with adaptive voltage off, the same INA
channels moved to 1.208 and 1.128 V, close to MLO's fixed SMPS1/SMPS2
settings of 1.20274 and 1.12678 V. Channel 2 stayed at 1.216 V. The
assignment of channels 1 and 3 to MPU and CORE is therefore high
confidence, though still not a direct physical net measurement. Stock
SmartReflex Class3 and the enabled MPU VP can explain the difference from
the configured ON selector `0x29`, but the snapshot alone does not prove
the cause. Exact stock OPP/ABB policy still needs review. CPUfreq and
voltage writes remain disabled.
