# OMAP4460 ROM storage path: what the visible secure gate can see

Scope: offline analysis of the captured Touch 10 ROM, the exact CE9.9.0 MLO,
and the signed PPA. No panel command or storage change was made. ROM addresses
below use the low alias; the PPA is loaded at its `0x4030xxxx` address.

## Visible call sequence

The storage loader at `0x32a74` initially reads the `KEYS` section (5
sectors), `PRIMAPP` (26 sectors), and one sector of the selected `MLO`
section. At `0x32aee`-`0x32af0` it overrides the selected first-read count
to one, so this phase fits in the 32 KiB SRAM window. Its call at `0x32b38`
passes four section payload pointers to `0x344fa`: key in R0, primary
application in R1, optional R&D in R2, and selected-image header in R3.
For this MLO, R&D is absent.

In `0x344fa`, the selected-image header pointer is used at `0x3451a` for
the pre-verification configuration interpreter at header offset `+0xa4`.
The secure-service calls at `0x3452c`, `0x3453a` (optional), and `0x3454e`
receive the key, R&D, and primary-application pointers respectively. The
service-2 result controls the fatal branch at `0x34552` and the status bit
set at `0x34554`-`0x3455a`.

The wrappers at `0x30f24`, `0x30f36`, and `0x30f48` supply service selectors
0, 1, and 2 to `0x30f04`/`0x37594`, which enters `SMC #1` at `0x375b0`.
Each wrapper places a one-element section-pointer descriptor on the stack.
None explicitly passes the outer TOC base or its destination word `+0x10`
as a service argument. After the gate, `0x32b40`-`0x32b66` uses the full
selected-image sector count and the TOC-derived destination in a storage
read. Only after that read does `0x32b7e` call `0x344dc`/`0x30f5a`, which
uses secure-service selector 3 on the loaded selected image.

## Authentication coverage and limits of the evidence

`analysis/bootrom/verify_mlo_chain.py` verifies the exact MLO's root key,
three RSA/SHA-256 certificate signatures, and PPA/ISW body hashes. An
in-memory change to TOC `+0x10` and the final sector tail preserves all of
those checks. This establishes that the edited bytes are outside the
cryptographic regions checked by that script. It does **not** establish
that the secure monitor accepts the edited TOC.

The `SMC #1` handler is not in this 48 KiB nonsecure ROM capture. The caller
retains the TOC pointer in callee-saved R11 while the explicit service
arguments are prepared; the secure handler could inspect that register,
the nonsecure stack, or shared state even though the visible wrapper does
not pass a TOC parameter. The PPA binary has direct references to the
handoff pointers at `0x402100` and `0x402104`, whose contents are outside
this extracted PPA. A scan found no direct fixed-address reference from
the PPA to the ROM storage loader's TOC stack area, but dynamic access
through those handoff pointers remains possible.

An earlier RAM-only USB test used a compact image with exact signed
`PRIMAPP` and root-key bytes but an altered outer TOC (`2ND` in place of
the installed `MLO` record). The panel printed the PPA banner and reached
a later fatal path; see `ppa-memory-audit-2026-11-07.md` and
`rom-exact-ppa-2nd-20261107T013700Z-serial.log`. This shows that at least
one outer-TOC edit did not prevent the *peripheral* path from running the
signed PPA. It does not test the storage-path destination word `+0x10`.

A later [pass/stall USB comparison](bootrom-speedup-poll-2026-11-07/README.md)
also kept the signed KEYS/PPA region exact while changing the outer `2ND`
start to zero and adding an unsigned speedup table. Its pass variant reached
the PPA banner; a one-bit-different equality-poll variant did not. This
strengthens the evidence that the peripheral path acts on unsigned outer
metadata before the visible secure-service sequence. It still does not
exercise the storage-path destination word or reveal the secure monitor's
TOC policy.

**Assessment:** the visible ABI and certificate layout support a TOC-only
edit passing the pre-copy gate; they do not prove it. The secure-side
handler is the main unresolved check. The separate MMC source-path audit
strongly supports the read callback used in the stack-overwrite model.
