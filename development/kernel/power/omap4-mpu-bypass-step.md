# Perrier MPU VC bypass transport trial

This is one bounded hardware test under the owner's 2026-11-13 approval for
CPU hardware tests. It uses the already validated ram113 kernel at **fixed
700 MHz** with both CPUs online, `CONFIG_HOTPLUG_CPU=n`, and the nowayout
watchdog. It neither changes the CPU clock nor installs a persistent voltage
policy.

The OMAP4460 TRM lists `PRM_VC_VAL_BYPASS` at `0x4a307ba0`. Its `VALID` bit
clears on acknowledge **or error**. `PRM_IRQSTATUS_MPU_A9` at `0x4a306010`
reports bypass acknowledge on bit 14 and VC timeout/address errors on bits
13–11. Cisco's CE9.9.0 MLO uses the same bypass register, slave `0x12`,
SMPS1 voltage register `0x55`, and selector `0x28` at boot. The ram113 PRM
snapshot records the subsequent MPU ON and VP selector as `0x29` with VP
disabled and an INA rail near 1.208 V. A selector decrement is nominally
12.66 mV; it is far smaller than the stock kernel's adaptive voltage
difference, but still requires actual rail and recovery checks.

The [fixed ARM helper](omap4_mpu_bypass_step.c) has no input arguments. Before
mapping MMIO it checks ram113 identity, both CPUs online, 700 MHz performance
governor, temperature below 70 °C, read-only eMMC and the INA3221 channel.
It maps only `0x4a306000..0x4a307fff` and requires the exact captured VC/VP
configuration, no pending bypass, and no VC error. It then:

1. Sends selector `0x29` to the same SMPS1 register to prove the transport,
   requiring an acknowledge with no error and a stable INA reading.
2. Sends one downward step to `0x28`; waits 0.5 seconds; records the INA
   voltage and CPU temperature at 700 MHz.
3. Sends `0x29` again; waits 0.5 seconds; verifies the INA voltage returns
   near the initial reading. It attempts restoration even if the lower
   command or rail check fails, provided no VC command remains pending.

Each command polls for `VALID=0` for at most 100 ms, then requires the
separate acknowledge bit and no VC error. The helper clears only the four
W1C bypass status bits before a command. The host byte-verifies the uploaded
binary in RAM-only `/tmp`, captures all output, removes the helper, requests
normal stock reboot, and verifies the factory boot environment and ADC
postflight. A bus fault or stuck command may require watchdog recovery;
the fixed MLO boot path requests selector `0x28` before Linux returns.

This proves only a small reversible transport operation. It does not yet
qualify a 350/700 MHz voltage table, implement `cpu-supply`, or establish
long-duration undervolt stability. The mainline `omap_vc_bypass_scale()`
completion loop checks `VALID` in the opposite direction from the TRM and
MLO, so that function must be corrected or bypassed in a future provider.

## Observed 2026-11-13 results

The [first RAM run](../../runs/20261113T155643Z-ram113-mpu-vc-step/result.json)
at 700 MHz reported `0x4100` after every bypass command: bit 14 ACK, bit 8
an unrelated transition event, and no VC error bits. The rail read 1.216 V
at `0x29`, 1.200 V at `0x28`, and 1.216 V restored. CPU temperature stayed
below 59 °C. The [second run under two-core load](../../runs/20261113T160032Z-ram113-mpu-vc-step/result.json)
reported the same ACK/error status and rail readings of 1.216, 1.208, and
1.216 V. Temperature stayed below 63 °C. INA voltage is quantized in 8 mV
steps; these measurements show the expected direction and restoration, but
do not calibrate the absolute PMIC output more precisely.

Both [first](../../runs/20261113T155524Z-uboot-ram113-99c94f/result.json)
and [loaded](../../runs/20261113T155918Z-uboot-ram113-258b20/result.json)
one-shot runners returned to stock Linux 3.4 with Phoenix running, the
factory p8 hash intact, and ADC postflight passed. The temporary ARM helper
was removed from tmpfs before recovery. No display reset cycle was run.
