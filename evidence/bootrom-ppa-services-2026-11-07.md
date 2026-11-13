# Exact CE9.9.0 PPA service dispatch and ROM gate

Scope: offline analysis of `firmware/codec-ce9.9.0/analysis/touch10-ce990-ppa.bin` (SHA-256 `c105b1bcaf7b61cf28432f4839c41cbf9ace7359b39de5245c792a33b4831a1c`) and the captured 48 KiB OMAP4460 ROM low alias. Addresses are PPA load addresses (`0x4030xxxx`) or ROM low-alias addresses (`0x3xxxx`). No panel access or device state change was made.

## ROM selectors versus PPA service IDs

The visible ROM calls at `0x3452c`, optional `0x3453a`, and `0x3454e` use wrappers `0x30f24`, `0x30f36`, and `0x30f48`. Those wrappers put **0, 1, and 2** in R0, respectively, before `0x30f04` calls `0x37594` and executes `SMC #1` at `0x375b0`. The later selected-image call at `0x344ec` uses wrapper `0x30f5a`, which puts **3** in R0 before the same SMC path. These are the ROM monitor's raw selector numbers. The `SMC #1` handler is absent from the 48 KiB low-alias capture, so the implementation and any TOC checks of selectors 0–3 are unresolved.

The signed PPA exposes a different dispatch interface. Its vectors at `0x40300e18` and `0x40300e26` OR `0x01000000` or `0x02000000` into the requested ID, then call `0x40302350`. That dispatcher removes the high byte and routes by namespace. Startup at `0x40303bd8` installs three PPA-owned tables at `R9+0xb0` through `R9+0xc4`:

| PPA namespace | Local table and IDs | Lookup behavior |
| --- | --- | --- |
| `0x01xxxxxx` | `0x40300e34`–`0x40300ecb`: `0x21`–`0x2a`, `0x3e`, `0x2b`–`0x32` | `0x40302372`–`0x40302384` calls exact-match lookup `0x403033f0`. IDs below `0x20` have no fallback. |
| `0x02xxxxxx` | `0x40300ecc`–`0x40300ee3`: `0x1031`–`0x1033`; `0x40300ee4`: `0x9c` | `0x40302386`–`0x403023c8` selects local tables or helper lookups. Helper `0x40301c20` recognizes only `0x8c`, `0x8d`, and `0x96` in its low-ID branch. |

`0x403033f0` compares each full 32-bit table ID with the requested low 24 bits (`CMP R5,R2` at `0x403033fc`); it does not truncate `0x21` to 1 or `0x32` to 2. In the visible PPA dispatcher, requests for IDs 0–3 in either namespace do not resolve to these table handlers. This rules out a **direct numeric alias/wrap** from the PPA's `0x21`–`0x32` IDs to ROM SMC selectors 0–3. It does not rule out a PPA handler making an independent outbound call that ultimately uses a monitor service; the external callback implementations are not present.

The PPA's outbound lookup at `0x40302c4c` is separate from those local tables. It obtains a callback through `[0x402104]`, invokes that callback for a requested ID, and may fall back to tables at `0x318100`, `0x318140`, or `0x318200`. None of those external targets is in the extracted PPA or low-alias ROM. Their behavior cannot be used to infer that a local PPA service ID reaches a ROM SMC selector.

## Startup descriptor and low-memory handoff

The PPA startup descriptor is **constructed by the PPA itself**. Vector `0x40300df8` calls `0x403031b4`, which places four words on its stack: caller R0 (flags) at `+0`, constant `3` at `+4`, constant `6` at `+8`, and constant `1` at `+12`. It passes that stack address to `0x40301f38`; depending on flags, that routine calls startup `0x403038d4`. At `0x403038ec`, the `+4` word is passed to `0x40303b0c`, but that callee overwrites R0 before use. The `+8` word is stored at `R9+0x28` by `0x40301f7c` and controls PPA print severity at `0x40301fa0`–`0x40301fb0`. The `+12` word is stored as a boot-information byte by `0x403031f0`. **This descriptor contains no observed outer-TOC pointer.** The origin and exact meaning of caller R0 flags remain outside the PPA image.

A distinct low-memory handoff exists: `0x40303c4c` copies `[0x402100]` and `[0x402104]` to `R9+0xd0` and `R9+0xd4`. The PPA uses the second pointer for outbound service lookup and memory-range operations; it also writes a callback at `[pointer+8]` in `0x40301880`. The code that populates the two low-memory words, the pointed-to structures, and the callback/table implementations are absent. No observed use identifies either word as the outer-TOC address.

## Outer TOC destination `+0x10`

In the ROM storage path, `0x32f2e` passes a stack-local buffer (`SP+0x28` at that call site) as R0 to `0x32a74`; `0x32a7e` retains that pointer in R11. The visible SMC wrappers pass section pointers in their explicit argument descriptors, not this stack-local outer-TOC pointer. The monitor could still inspect R11, saved registers, nonsecure stack, or shared state; its handler is unavailable.

In the IDA-recognized PPA code, the two direct `LDR [base,#0x10]` instructions are `0x403023aa` (PPA service-group table pointer at `R9+0xc0`) and `0x403024a2` (a hardware-register block also read/written at offsets `+8`, `+0xc`, and `+0x40`). Neither is traced to the ROM's TOC stack buffer. The PPA's fixed `0x40300000` and `0x40303c00` references at `0x40301a4c`–`0x40301a84` configure exception/vector addresses; they are not a TOC parse. Searches of the PPA image found no `MLO`, `PRIMAPP`, `KEYS`, or `TOC` string. This is evidence against an **obvious direct PPA read** of outer TOC `+0x10`, not an exhaustive proof against dynamic access through unknown monitor state.

**Assessment:** the PPA startup descriptor and local service table provide no path by which changing outer TOC `+0x10` is clearly checked before the ROM's `0x32b66` read. Acceptance remains unproved because the secure SMC handler and low-memory handoff contents are missing. The next decisive evidence would be a same-revision secure ROM/monitor implementation or a bounded device test of the unchanged signed payload with only the outer TOC destination altered; this report authorizes no device test.
