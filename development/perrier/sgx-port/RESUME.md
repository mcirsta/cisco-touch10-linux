# Parked SGX540 acceleration work — 2026-11-08

Status: paused at the user's request. Resume from the evidence and plan here;
do not treat the staged TI binary rootfs as the intended userspace.

## Preserved result

- The Touch 10 stock stack is DDK `1.9@2253347`, SGX540 rev 120. Stock
  evidence is in `evidence/perrier-stock-graphics-stack-2026-11-08.txt`.
- TI's `1.17.4948957` OMAP4/SGX540 kernel source is in
  `development/reference/ti-sgx-km-1.17`. Its out-of-tree module was patched
  for Linux 6.18.48 and compiled offline. The patch, module, exact input
  commit, hash, and build logs are indexed in `README.md`. It has **not** been
  loaded on the panel.
- TI's 1.17 ARM userspace binaries are in
  `development/reference/ti-sgx-um-1.17`. The older LG DDK 1.8 source was
  inspected at `/tmp/touch10-lg-omap-sgx-ddk`; that temporary path may need
  to be reacquired in a future session. The exact commits are recorded in
  `README.md` and `graphics-stack.md`.
- IDA comparison found shared services API names and DRM bridge transport,
  but different command numbers, a reordered bridge package, changed
  CONNECT payloads, and changed SGX initialization layout. TI's actual binary
  sends ENUMERATE=1, CONNECT=13, and GET_MISC=39. Full evidence and source
  locations are in `abi-comparison.md`.
- TI's initializer binary calls `SGXGetInfoForSrvInit` and
  `SGXDevInitPart2` in the same broad order as the older source. This says
  nothing yet about the compatibility of scripts, microkernel code, or GLES.

## Agreed direction on resumption

Build our own ARM32 userspace from source. Use TI 1.17's released kernel
headers as the target wire ABI and the TI binaries as offline behavioral
references. Start with a minimal services bridge for CONNECT, ENUMERATE, and
GET_MISC, including exact ARM32 sizes and offsets and a host-side mock.
Then port initialization with the 1.17 structure layout and characterize the
microkernel image and scripts. GLES/shader compiler and Mesa integration are
later stages. See `abi-comparison.md` and `graphics-stack.md` for the ordered
plan and open questions.

The binary staging artifacts under `packages/` and `rootfs/` are retained only
for comparison. They are superseded by this source-built direction. No SGX
runtime behavior has been tested on the Touch 10, and no persistent boot or
storage change is part of the acceleration plan.
