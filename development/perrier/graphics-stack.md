# Graphics stack choice for Perrier

The Touch 10's OMAP4460 contains a PowerVR SGX540. The factory Linux 3.4
installation uses `omapdrm` for the display framebuffer and loads
`omapdrm_pvr` for SGX acceleration. The installed SGX DDK reports
`1.9@2253347`, revision `1.2.0`. See
[`evidence/perrier-stock-graphics-stack-2026-11-08.txt`](../../evidence/perrier-stock-graphics-stack-2026-11-08.txt).

For the new Linux image, use mainline `omapdrm` for DSS/DSI scanout and the
mainline `tc358775` DRM bridge driver, which includes TC358765 support. Bring
up a working 1280x800 display with CPU-rendered buffers first. The current
`simplefb` trial only inherits display state from the factory kernel across
kexec; it is not a cold-boot display implementation. The legacy `omapfb`
driver is present in Linux 6.18, but it is mutually exclusive with
`DRM_OMAP` and would need additional integration for this bridge.

GPU acceleration is a separate stage:

* Mesa's upstream PowerVR Vulkan driver starts with Rogue/Series6 hardware.
  Mesa explicitly excludes earlier GPUs, so it cannot run on SGX540.
* TI's newer `sgx` Gallium component is a Mesa shim for its SGX DDK. It can
  use `omapdrm` as the display alias, but TI states that the matching GLES
  userspace library, firmware, and control server remain proprietary. This
  is a possible accelerated path if those binaries work on this OMAP4460 and
  the out-of-tree kernel module is ported to our kernel; it is not a fully
  open source renderer.
* The independent reMESA work is experimenting with an open SGX535 Mesa and
  kernel driver and researching SGX544. Its published implementation does
  not support this SGX540. It is useful protocol research, not a drop-in
  graphics stack for Perrier.

## Full SGX540 acceleration investigation (2026-11-08)

The factory panel already has a working Linux SGX stack: `omapdrm_pvr.ko`,
`pvrsrvinit`, EGL/GLESv1/GLESv2, GBM, KMS window-system glue, and SGX test
programs in `/extra`. `/proc/pvr/version` reports DDK `1.9@2253347` and SGX
revision `1.2.0`. TI published the matching 1.9 kernel-source tag, which is
available locally in `development/reference/ti-sgx-km-1.9-stock`.

For a newer stack, TI's public `1.17.4948957/mesa/k6.1` kernel module is in
`development/reference/ti-sgx-km-1.17` (commit `9ae0fa4998b1`). Its
`ti443x_linux` target explicitly selects SGX540 revision 120, and its device
table matches `ti,omap4-sgx540-120`. TI's matching 32-bit ARM userspace release
is in `development/reference/ti-sgx-um-1.17` (commit `84a396a4fb37`) under
`targetfs/ti443x_linux/lws-generic/release`. It includes the proprietary GLES
implementation, shader compiler, services and initialization libraries, and
`pvrsrvctl`. TI documents the userspace as linked against glibc 2.35. The
kernel and userspace DDK build numbers and build options must match.

TI's SGX Mesa fork supplies the DRI/Gallium *shim*, built with
`-Dgallium-drivers=sgx -Dgallium-sgx-alias=omapdrm`; rendering remains in the
proprietary DDK userspace. Upstream Mesa's PowerVR Vulkan driver cannot target
SGX540. The proven Perrier `ram14` kernel has no loadable module or native DRM
display configuration yet. A separate offline configuration and a four-file
API patch now compile the TI 1.17 SGX module against Linux 6.18.48; see
[`sgx-port/README.md`](sgx-port/README.md). This is a compile result only: the
module has not been loaded on the panel. TI documents compatibility through
Linux 6.12, so its runtime behavior on 6.18 remains unverified.

The userspace target is now a **source-built implementation**. TI 1.17
binaries serve as protocol references only. The LG 1.8 source and TI 1.17
binary use related services APIs and DRM transport, but their command map,
bridge packet layout, CONNECT payloads, and SGX initialization layout differ.
See [`sgx-port/abi-comparison.md`](sgx-port/abi-comparison.md). Library version
requirements of TI's prebuilt binaries do not set requirements for our own
build. Full acceleration still requires understanding the 1.17 SGX
microkernel, initialization scripts, GLES implementation, and shader compiler.

The reported LG OMAP4 source dump was fetched for local inspection to
`/tmp/touch10-lg-omap-sgx-ddk` (commit `f184ac914561`). Its own version header
and README identify Android DDK `1.8@869593`, SGX540 revision 120. It is older
than the factory DDK and expects Android graphics plumbing. Imagination's
2018 copyright complaint identifies its userspace and compiler tree as
unauthorized publication; keep that dump separate from the project sources.
Use the released TI kernel headers for the new wire ABI, the TI binaries as
offline behavioral references, and our own source-built userspace as the
implementation target.

### Bring-up order

1. Finish native `omapdrm`/DSS/DSI/TC358765 display scanout with fixed
   factory-derived clocks, regulator settings, and reset sequencing.
2. Enable module loading in a *RAM-only* 6.18 kernel, then build TI's
   `ti443x_linux` SGX 1.17 module against its headers. Resolve kernel API
   differences offline; do not modify stock firmware or boot partitions.
3. Build an ARM32 services client from source using the TI 1.17 bridge
   headers. Verify its packet and payload layouts offline, then characterize
   and port SGX initialization and microkernel loading. Use TI binaries as
   behavioral references only.
4. With watchdog recovery preserved, run a bounded RAM-only kernel trial.
   Verify GPU device probe, services communication, and SGX initialization
   before using an offscreen EGL/GLES test, then a visible DRM/KMS test.
5. Record GPU clock, thermal, interrupt, and power observations during the
   test. Stop on abnormal sound, temperature, or display behavior and let the
   watchdog return to stock.

The immediate dependency is to verify the stock bridge's power, reset, lane,
and clock sequence before enabling native OMAP DRM. After scanout works,
test software Mesa rendering through DRM/KMS. A future SGX540 renderer would
need its own GPU execution driver and buffer sharing with `omapdrm`; TI's
`omapdrm` documentation confirms DMA-BUF imports on OMAP4 TILER, but actual
format and synchronization compatibility must be tested. GPU acceleration
can then be evaluated without changing the display driver choice.

Primary references:

* [TI OMAP4430/4460 multimedia-device addendum](https://www.ti.com/lit/ug/swpu278/swpu278.pdf), Chapter 11 (SGX540)
* [TI DSS and omapdrm documentation](https://software-dl.ti.com/processor-sdk-linux/esd/docs/06_02_00_81/linux/Foundational_Components/Kernel/Kernel_Drivers/Display/DSS.html)
* [Mesa PowerVR driver documentation](https://docs.mesa3d.org/drivers/powervr.html)
* [TI SGX build guide](https://github.com/texasinstruments/processor-sdk-doc/blob/master/source/linux/Foundational_Components/Graphics/SGX/Build_Guide.rst)
* [TI SGX kernel source refs](https://git.ti.com/cgit/graphics/omap5-sgx-ddk-linux/refs/)
* [TI SGX userspace refs](https://git.ti.com/cgit/graphics/omap5-sgx-ddk-um-linux/refs/)
* [LG OMAP4 dump inspected](https://github.com/shaqfu786/GFX_Linux_DDK)
* [Imagination copyright complaint](https://github.com/github/dmca/blob/master/2018/2018-05-21-SGX.md)
* [reMESA project status](https://github.com/reMESA-devgroup/reMESA)
