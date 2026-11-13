# OMAP4 PM late-init write audit

## Why the TWL6032 address fix is insufficient

Ram110 and the thermal-policy boot intentionally blacklist
`omap2_common_pm_late_init`. The OMAP4 TWL6032 address patch is compiled
offline but is not present in either booted kernel. This audit follows
pristine Linux 6.18.48's call path before considering its activation:

`omap2_common_pm_late_init()` calls `omap4_twl_init()`,
`omap_voltage_late_init()`, `omap_devinit_smartreflex()`,
`omap4_pm_init()` and `omap2_clk_enable_autoidle_all()`. The OMAP4 PM
routine also changes powerdomain and clockdomain target states, MPUSS and
idle handling. Removing the blacklist is therefore a broad system change.

`omap_voltage_late_init()` iterates the MPU, IVA and CORE voltage domains.
For each domain, `omap_vc_init_channel()` writes the VC slave, voltage and
command-register addresses, command values, channel configuration, I2C
mode/timing, PMIC signaling, and voltage-ramp timing. `omap_vp_init()` then
writes VP config, step minimum, step maximum and voltage limits. These are
live OMAP register writes even with CPUfreq and AVS disabled.

| Item | Saved stock MPU state | Pristine mainline init if enabled |
| --- | --- | --- |
| VC command ON / ONLP | selector `0x29` / `0x29`, about 1.215 V | generic OMAP4 1.375 V target converts to selector `0x36`, about 1.380 V with the unit's offset bit |
| VC command RET / OFF | selector `0x05` / `0x00` | 837.5 mV RET target converts to `0x0c`, about 848 mV; OFF stays zero |
| VP MPU config | `0x00242909`, with `VPENABLE=1` | first `omap_vp_init()` write is `0x00000008` from its default error offset and `TIMEOUTEN`, clearing `VPENABLE` and the prior init/ON state |
| VC PMIC addresses | Cisco/TWL6032 MPU `55/56`, CORE `5b/5c`, IVA `49/4a` | pristine Linux maps CORE `61/62`, IVA `5b/5c`; isolated patch corrects addresses only |

The selector conversion uses the stock offset EPROM bit and Linux's
`twl6030_uv_to_vsel()` arithmetic: `V = 709000 + (selector - 1) * 12660`
microvolts. The command table is not a direct voltmeter, and a register
write does not by itself prove an immediate physical rail change. It does
show that merely fixing the two addresses and enabling the late init would
replace known working command and VP state. The 1.375 V generic command
also exceeds the 1.200 V maximum configured in the CORE VP limit data.
**Keep the PM late init blacklisted.**

At the board's measured 38.4 MHz `sys_clkin_ck`, the mainline VP init would
also replace these captured fields. This arithmetic follows `omap_vp_init()`
with mainline's 12,660 µV step, 4,000 µV/µs slew rate and 200 µs timeout;
it assumes the measured TWL6032 offset bit is read successfully.

| VP field | Saved stock | Calculated pristine mainline write |
| --- | --- | --- |
| MPU limits | `0x37051e00` | `0x390b1e00` |
| CORE limits | `0x2c051e00` | `0x280b1e00` |
| IVA limits | `0x36051e00` | `0x2d0b1e00` |
| Minimum step, all domains | `0x00003701` | `0x00007a01` |
| Maximum step, CORE | `0x00003704` | `0x00007a04` |
| Maximum step, MPU and IVA | `0x00003705` | `0x00007a04` |

The limits encode maximum selector, minimum selector and timeout. These
differences reinforce that a PMIC address-only patch is not a safe switch
to the full mainline init sequence. The stock and predicted words are
register settings; no live mainline write was attempted.

## Stock snapshot and next implementation boundary

The owner-authorized [31-word stock snapshot](../../../evidence/perrier-omap-prm-power-stock-2026-11-13.md)
confirmed the Cisco/TWL6032 register map and captured all three VC command
words. Stock ON selectors are MPU `0x29` (about 1.215 V), CORE `0x23`
(about 1.139 V), and IVA `0x36` (about 1.380 V). All RET selectors are
`0x05`; pristine mainline would write `0x0c`. All three stock VPs are
enabled. Its current MPU/CORE requests were about 0.988/0.962 V, close to
subsequent INA3221 readings of 0.992/0.960 V on the likely matching rails.
The snapshot helper was removed and stock boot health was verified.

A future kernel should separate passive PMIC/address registration from
VC/VP programming, preserve the working 700 MHz voltage state and retain
the watchdog. It must express board-appropriate ON/RET commands and VP
limits, and account for the stock adaptive voltage behavior before enabling
any PM late init. Only a reviewed, bounded transition can test a lower
fixed MPU voltage. CPUfreq and the 920 MHz OPP remain disabled until a
real voltage-control path and safe transition ordering are established.

Sources: local OMAP4460 TRM `development/kernel/references/omap4460-swpu235ab.pdf`,
Linux 6.18.48 `arch/arm/mach-omap2/{pm.c,pm44xx.c,voltage.c,vc.c,vc44xx_data.c,vp.c,vp44xx_data.c,omap_twl.c}`,
and the [stock VP snapshot](../../../evidence/perrier-omap-vp-stock-2026-11-13.md).
