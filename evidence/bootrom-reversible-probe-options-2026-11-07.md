# Reversible ways to test the Touch 10 ROM TOC hypothesis

Scope: offline review of the exact CE9.9.0 MLO, the captured OMAP4460 ROM,
saved eMMC layout, earlier USB/serial trials, and Cisco's documented panel
connectors. No device command, reboot, storage change, or new probe was made.
The target question is whether a modified outer TOC destination word at
`+0x10` passes the **storage** path's pre-copy secure gate and reaches the
full MLO read at ROM `0x32b66`.

## Which routes exercise that exact question?

| Route | Reversible from the PC? | Tests the same storage gate and MMC read? | Evidence and limit |
| --- | --- | --- | --- |
| Stock boot from eMMC LBA 256 | Yes, with unmodified bytes | Yes, but TOC destination remains zero | Baseline boot only. The exact installed MLO is at the second raw MMC slot. |
| Edit eMMC MLO TOC `+0x10` at LBA 256 | **No demonstrated rescue if boot fails** | Yes | This is the only identified path that directly tests the candidate on this board. A failed pre-copy gate or stack crash could prevent U-Boot and root SSH from starting on every reset. |
| Place a candidate at raw slot 2 (LBA 512) or 3 (LBA 768) while leaving LBA 256 intact | The original MLO stays intact, but this still writes the first-stage partition | Not during normal boot | The ROM's slot order is 0, 256, 512, 768. It reaches slot 2/3 only after slot 1 fails or is skipped. No proven reversible slot selector can make it skip slot 1, so this does not test a candidate by itself. |
| Reconfigure eMMC boot0/boot1 or boot selection | No demonstrated rescue | Uncertain | Both boot-area backups lack the installed MLO. Changing eMMC boot configuration is persistent, and the current ROM source/partition behavior after such a change is unproven. |
| Feed the exact MLO over ROM USB or UART | RAM-only if accepted | No | The type-2 peripheral receiver at `0x33092` accepts at most 32,767 declared bytes. The exact signed MLO needs 41,024 bytes. Earlier host captures show rejection at 32,768 bytes and the unmodified MLO failing after the first sector. UART shares this generic peripheral image path. |
| Feed a compact signed PPA image with an edited outer TOC over ROM USB | RAM-only; a power cycle restores normal boot after a failure | **Proxy only** | The earlier 16,284-byte `2ND` image ran the exact signed PPA and ended at its fatal path without writing eMMC. An edited `+0x10` could test whether the *peripheral* service calls tolerate that field, but it does not take `0x32a74` or `0x33bba` and cannot establish storage-path acceptance. |
| Boot unsigned RAM Linux via U-Boot `bootz` and call ROM/SMC routines | The kernel boot itself is reversible | No faithful reset-time test established | The previously proven `bootz` route reaches U-Boot after the ROM has already authenticated and handed off its MLO. Security state, stack, and MMC initialization differ from the ROM boot phase. A later call would not establish what the reset-time storage gate accepts. |
| Software emulation of the captured public ROM | Yes, offline | Models only the visible code | It can test branch and copy arithmetic, already done in `stack_tail_model.py`, but cannot decide how the absent secure-side SMC handler treats the TOC. |

## Hardware access and recovery limits

