# SGX540 DDK 1.17 offline port

This work is parked. Start with [RESUME.md](RESUME.md) when returning to 3D
acceleration.

This is an **off-device compile result**, not a bootable graphics image. The
Touch 10's installed firmware and the proven `ram14` RAM-boot baseline were
not changed.

## Inputs and result

- Linux: `development/sources/linux-6.18.48`, using a separate configuration
  saved as `kernel.config` (`CONFIG_MODULES=y`, `CONFIG_DRM_OMAP=y`,
  `CONFIG_PREEMPT_VOLUNTARY=y`, local version `-perrier-sgx-dev`).
- TI SGX kernel module: `development/reference/ti-sgx-km-1.17`, upstream
  commit `9ae0fa4998b1c624408945e062bf8fb0ea7efb9d`, target
  `ti443x_linux`, SGX540 revision 120, release and `lws-generic`.
- Port changes: `ti-sgx-km-1.17-linux-6.18.patch`. These adapt the timer API,
  mixed-PFN API, DMA-BUF namespace syntax, and removed DRM `date` field.
  `link_module_sources.py` creates links that the TI generated Makefile's
  pattern rule does not produce with Linux 6.18 nested module objects.
- Built module: `pvrsrvkm-1.17-6.18.48.ko`, ARMv7, vermagic
  `6.18.48-perrier-sgx-dev ARMv7 p2v8`, SHA-256
  `22a370ef2d35922ccbf165315b21c159c8efadd529f43f66857b69c166f5456b`.
  `modpost` resolved all kernel symbols. The only remaining build warning is
  TI's missing `MODULE_DESCRIPTION()`.

The kernel must be built with both `vmlinux` and `modules` before the external
module so that `Module.symvers` exists. The module source links are prepared
after the first TI make invocation generates its output directory. See
`kernel-build.log`, `kernel-modules-build.log`, and `ti-sgx-km-1.17-build.log`.

## Userspace decision

Build our own userspace. TI's 1.17 binaries are protocol references, not
runtime dependencies. The earlier binary-rootfs staging experiment in
`stage_userspace.py`, `packages/`, and `rootfs/` is superseded.

The important obstacle is the interface, not the DDK version string. Offline
comparison of the LG 1.8 source, TI 1.17 kernel headers, and TI's actual
`libsrv_um.so` found changed bridge command numbers, a reordered 28-byte
bridge packet, changed CONNECT payloads, and a reordered SGX initializer
structure. See [abi-comparison.md](abi-comparison.md) for the evidence and
the source-built development sequence. The TI kernel also checks SGX
microkernel structure sizes and build options, so startup requires more than
a compatible services handshake.

## Before a live GPU trial

1. Finish native `omapdrm` display bring-up and confirm the board's SGX
   power/clock/reset/interrupt DT node against the stock hardware evidence.
   The current `ram14` DT intentionally does not enable the GPU.
2. Build a **separate** RAM-only image using this SGX kernel configuration,
   with the established watchdog and stock-return path intact. Do not boot
   this development `vmlinux` directly; its native display path has not been
   validated on Perrier.
3. Implement and host-test the source-built ARM32 services bridge and SGX
   initializer against TI 1.17's released headers, using the binary only to
   resolve unclear behavior. Characterize the microkernel and scripts before
   any GPU start attempt.
4. Integrate our own userspace into a temporary RAM-only image. Check the
   module's `ti,omap4-sgx540-120` probe, then a bounded services handshake,
   then SGX initialization, then an offscreen GLES test and visible KMS
   rendering. Record GPU clocks, temperature, interrupts and watchdog
   recovery.

No 3D runtime behavior has been verified on the Touch 10 yet.
