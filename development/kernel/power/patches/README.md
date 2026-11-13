# TWL6032 voltage-controller address candidate

`0001-omap4-twl6032-vc-addresses.patch` is an isolated Linux 6.18.48 source
patch against `arch/arm/mach-omap2/omap_twl.c`. It leaves the existing
TWL6030 register map intact and selects the TWL6032 map only when an
available `ti,twl6032` DT node exists. The MPU address pair stays `55/56`;
CORE becomes `5b/5c`, and IVA becomes `49/4a` on VC slave `0x12`.

The [review record](review.json) hashes the pristine source, exact patch and
patched source. Applying it in an isolated temporary tree reproduced the
reviewed patched hash. The patched source also compiled to an ARM object
with ram110's frozen kernel configuration. It has **not** been added to the
canonical patch series, linked into a bootable kernel, or run on the Touch 10. The validated ram110
image still blacklists `omap2_common_pm_late_init`, so no Linux VC/VP init
or voltage transition is enabled.

The mapping is supported by Cisco's exact MLO and stock kernel, and by
TI's OMAP4 U-Boot [SMPS address definitions](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/include/asm/arch-omap4/clock.h?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8)
and [TWL6032 rail assignment](https://git.ti.com/cgit/ti-u-boot/ti-u-boot/tree/arch/arm/mach-omap2/omap4/hw_data.c?id=e79de74103d9d411aa6b4e63582c5d7075c6a7a8).
This establishes the address map, not safe activation of the whole OMAP PM
late-init sequence. The [write audit](../pm-late-init-audit.md) found that
mainline would replace stock's 1.215 V MPU ON command with a generic
1.375 V target and clear the stock VP enable bit during init. The sequence
also changes powerdomains, clockdomains and idle behavior. The later
[stock VC/VP capture](../../../../evidence/perrier-omap-prm-power-stock-2026-11-13.md)
confirmed the three Cisco address pairs, distinct ON commands and enabled
VPs. Review each mainline write and implement a guarded board policy before
any RAM image removes the blacklist. Keep CPUfreq off throughout that work.
