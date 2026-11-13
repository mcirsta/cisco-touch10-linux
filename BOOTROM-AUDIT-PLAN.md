# OMAP4460 ES1.1 Boot ROM security audit

Target: the Touch 10's 49,152-byte ROM captured at physical
`0x40030000`–`0x4003bfff`, SHA-256
`7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff`.
The installed first-stage image is the exact CE9.9.0 MLO, SHA-256
`2b80cf8b398c3cb109d4da028831ff4881c8b0ea0fa8c33167a6d6b00e62e427`.
This is an offline audit. Any later test on the panel needs a separate,
reviewed experiment.

Current progress (2026-11-07): Phase 1 mapped the captured 48 KiB executable
ROM and its low alias. Phase 2 traced the USB size limit, TOC parser,
storage read, and all visible callers of the defective range clamp. Phase 3
verified the exact MLO certificate/body chain offline and mapped the
pre-copy secure-service gate; the secure-side handler remains unavailable.
Phase 4 has a strong conditional return-address overwrite candidate:
the first pass reads 5 KEYS + 26 PRIMAPP + 1 selected-header sectors, then
the later full 49-sector selected read can cross the SRAM window and write
an unsigned sector tail over a saved return address. An independent stack
challenge found no missed frame or second visible bound. The eMMC backup
places the exact MLO at raw slot LBA 256, and the signed MLO's successful
path implies inherited source code 5 or 6; both use the modeled ROM MMC
callback. Acceptance of an edited TOC by the secure handler remains unknown.
Phase 5 found no established reversible way to test the exact storage gate
through accessible ports. Phase 6 therefore retains the already proven
U-Boot RAM `bootz` route for firmware development. Follow-up reviews of
USB setup/bulk handling, CH offsets, the configuration interpreter, and
the signed PPA service dispatch did not establish a second executable
ROM exploit. A focused USB follow-up established that the saved ASIC ID
has the CH/speedup fuse gate enabled on this unit. The ROM parses a short
USB image beyond its received length, and an unchecked CHRAM TOC offset
can wrap to a ROM literal that passes the record checks when runtime
context bit 6 is clear. The resulting fixed memory-controller writes
have not yielded code execution or readback. The USB receiver uses DMA
with a ROM-selected destination and a checked count; mid-transfer bus
reset and DMA cancellation remain hardware-dependent questions. A bounded
live reset test showed that the ROM answered GET_ID again after a USB port
reset. The OMAP4460 controller specification confirms that this four-byte
packet took the FIFO path, so it did not exercise a DMA memory write.
No ROM exploit has been reproduced on the panel. The current consolidated result is in
`evidence/bootrom-audit-assessment-2026-11-07.md`.

## Phase 1 — Establish the binary map

- Confirm capture length, ARM entry vectors, physical load address, code/data
  boundaries, and sparse/padding regions.
- Import the raw ROM at `0x40030000`, ARM little-endian, and build a function,
  cross-reference, and string inventory.
- Map public TI boot-flow descriptions to observed code without assuming that
  adjacent OMAP revisions share identical ROM bytes.
- Deliverable: address map and reproducible analysis database/script.

## Phase 2 — Trace host-controlled inputs

- Recover USB peripheral boot commands and transfer framing, plus UART and
  other boot-source entry points reachable on this board.
- Track lengths, offsets, TOC names, destination pointers, and error paths
  from ingress to memory writes.
- Mark each value as host-controlled, fuse/ROM-derived, or computed.
- Deliverable: protocol state diagram and input-to-sink table.

## Phase 3 — Trace authentication and execution

- Identify secure-device selection, key-hash checks, certificate and signature
  parsing, hash calculations, anti-rollback checks if present, and the final
  jump to a loaded image.
- Compare the ROM's accepted image structures with the exact signed MLO/PPA,
  including the observed `2ND` and `MLO` paths.
- Deliverable: trust-boundary diagram and a list of checks required before
  attacker-supplied bytes can execute.

## Phase 4 — Hunt and rank vulnerabilities

