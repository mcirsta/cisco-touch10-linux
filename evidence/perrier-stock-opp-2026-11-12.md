# Perrier CE9.9.0 stock OPP table

The channel assignment at the end of this original 2026-11-12 note was
superseded by the [stock VP read and saved RAM-boot comparison](perrier-omap-vp-stock-2026-11-13.md): INA channel 1 tracks MPU and channel 3
tracks CORE with high confidence. The OPP voltages below remain nominal
table entries, not measured running voltages.

The saved stock Linux image's OMAP4460 branch in `omap4_opp_init` at
`0xc071e994` registers 21 entries beginning at `0xc074d420`. Each entry
is 24 bytes: hardware module string pointer, voltage-domain string
pointer, clock string pointer, frequency, nominal microvolts, and a
default-available flag. These values were read from the exact saved
`development/stock-kernel/ce990-Image.bin` in IDA, not inferred from
another board's source tree.

| Hardware/clock | Domain | Frequency | Nominal voltage | Default |
| --- | --- | ---: | ---: | --- |
| MPU / `virt_dpll_mpu_ck` | `mpu` | 350 MHz | 1.025 V | no |
| MPU / `virt_dpll_mpu_ck` | `mpu` | **700 MHz** | **1.203 V** | yes |
| MPU / `virt_dpll_mpu_ck` | `mpu` | 920 MHz | 1.317 V | yes |
| MPU / `virt_dpll_mpu_ck` | `mpu` | 1200 MHz | 1.380 V | yes |
| MPU / `virt_dpll_mpu_ck` | `mpu` | 1500 MHz | 1.390 V | no |
| L3 / `virt_l3_ck` | `core` | 100 MHz | 0.962 V | yes |
| L3 / `virt_l3_ck` | `core` | 200 MHz | 1.127 V | yes |
| L3 / `virt_l3_ck` | `core` | 200 MHz | 1.250 V | yes |
| IVA / `virt_iva_ck` | `iva` | 133 MHz | 0.950 V | yes |
| IVA / `virt_iva_ck` | `iva` | 500 MHz | 1.376 V | no |

The other eleven entries cover GPU, FDIF, DSP, and AESS clocks. Several
of those share `core` or `iva` domains, so an application load can change
current in a domain other than `mpu`.

At the observed stock 700 MHz CPU setting, INA3221 `4-0041` reads
0.992 V on channel 1, 1.216 V on channel 2, and 0.960 V on channel 3.
Those three voltages resemble the stock CORE lower point, MPU 700 MHz
point, and IVA lower point, respectively, within 10–30 mV. That suggests
one possible channel order, but the [bounded arithmetic test](perrier-ina-arithmetic-2026-11-12.md)
found a +120 mA and +190 mA response on the 0.992 V channel with one and
two CPU workers. The 1.216 V channel did not rise. The arithmetic workers
also use memory and interconnects, so neither voltage resemblance nor
current response identifies the physical rail by itself. **Keep the channel
mapping unresolved** at the time of this note. The subsequent VP/INA
comparison resolves channels 1 and 3 with high confidence, while channel
2 remains unidentified. The board table provides no channel labels.

The inherited mainline OMAP4460 DT table has 350/700/920 MHz at
1.025/1.200/1.313 V; it omits stock's enabled 1.2 GHz point and differs
slightly at 700 and 920 MHz. Ram111 still has CPUfreq disabled and
performs no OPP transition. Before DVFS development, compare ABB and
voltage-controller policies as well as this table.
