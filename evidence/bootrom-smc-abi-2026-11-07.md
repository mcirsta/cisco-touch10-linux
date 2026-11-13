# ROM secure-service call ABI at the storage gate

Scope: disassembly of this unit's captured OMAP4460 Boot ROM, low alias
addresses. This is an offline register/stack trace, not a claim about the
unseen secure handler's implementation.

The storage loader `0x32a74` keeps the TOC base in R11 from `0x32a7e`.
Its first-pass gate calls `0x344fa` at `0x32b38`. That function saves
R4–R8/LR but does not modify R11. For the exact MLO, its secure-service
calls use three wrappers:

| Selector | Wrapper | Visible section argument |
| ---: | --- | --- |
| 0 | `0x30f24` at `0x3452c` | KEYS pointer (R6 in `0x344fa`) |
| 1 | `0x30f36` at `0x3453a`, optional | R&D pointer (R5), absent in the exact MLO |
| 2 | `0x30f48` at `0x3454e` | PRIMAPP pointer (R8) |

Each wrapper places its section pointer in a stack word and sets R3=1.
`0x30f04` saves R0–R3, then sets R3 to the address of that saved R3
word and enters `0x37594`. At `0x37594`, R4–R12/LR are saved, R6 is set
to `0xff`, R12 to zero, and `SMC #1` executes at `0x375b0`. The visible
descriptor passed in R3 is therefore a count word followed by a section
pointer. No explicit TOC pointer or TOC `+0x10` destination is put in
R0–R3 by these wrappers.

TI's public [OMAP secure dispatcher source](https://git.ti.com/cgit/ti-linux-kernel/ti-linux-kernel/tree/arch/arm/mach-omap2/omap-secure.c?id=f7901365aa48b20b25f8402e0fd1eea4ac6c55e7)
uses the same convention for later secure-service calls: a parameter array
whose first word is an argument count, followed by explicit arguments,
passed through `omap_smc2`. This corroborates the descriptor interpretation;
it does not reveal this unit's secure handler code or guarantee that it
ignores other registers.

The full selected-image read runs at `0x32b66`. Only afterward does
`0x32b7e` call `0x344dc` and wrapper `0x30f5a`, which selects service 3
with a descriptor count of two for the loaded selected image and a second
argument. This timing
supports the pre-service-3 stack-overwrite candidate.

R11 still contains the TOC pointer when the pre-copy `SMC #1` runs. The
nonsecure veneer preserves it but does not clear it. A secure handler
could read that register, the nonsecure stack, or shared state despite the
explicit descriptor containing only section pointers. The exact secure
handler is not present in the captured 48 KiB ROM, so its TOC policy
remains unproven.
