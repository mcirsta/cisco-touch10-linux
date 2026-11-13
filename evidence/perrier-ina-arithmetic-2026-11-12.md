# Stock INA3221 response to bounded CPU arithmetic

The stock panel was running Linux `3.4.113+` at 700 MHz. No clock,
voltage, PMIC, display or storage setting was changed. A shell arithmetic
worker ran for a fixed 1.5 million iterations, first once and then as two
concurrent workers. Sixteen readings of all six INA3221 channels were taken
in each idle and loaded phase. The raw capture is
[`perrier-ina-arithmetic-2026-11-12.csv`](perrier-ina-arithmetic-2026-11-12.csv).
All 80 samples reported `scaling_cur_freq=700000` kHz.
The final SSH postcheck still found stock Linux `3.4.113+`, CPU0 at
700 MHz, and the `phoenix` application running.

The table compares each loaded phase with the mean of its two adjacent idle
phases. Values are changes in measured current, in mA; samples are serially
correlated, so these are effect sizes, not independent statistical trials.

| Monitor/channel | One worker | Two workers |
| --- | ---: | ---: |
| I2C4 `0x40`, channel 1 (1.832 V) | +1 | +4 |
| I2C4 `0x40`, channel 2 (3.304 V) | +0 | +1 |
| I2C4 `0x40`, channel 3 (5.032 V) | +15 | +37 |
| I2C4 `0x41`, channel 1 (0.992 V) | **+120** | **+190** |
| I2C4 `0x41`, channel 2 (1.216 V) | −46 | −42 |
| I2C4 `0x41`, channel 3 (about 0.960 V) | +51 | +2 |

The `0x41` channel 1 response is repeatable across this test and the
earlier gzip tests. Two workers produce a larger response than one. This
is evidence that the channel supplies a CPU-load-dependent circuit, but
the workload still uses memory and OMAP interconnects. It does not alone
distinguish direct VDD_MPU from CORE. Channel 2's voltage closely matches
the stock 700 MHz MPU OPP target of 1.203 V, yet its measured current did
not rise under this workload. **The INA channel-to-rail mapping is therefore
unresolved; voltage resemblance must not be treated as confirmation.**

The exact stock board I2C table at `0xc074dbb0` and `0xc074dbd8` registers
the two INA3221 clients at `0x40` and `0x41`, without per-channel labels or
platform-data pointers. Stock sysfs likewise exposes no channel labels and
no VCORE1 regulator attribute. The three stock SmartReflex sysfs devices
also expose no voltage value; stock `dmesg` reports SmartReflex Class3
initialized, so nominal OPP voltage cannot simply be assumed to equal
the monitored rail voltage. A direct read of the documented OMAP
`PRM_VC_VAL_BYPASS` register through stock `/dev/mem` returned `Bad
address`; it yielded no value and changed no setting. At the time of this
capture, the next proposed check was a fixed-register PMIC read, and a
ram111 regulator observer had been prepared offline. No helper or ram111
artifact was transferred during this capture.

**Update, 2026-11-13:** The authorized control-I2C read returned zero at
the voltage offsets, so ram111 was retired before device use. A separate
[stock OMAP VP snapshot](perrier-omap-vp-stock-2026-11-13.md) then found
MPU and CORE programmed selectors corresponding to 1.00018 and
0.97486 V, closely matching INA channels 1 and 3. Combined with this
arithmetic load response, that is strong software evidence for those
monitor assignments, still short of a measured PCB connection.