[Cisco's Touch 10 physical-interface guide](https://www.cisco.com/c/dam/en/us/td/docs/telepresence/endpoint/roomos-1124/desk-room-board-administration-guide-roomos-1124.pdf)
lists a maintenance Micro-USB port and PoE Ethernet for the newer Touch 10;
it shows no user-accessible SD slot. The older version has additional USB
connectors labeled unused, not a documented ROM boot medium. The user does
not want to open this panel, so internal MMC wiring or hidden pads are
outside this plan. The panel's Ethernet service operates after Linux starts;
no ROM network boot path is established by the captured source table or prior
tests.

Cisco's [CE9.9 panel reset procedure](cisco-touch10-recovery-2026-11-07.md)
is a factory reset and pairing recovery after the panel boots. It is not
documented as an early-boot eMMC repair route. The existing root SSH and
U-Boot console are also unavailable if a modified first-stage MLO prevents
the ROM from reaching U-Boot. The PC holds full eMMC and EEPROM backups,
but a backup alone cannot restore a panel that no longer boots without a
working recovery transport.

## Practical conclusion

There is **no established, nonpersistent test of the exact storage-path TOC
gate** using this panel's accessible ports. A compact signed PPA upload is
the best RAM-only *proxy* for whether a TOC field is rejected in the common
secure-service sequence, with a limited interpretation. The exact MMC
candidate should remain an offline finding until secure-side handler
behavior is recovered or a genuinely independent first-stage recovery path
is demonstrated. U-Boot `bootz` remains the already proven reversible route
for the user's firmware rewrite, though it does not answer the ROM exploit
question.

## Addendum: independent recovery after a broken first stage

The [OMAP4460 TRM, chapter 27](https://www.ti.com/lit/ug/swpu235aa/swpu235aa.pdf)
documents boot-device order, ROM boot sequence, and USB/UART peripheral boot.
TI's [OMAP4460 silicon erratum i739](https://www.ti.com/pdfs/wtbu/OMAP4460_ES1.x_Silicon_Errata_Rev_H.pdf)
explicitly describes the ROM moving to the next configured device when
MMC1 initialization fails. These are **chip capabilities**, not a Touch 10
recovery procedure or proof that a failed authenticated image takes the same
fallback branch. The saved logs do not record this board's SYS_BOOT latch.

There is stronger **board-specific** evidence for an early USB transport:
on repeated cold power cycles, the Touch 10 enumerated as TI ROM USB
`0451:d010`, accepted ROM BOOT/length requests, disconnected, and then
printed the normal Cisco MLO and U-Boot banners. The
[timestamped EHCI comparison](rom-ehci-format-timing-2026-11-07.txt)
records this order even when the host's MLO upload failed. The accessible
service USB port therefore exposes the ROM before the successful installed
first stage runs. It is reasonable to expect the same enumeration after a
bad LBA 256 image on a **cold** reset, but that exact broken-image condition
has not been tested. The USB transport is not yet a recovery *loader*: the
known peripheral receiver rejects the full 41,024-byte MLO above 32,767
bytes, and the compact signed PPA trial ended at its fatal path rather than
providing eMMC write access.

The captured ROM's boot chooser at `0x30a7c` loops over an eight-entry
source list, calling storage `0x32dea` or peripheral `0x33092` according
to each source code. The storage loader returns to the chooser at `0x32f6a`
after ordinary image-not-found errors, so a blank or unrecognized eMMC
can fall through to later configured boot sources. Its raw MMC reader can
advance among LBAs 0, 256, 512, and 768 when an attempt returns. This does
**not** make slot 2 or 3
a dependable rescue for the TOC experiment: on a failed secure-service-2
check, `0x34562` passes address `0x300a8` to `0x300c0`, which branches
to the infinite loop at `0x300a8`. A copy into the ROM stack can likewise
prevent normal error return. Thus a later raw slot is only useful for
failure modes that return to the chooser; the proposed exploit's failures
need not do so.

Result: the panel has a demonstrated early ROM **USB connection**, but no
demonstrated independent way to restore eMMC from it after a broken MLO.
Cold-reset USB enumeration and authenticated recovery execution are
separate milestones. The current primary-slot experiment still lacks a
proven rescue path.

TI also published a [Flash v1.6 guide](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/791/Flash-v1.6-User-Guide-_2D00_-Texas-Instruments-Wiki.pdf)
that lists OMAP4 HS USB/UART `dnld_startup_omap4_hs_{2g,4g,8g}.2nd`
loaders. Its flow reads the ROM ASIC ID, uploads a second loader, applies
board configuration, then downloads a separate memory driver. The guide's
documented destinations are NAND and SDRAM; it does not establish eMMC
programming on this panel. These generic HS loaders also have not been
checked against this unit's burned root-key hash or DDR layout. Their
existence strengthens the USB recovery lead but is not yet a tested rescue.
