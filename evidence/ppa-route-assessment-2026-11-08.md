# Signed PPA routes on this Touch 10

Offline assessment of the exact CE9.9.0 files and the saved 48 KiB OMAP4460
ROM capture. No new device command, upload, or storage change was made for
this assessment.

## Boot USB route

The earlier 16,284-byte `2ND` upload contains byte-identical KEYS and
Primary Protected Application (PPA) data from the panel's signed MLO. Its
pass variant printed the PPA 1.8.5 banner; the one-bit stall variant did not
print it during a 120-second capture. This establishes a pre-verification
effect of the unsigned speedup table and execution of the signed PPA in the
pass run. It does not establish execution of the signed Cisco ISW or unsigned
code. See [the live differential](bootrom-speedup-poll-2026-11-07/README.md).

The smallest contiguous USB image containing a 0x200-byte TOC, the 0x960-byte
KEYS section, the 0x339c-byte PPA section, and the 0x6040-byte Cisco ISW
section is 0x9f3c = 40,764 bytes. The observed ROM type-2 USB BOOT limit is
32,767 bytes. The ROM USB path receives one image and scans its in-memory
TOC; no second upload or fetch of the missing ISW from eMMC was found in the
visible path. The PPA fatal message is consistent with this incomplete chain,
but its exact cause has not been observed. See the
[USB state-machine audit](bootrom-usb-state-machine-2026-11-07.md) and
[secure-gate trace](bootrom-secure-gate-2026-11-07.md).

The unsigned outer TOC can select section pointers and has a demonstrated
pre-verification speedup-table effect. No dataflow from that TOC to a useful
PPA service argument has been established. PPA startup constructs its own
descriptor rather than receiving an observed TOC pointer; changing the
selected TOC start and size left the PPA free-space numbers unchanged. See
[the service trace](bootrom-ppa-services-2026-11-07.md) and
[memory audit](ppa-memory-audit-2026-11-07.md).

### Why the compact USB image ends at the fatal banner

The visible USB route calls `0x32fd6` from `0x332b6`, then reaches the
non-type-3 selection logic at `0x346ec`. Its `2ND` branch at `0x34572`
requires a selected item, `KEYS`, and `PRIMAPP` (`0x34586..0x34596`). It
passes the key and PPA section pointers to `0x344fa`, whose secure selectors
0 and 2 run after the unsigned speedup table. Once that gate returns
successfully, `0x34614..0x34618` calls `0x344dc`, which invokes secure
selector **3** (`0x30f5a`) with the selected item's pointer and boot context.
The tested compact image has its `2ND` item at offset zero with size `0x200`:
that pointer addresses the **unsigned outer TOC**, not a signed Cisco ISW or
`CertISW` section. A selector-3 rejection of that item is therefore the
strongest explanation for the later fatal message. The exact failure branch
is inside the unavailable secure `SMC #1` handler, so the cause is an
inference, not a directly observed result.

The text `FATAL ERROR` comes from PPA function `0x403017f4`. At
`0x40301880..0x4030188a`, the PPA installs that function as the `+8`
callback in a table obtained through `[0x00402104]`; the function has no
direct call reference in the extracted PPA. The banner therefore does not
identify a PPA memory bug or prove that the PPA itself rejected its own
startup. A normal boot prints the same 2172/2252 free-space values and then
the Cisco MLO banner, while the compact image prints those values and then
the fatal banner. Altering the unsigned selected start/size in earlier live
comparisons left the free-space values identical. No concrete path from
those editable fields to the PPA cleanup endpoints or another PPA service
argument has been established.

## Runtime PPA services in the exact signed image

Addresses below are PPA load addresses. These are candidate defects, not
demonstrated exploits:

