# Adversarial check of the OMAP4460 ROM MMC stack-overwrite candidate

Scope: exact Touch 10 ROM at low alias `0x30000..0x3bfff`, exact CE9.9.0
MLO, and saved eMMC user-area image. All checks were offline. No panel
command or storage change was made.

## Branches into the read

`0x308d0` resets SP to `0x4030d000` immediately before entering main at
`0x30a18`; the intervening `0x308c4` call has returned. Main calls
`0x30a7c` at `0x30a6a`. The chooser calls the storage loader `0x32dea`
directly at `0x30b66`, so there is no uncounted active frame between those
two routines. `0x32f40` calls the nonzero-name section loader `0x32a74`.
For the exact TOC, the recognized MLO name is index 4 and its record is
ordinal 0, making that nonzero-name branch applicable.

The storage loader initializes boot-context word `+8` to zero at
`0x32e3a`. The raw MMC open path `0x33af4..0x33bb8` does not write it.
The per-slot selector updated by `0x36cea` is in the *separate card
context* at `+0x0c`. The two skip checks at `0x32aca` and `0x32b3c`
therefore have no visible raw-MMC reason to bypass the initial and full
reads. The per-attempt section-sector offset at storage-loader stack
`var_18` resets to zero at `0x32e82` after each raw-slot open. Thus a
second-slot attempt adds LBA 256 in the MMC callback and still uses the
MLO record's start sector 32; it does not accidentally start at sector 33.

`0x32a18` copies the selected TOC record's word `+0x10` into descriptor
word `+0x10` through `0x344ac`. For the fourth descriptor in `0x32a74`,
that is stack `var_18`. The full read loads it at `0x32b48`, passes its
address to clamp `0x34380` at `0x32b4e`, and passes the resulting
destination through stack `var_4` to the source read callback at
`0x32b66`. No local destination validation intervenes.

The initial first-pass read uses the distinct fixed SRAM pointer at
`0x40304000`. At `0x32aee..0x32af0`, the fourth (selected) descriptor's
transfer count is replaced by one sector only for this first pass. The
exact TOC contributes KEYS 5, PRIMAPP 26, optional R&D 0, and MLO header
1 sector, totaling 32 sectors/16 KiB. The check at `0x32af8` permits it.
The original selected descriptor still holds 49 sectors, loaded at
`0x32b40` for the later full read.

## Clamp, callback, and stack

For aligned TOC destination `0x40306c00`, `0x34380` classifies the address
inside the SRAM window but computes maximum length as
`0x4030bfff - 0x40304000 + 1 = 0x8000`, irrespective of the requested
destination. The selected read is `49*512 = 0x6200`, so address and length
remain unchanged. It extends to `0x4030cdff`, 3,584 bytes past that
window's upper bound.

Sources 5–7 share read callback `0x33bba`. In raw mode it calculates
physical sector `section_sector + (slot << 8) + loop_sector` at
`0x33c16..0x33c22`, then calls `0x36c62` at `0x33c52`. That routine
passes the descriptor's destination to `0x35f30`. The MMC initialization
at `0x35d9e` writes block length `0x200`; `0x35f3c` reads it, and the
FIFO loop at `0x35f6a..0x35f7c` stores 128 words through `[R1],#4`.
There is no visible destination recheck. The only other visible `#0x204`
register store (`0x362e2`) targets a different `0x48241000` controller,
not this MMC block-length register.

The active frame depths on the direct call chain are 16, 64, 608, 168,
48, 32, and 20 bytes respectively (`0x30a18`, `0x30a7c`, `0x32dea`,
`0x32a74`, `0x33bba`, `0x36c62`, `0x35f30`). They put FIFO-copy SP at
`0x4030cc44`. Its `PUSH {R4-R7,LR}` saves LR at `0x4030cc54`, and its
`POP {R4-R7,PC}` consumes that same word. For the chosen destination,
that word lies 84 bytes into final sector 48, at MLO-relative offset
`0xa054` and eMMC offset `0x2a054`. The signed ISW body ends at MLO
offset `0xa03f`, so this word is 20 bytes into the 448-byte tail beyond
the signed body. The saved eMMC word there is `fb c3 43 bd`; a controlled
tail could replace it without altering the certificate/body hashes checked
offline.

## Assessment and remaining conditions

I found no omitted stack frame, second MMC destination bound, or count
change that defeats the modeled return-address overwrite on the raw MMC
path. The FIFO copy will overwrite its saved registers and LR on the
final sector before its return if the modified destination reaches it.

This does **not** prove exploitation on the panel. Secure services 0–2
execute before the full read; their unseen implementation may reject the
edited outer TOC or change shared boot state. A storage error could stop
the callback before the final sector. A destination firewall fault at
`0x4030cc54` appears unlikely: `0x35f30` itself has already used a CPU
`PUSH` to write its saved LR at that exact address in the same execution
context. The selected-image service 3 is visibly later than the copy, so
it does not prevent the modeled overwrite once the callback reaches that
sector.
