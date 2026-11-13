# Stock OMAP4460 VC/VP snapshot (2026-11-13)

The owner authorized one temporary RAM-only run of the fixed 45,244-byte
`omap4_prm_power_read.arm` helper, SHA-256
`4579e0a1c39338f170d8fca2c08042f26584462f179cfc3e67af92f7751aa11d`.
It mapped the `0x4a307000` PRM page read-only and read 31 allowlisted words.
The host verified the uploaded hash, ran the helper once, removed it from
`/tmp`, and verified that stock Linux `3.4.113+`, Phoenix, and the boot ID
`88e2ac37-4f90-4cc9-9832-59a4b7e78031` were unchanged. There was no
reboot, PMIC write or persistent-storage write. The one-use authorization
is consumed.

The complete [raw register capture](../development/runs/20261113T122951Z-stock-prm-read-800d19/prm-raw.csv),
[decoded result](../development/runs/20261113T122951Z-stock-prm-read-800d19/prm-decoded.json),
and [run record](../development/runs/20261113T122951Z-stock-prm-read-800d19/result.json)
are saved locally. The OMAP4460 TRM identifies the fields and access types.
Selector-to-voltage arithmetic below uses the stock TWL6032 EPROM offset bit
read earlier; these register values are requests and limits, not direct rail
measurements.

| Domain | VC slave, voltage/command registers | Stock VC ON / RET | VP current selector at capture | VP max selector |
| --- | --- | --- | --- | --- |
| MPU | `0x12`, `0x55/0x56` | `0x29` ≈ 1.215 V / `0x05` ≈ 0.760 V | `0x17` ≈ 0.988 V | `0x37` ≈ 1.393 V |
| CORE | `0x12`, `0x5b/0x5c` | `0x23` ≈ 1.139 V / `0x05` ≈ 0.760 V | `0x15` ≈ 0.962 V | `0x2c` ≈ 1.253 V |
| IVA | `0x12`, `0x49/0x4a` | `0x36` ≈ 1.380 V / `0x05` ≈ 0.760 V | `0x2e` ≈ 1.279 V | `0x36` ≈ 1.380 V |

All three stock VP configurations have bit 0 (`VPENABLE`) set. The exact
registers are CORE `0x00172309`, MPU `0x00242909`, IVA `0x00283609`.
`PRM_VOLTCTRL` was `0x00000300`, and VC channel configuration `0x00001717`.
In the TRM's `PRM_VOLTCTRL` layout, `0x300` sets the separate MPU and IVA
rail-presence bits while leaving automatic SLEEP/RET transitions disabled
for all three domains at the time of the capture.
The current VP selectors differ by one step from the earlier five-word
capture; the stock system uses SmartReflex Class3, so a changing request is
expected. This observation alone does not quantify stability or prove a
particular SmartReflex algorithm.

A subsequent read-only INA3221 sample at I2C `4-0041` reported 992 mV on
channel 1 and 960 mV on channel 3 while the CPU remained at 700 MHz.
Those are close to the snapshot's MPU and CORE VP requests of 988 and
962 mV. The samples were not simultaneous and physical board traces were
not probed, but together with the previous CPU-load current response they
strengthen the channel 1 = MPU and channel 3 = CORE assignment. No IVA
sensor channel has been identified.

With this unit's measured TWL6032 offset bit and a successful PMIC read,
pristine Linux 6.18.48's OMAP4 VC table would write the same ON command
selector `0x36` for **all** domains, and RET `0x0c`, producing command word
`0x36360c00`. That differs from every stock command word: MPU `0x29290500`,
CORE `0x23230500`, and IVA `0x36360500`. Its IVA and CORE VP maxima are
1.260 and 1.200 V, below its 1.375 V ON target. The pristine VP init would
also write `0x00000008` to each VP config first, clearing the three stock
`VPENABLE` bits. These are software write-path comparisons; the late init
was not enabled on the panel, and no resulting rail change was tested.

Keep `omap2_common_pm_late_init` blacklisted. Fixing TWL6032 addresses alone
does not make its generic VC/VP initialization safe for this board.
