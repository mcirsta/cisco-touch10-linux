# Cortex-A9 general PMU counters on Touch 10

The OMAP4460 Cortex-A9 PMU is present and its cycle counter and overflow IRQ
work in Linux 6.18.48. Its six programmable event counters do not count on this
unit. The stock Linux 3.4.113+ kernel shows the same behavior.

## Evidence

* The stock kernel's PMU read, write, enable, start and reset routines are
  preserved in `out/pmu-fix/stock-pmu-*.asm` and `.c`. They select and enable
  programmable counters through the normal CP15 interface. They do not set
  SDER. The stock `perf` workload counts cycles but no instructions.
* Ram100 used the unmodified mainline Cortex-A9 PMU driver, correct IRQ and
  debug-subsystem DT nodes, and unrestricted perf event attributes. Its cycle
  counter generated 50 overflow samples with no losses. Instruction count
  and nine raw events, including Cortex-A9's instruction event `0x68`, all
  returned zero. See `validation-ram100.json` and its run directory.
* Ram101 read the CPU debug-authentication status with a narrowly scoped,
  fault-handled CP14 instruction. It returned **0x000000aa**. A guarded SDER
  read trapped, showing that this Linux boot is in the Non-secure state. The
  runtime PM test held the mainline debug-subsystem parent active and its
  clock enabled; the same ten general events remained zero. See
  `../runs/20261112T123410Z-uboot-ram101-c54db3/diagnostics-pmu-probe-*.log`
  and `out/pmu-fix/ram101-runtime-pm.log`.
* Ram102 directly selected event `0x68` in an unused counter, read the event
  selection back as `0x68`, ran a fixed instruction loop, then tried 100
  software increments with event `0x00`. Both counter reads were zero. It
  restored the prior PMU state before userspace started. A subsequent `perf`
  run again counted cycles and 50 overflow samples while all general events
  stayed zero. See
  `../runs/20261112T124954Z-uboot-ram102-d8fc19/diagnostics-pmu-selftest-checks.json`.

The [ARMv7-A architecture manual, sections C11.11.1 and C12.1.7](https://documentation-service.arm.com/static/5f8daeb7f86e16515cdb8c4e)
defines DBGAUTHSTATUS bits 7, 5, 3 and 1 as *implemented*, and bits 6, 4, 2
and 0 as *enabled*. Thus `0xaa` reports all four classes of debug implemented
but disabled. Bit 2 specifically says **Non-secure non-invasive debug is
disabled**. Table C12-1 specifies that event counters do not count when
non-invasive debug is forbidden, while the cycle counter may continue if
`PMCR.DP=0`; that is precisely the observed pattern. The
[Cortex-A9 technical reference manual, section 10.8.2](https://documentation-service.arm.com/static/5f0377b2cafe527e86f5c247)
calls performance counting a non-invasive debug feature. The
[OMAP4460 technical reference manual, section 28.6.1](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf)
confirms six programmable counters and PMU interrupts.

The immediate cause is the debug-authentication state delivered to the CPU.
Neither kernel's event selection nor the OMAP debug clock explains these
zero counts. The `secure-reg-access` DT property cannot be used for this boot:
the SDER read trapped in Non-secure Linux, and the property would make the
mainline PMU driver access that Secure-only register. A normal Non-secure
kernel has no architectural way to assert the DBGEN/NIDEN authentication
inputs. We have not established whether they are tied off by hardware or set
by earlier Secure firmware; that distinction needs a separately scoped
early-boot investigation. No debug-authentication, fuse, or Secure Monitor
configuration was changed in these trials.

Ram100 remains the qualified default and ram99 the fallback. The two PMU
diagnostic images are preserved as snapshots in `baselines/ram101` and
`baselines/ram102`, with [ram101](validation-ram101.json) and
[ram102](validation-ram102.json) recorded as **not promoted**. Both used the
one-shot U-Boot RAM path. Ram102 returned to stock through the hardware
watchdog in 151.8 seconds; the factory p8 hash matched its saved value.
The owner-approved ADC postflight restored the three sensing controls, and
stock checks passed for ADC trim, audio and all 65 sampled PMIC supply
fields. Display and Qt were not cycled in either diagnostic run. Exact copies
of the temporary staged images are archived on the host; their p14 copies
were removed after stock recovery, leaving ram99 and ram100 staged.