- Review arithmetic overflows/underflows, bounds checks, short transfers,
  state-machine confusion, parser ambiguity, overlap/aliasing of source and
  destination, copy/decompression routines, and error-path cleanup.
- For each candidate, record exact ROM addresses, controlling input, reachable
  boot mode, violated invariant, likely effect, and evidence against it.
- Deliverable: findings table with confidence levels: hypothesis, statically
  demonstrated, or reproduced on this unit.

## Phase 5 — Reproduce candidates safely

- Build an offline parser/emulator harness where feasible, with regression
  inputs that isolate one condition at a time.
- Propose bounded device probes only for candidates that cannot be resolved
  offline, with explicit expected serial/USB outcome and recovery procedure.
- Deliverable: reproducible PoCs or a documented reason each candidate fails.

## Phase 6 — Decide practical access path

- Assess whether a real weakness gives ROM code execution, data readback, or
  only a denial of service; separate it from the already proven U-Boot `bootz`
  path.
- Recommend the smallest reversible next experiment and preserve the current
  firmware backup and recovery state.
- Deliverable: final technical report with citations to disassembly, traces,
  and public primary documentation.

## Phase 7 — Focus on USB ROM exploitability

- Completed offline: trace GET_ID/BOOT sequencing, DMA and FIFO sinks, EP0
  descriptors, short-image TOC parsing, CH record dispatch, and the
  pre-verification speedup interpreter. See the three focused USB reports in
  `evidence/bootrom-usb-{state-machine,memory-sinks,preauth}-2026-11-07.md`.
- Completed live, under separate authorization: the ROM returned the same
  81-byte GET_ID response twice before a host USB port reset and once after
  it, within the same ROM USB appearance. The panel later booted Linux.
  The four-byte packets used the residual FIFO path, so this proves
  command-path recovery and constrains DMA_ADDR retention, not DMA enable
  or memory safety. See `evidence/rom-usb-reset-2026-11-07.md`, its raw
  logs, and `evidence/bootrom-usb-dma-reset-followup-2026-11-07.md`.
- Next offline: establish the internal DMA channel's enable/count behavior
  across a bus reset during a *full* 512-byte packet. The four-byte GET_ID
  probe never caused a DMA data write, although it constrains DMA_ADDR
  retention. A full-packet USB timing result alone cannot prove a late RAM
  write; an instrumented RAM-only controller test would be stronger.
- Next offline: trace the fixed CHRAM/CHSETTINGS register effects and the
  secure-service transition for a *controlled* pre-authentication image.
  A ROM-literal CHRAM test would program instruction words into DMM/EMIF
  registers, so it is not a suitable first live probe.
- Completed offline MMIO narrowing: DMM mappings cannot redirect low Q0
  writes into executable OCMC or DDR; GPMC config reaches external Q0
  chip selects; permitted PRCM addresses are clock generators, not direct
  fuse/firewall controls. TI errata identify conditional clock/DDR hangs,
  not a verified authentication bypass. See
  `evidence/bootrom-usb-preauth-mmio-followup-2026-11-07.md`.
- Candidate unsigned speedup-table placement: selected `2ND` TOC start 0,
  table at outer-header `+0xa4..+0x1b3`, exact signed KEYS/PRIMAPP bytes
  unchanged. ROM code does not reject start 0 before the interpreter call.
  A read-only equality poll of a known ROM literal uses pass and stall
  images differing by one bit. In separately authorized cold cycles, the
  pass image reached the PPA fatal banner; the stall image transferred
  fully but produced no PPA banner over a 120-second serial capture. A
  subsequent cold cycle restored Linux and SSH. This is strong evidence
  that the unsigned table is interpreted before verification, not a
  signature bypass. See
  `evidence/bootrom-speedup-poll-2026-11-07/README.md`.
- Any further live ROM upload requires a separate payload review and scope
  decision. The completed reset test sent GET_ID only and no image.

## Audit rules

- The dumped ROM is evidence, not proof that any input path is exploitable.
- Static suspicion is not called a vulnerability until its input reachability
  and effect are demonstrated.
- Preserve original bytes; annotate a separate IDA database and keep scripts,
  offsets, and hashes alongside the report.