| ID | Code path | Observation | Missing proof |
| --- | --- | --- | --- |
| `0x2c` | Table `0x40300e94` to handler `0x4030131c` | At `0x40301348`, the first marshalled handler argument indexes two initialized eight-byte stack records via `SP + (index << 3)` without a visible range check. Index 2 reads saved R4/LR; index 3 or more can read the caller's stack. The read bytes feed writes to fixed addresses `0x6f1e0038` and `0x6f1e0034`. | No existing ISW or U-Boot call, no normal-world caller proven to supply an arbitrary index, no returned stack bytes or arbitrary write address. The fixed target's peripheral meaning is unresolved. |
| `0x2f` | Table `0x40300eac` to `0x40303068` | Translates a caller pointer through external service `0x88` and writes a fixed 34-byte result; no local span check is visible. | Semantics of service `0x88`, boundary behavior, and caller reachability. |
| `0x3e` | `0x4030309c` | Hash service accepts a descriptor with input pointer/length and output pointer. The exact signed ISW and U-Boot invoke it after certificate verification. | Their observed descriptor offset and length come from each image's signed certificate prefix, so unsigned USB TOC control of this call has not been found. External translation and hash-service range checks remain unavailable. |

The exact signed ISW and U-Boot visibly call PPA IDs `0x0c` and `0x3e`, not
`0x2c`. For ISW, certificate fields at `[R4+0x34]` and `[R4+0x38]` define
the region hashed by `0x3e`; the exact CertISW has `(0x350, 0x5cf0)` in its
signed prefix. U-Boot uses the same pattern with `(0x350, 0x3312c)` in its
own signed prefix. The visible normal boot call sites therefore do not make
`0x2c` or the `0x3e` length attacker-controlled.

Public [TI OMAP secure-dispatcher code](https://git.ti.com/cgit/ti-linux-kernel/ti-linux-kernel/tree/arch/arm/mach-omap2/omap-secure.c?id=f7901365aa48b20b25f8402e0fd1eea4ac6c55e7)
and [its header](https://git.ti.com/cgit/ti-linux-kernel/ti-linux-kernel/tree/arch/arm/mach-omap2/omap-secure.h?id=f7901365aa48b20b25f8402e0fd1eea4ac6c55e7)
show that some OMAP4 PPA IDs are callable from kernel context via a marshalled
SMC descriptor. The saved kernel has an `omap_secure_dispatcher` symbol in
kallsyms, but a module export has **not** been established, nor has a userland
API for arbitrary PPA IDs. Whether this panel's monitor accepts ID `0x2c`
after Linux boot is unknown. A future controlled call needs both an identified
kernel-context mechanism and the exact selector/argument marshalling; setting
an SMC selector register alone is insufficient.

## Separate Linux-loaded secure application

`/etc/firmware/smc_pa.ift` is a 146,020-byte `CertPAS` container with SHA-256
`2ca0e75f0d152b6aad0606ac18341a6ef08e2fb9435ed5408f4eb38e134ad2af`.
The live file hash matches the package. `/etc/init.d/S30smc` loads it after
Linux starts using `/extra/bin/smc_pa_ctrl` and `/dev/tf_ctrl`, then runs
`tf_daemon`. This is **distinct** from the early boot PPA. The TEE interface
also exposes `/dev/tf_driver` and root-only management commands in `tfctrl`.
It supplies another secure-world parser and service surface, but no bypass or
arbitrary secure-world execution has been shown. See
[`S30smc`](../firmware/codec-ce9.9.0/apps-unpacked/etc/init.d/S30smc).

## Next useful investigation

1. Trace the exact monitor's marshalling and access checks for runtime PPA
   service `0x2c`, including whether a normal-world caller can choose its
   first handler argument. Keep any new live call separate from the USB boot
   experiment.
2. Resolve external PPA translation services `0x83`/`0x88` before treating
   `0x2f`/`0x3e` as memory-boundary vulnerabilities.
3. Map the saved kernel's TrustZone driver ABI and the separate `CertPAS`
   parser offline before considering a bounded runtime test. A runtime TEE
   service bug would not automatically bypass ROM authentication on a cold
   boot.
