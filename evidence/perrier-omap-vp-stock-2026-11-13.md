# Stock OMAP voltage-processor read (2026-11-13)

## One authorized RAM-only run

The owner authorized one upload, execution and removal of the fixed
[read-only mapping helper](../development/kernel/diagnostics/omap4-vp-stock-read.md).
Stock Linux was `3.4.113+` at 700 MHz before the run. The exact 45,244-byte
ELF had SHA-256
`89a70e67a569fac941be6dffe44ed3a014d9b30c2a4a198d36ade235891b9c00`;
its SHA-512 was verified on the panel before execution. It was executed
once and removed from `/tmp`. Stock Linux remained `3.4.113+` at 700 MHz.
No device register, persistent storage, boot setting or firmware was
written; there was no reboot.

```text
vp_core_voltage,0x4a307b4c,0x00011116
vp_mpu_config,0x4a307b58,0x00242909
vp_mpu_voltage,0x4a307b64,0x00011118
vp_iva_voltage,0x4a307b7c,0x0001112d
vc_mpu_command,0x4a307b98,0x29290500
```

The OMAP4460 TRM defines the voltage registers' low byte as the *current
selector requested by the voltage processor*, not a direct voltmeter.
`vp_mpu_config` has `VPENABLE=1` and `INITVOLTAGE=0x29`.
`vc_mpu_command` has `ON=0x29`, `ONLP=0x29`, `RET=0x05`, `OFF=0x00`.
The current MPU VP selector `0x18` therefore differs from the initial/ON
command `0x29`; those values describe different roles.

The earlier [control-I2C read](perrier-smps-selector-stock-2026-11-13.md)
returned offset EPROM `0x5b`; bit 3 selects the stock kernel's conversion
`709000 + (selector - 1) × 12660` microvolts. The saved stock kernel's
`twl6030_vsel_to_uv` at `0xc00234f4` uses that conversion. Its
`omap_vp_get_curr_volt` at `0xc002aa50` reads the VP selector through
the voltage-domain callback and converts it with the PMIC callback.

| Domain/command | Selector | Converted programmed level |
| --- | ---: | ---: |
| MPU VP current request | `0x18` | 1,000,180 µV |
| CORE VP current request | `0x16` | 974,860 µV |
| IVA VP current request | `0x2d` | 1,266,040 µV |
| MPU initial/ON command | `0x29` | 1,215,400 µV |

The later stock INA3221 `4-0041` snapshot was 1000, 1216 and 976 mV
on channels 1–3, with currents 448, 292 and 548 mA. Channel 1 differs
from the MPU VP request by only 0.18 mV, and channel 3 differs from CORE
by 1.14 mV. This strongly supports channel 1 as the monitored MPU rail
and channel 3 as CORE. The earlier
[fixed-frequency arithmetic test](perrier-ina-arithmetic-2026-11-12.md)
also found that channel 1 current rose substantially with CPU work.
These are multiple independent software observations, but no physical net
or package voltage has been measured. The 1216 mV channel resembles the
configured MPU ON command, yet its role is unresolved; the configured ON
value is not the same thing as the current VP request.

The stock config has `CONFIG_OMAP_SMARTREFLEX=y` and
`CONFIG_OMAP_SMARTREFLEX_CLASS3=y`. Stock boot logs show three SmartReflex
devices and Class3 initialization. Combined with `VPENABLE=1`, this is
consistent with active voltage adaptation explaining why the current VP
selector is below the initial/ON command. This is an inference; the
single snapshot does not prove the exact cause of the difference.

## Existing ram110 cross-boot evidence

An offline review of the already saved
[ram110 peripheral log](../development/runs/20261112T183007Z-uboot-ram110-0b1bed/extended-peripherals.log)
found the low-voltage INA channels at 1208, 1216 and 1128 mV. That RAM
kernel's command line explicitly blacklists
`omap2_common_pm_late_init`, and its config has power AVS and CPUfreq off.
The exact Cisco MLO programs SMPS1/VCORE1 selector `0x28` (1202.74 mV)
and SMPS2/VCORE2 selector `0x22` (1126.78 mV) before this kernel boots.

| INA channel | Stock SmartReflex boot | ram110 fixed-power boot | Source values aligned with each reading |
| --- | ---: | ---: | --- |
| 1 | 1000 mV | 1208 mV | MPU VP `0x18` = 1000.18 mV; MLO SMPS1 `0x28` = 1202.74 mV |
| 2 | 1216 mV | 1216 mV | No matching changing selector established |
| 3 | 976 mV | 1128 mV | CORE VP `0x16` = 974.86 mV; MLO SMPS2 `0x22` = 1126.78 mV |

The two independently changing channels follow their respective stock VP
requests and MLO settings across different boot paths. This, plus the
fixed-frequency CPU current response on channel 1, gives **high confidence
that channel 1 monitors MPU and channel 3 monitors CORE**. A direct probe
or board netlist would still be needed to call the PCB connection
electrically proven. Channel 2 remains unidentified.

The ram110 boot uses MLO's higher fixed MPU/CORE settings. Any enablement
of SmartReflex or CPUfreq in the new kernel requires a separate guarded
review and device authorization; the validated kernel does not yet
implement stock adaptive voltage behavior.

An offline comparison also found that pristine Linux 6.18.48 maps the
OMAP4 CORE and IVA voltage-controller commands to `0x61/0x62` and
`0x5b/0x5c`, respectively, whereas Cisco stock uses `0x5b/0x5c` and
`0x49/0x4a`. The current RAM image blacklists the PM late init that would
program those mappings. See the [power policy](../development/kernel/power-policy.md)
before enabling any mainline voltage initialization.
