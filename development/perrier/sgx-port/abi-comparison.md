# SGX540 userspace protocol comparison

Scope: offline comparison of the LG OMAP SGX DDK 1.8 source tree at
`/tmp/touch10-lg-omap-sgx-ddk`, TI's SGX DDK 1.17 kernel headers in
`development/reference/ti-sgx-km-1.17`, and TI's 1.17 ARM userspace
`libsrv_um.so.1.17.4948957`. No Touch 10 device command was run.

## Result

The public-facing services API has recognizable entry points across these
releases, and both use a DRM bridge transport. The kernel bridge protocol is
**not wire compatible**. A source-built 1.17 userspace can reuse concepts and
selected algorithms from the older source, but must use the 1.17 command map,
packet layouts, handle rules, and SGX initialization protocol. Changing or
disabling the version comparison alone would send incorrectly structured data.

At the C API layer, the LG source implements `PVRSRVConnect`,
`PVRSRVEnumerateDevices`, and `PVRSRVGetMiscInfo` in
`srvclient/bridged/bridged_pvr_glue.c`; IDA finds all three exported by TI's
`libsrv_um.so`. TI's released `include4/services.h` also declares the first
two with corresponding connection/device parameters. This is useful porting
continuity, but the matching function names do not imply matching bridge
messages. EGL/GLES and compiler APIs were not compared in this pass.

## Command and transport evidence

The older Linux bridge client calls `drmCommandWrite(..., PVR_DRM_SRVKM_CMD,
&sBridgePackage, sizeof(sBridgePackage))` in
`eurasia/services4/srvclient/env/linux/common/pvr_bridge_u.c:230-255`.
IDA analysis of TI's ARM `libsrv_um.so` shows its connect path also calls
`drmCommandWrite`. Thus the transport is similar. The bridge command carried
inside the package differs:

| Operation | LG 1.8 header | TI 1.17 header | TI binary observation |
| --- | ---: | ---: | --- |
| UM/KM compatibility | absent | command 0 | not yet traced |
| Enumerate devices | command 0 | command 1 | `PVRSRVEnumerateDevices` passes `0xC01C6701` |
| Connect services | command 12, `0xC01C670C` | command 13, `0xC01C670D` | connect helper constructs `0xC01C670D` |
| Allocate device memory | command 6 | command 7 | not yet traced |
| Get misc info | command 48 with default LG options | command 39 with TI OMAP4 options | `PVRSRVGetMiscInfo` passes `0xC01C6727` (39) |

The `0xC01C67xx` values encode `_IOWR('g', command, 28)` on 32-bit ARM.
The old command map comes from `eurasia/services4/include/pvr_bridge.h:75-140`;
the new map comes from `services4/include/pvr_bridge.h:87-161`.
The TI OMAP4 build enables `SUPPORT_DMABUF` at
`eurasiacon/build/linux2/ti443x_linux/Makefile:103`. The old `GET_MISC_INFO`
number is conditional on old build options; 48 assumes overlay and PDUMP
disabled. The binary observation establishes the new value for the shipped
TI build. There is no single offset: TI inserted the compatibility command,
removed two core device-class mapping commands from that block, and added
DMA-BUF commands before the miscellaneous block.

## Packet layout evidence

Both bridge packages occupy 28 bytes on ARM32, but fields moved:

| Byte offset | LG 1.8 `PVRSRV_BRIDGE_PACKAGE` | TI 1.17 `PVRSRV_BRIDGE_PACKAGE` |
| ---: | --- | --- |
| 0 | bridge ID | bridge ID |
| 4 | package size | package size |
| 8 | input pointer | input handle/pointer |
| 12 | input length | output handle/pointer |
| 16 | output pointer | input length |
| 20 | output length | output length |
| 24 | kernel-services handle | kernel-services handle |

Sources: LG `pvr_bridge.h:289-303`, TI `pvr_bridge.h:311-321`.
An unmodified old client would place its input length where the 1.17 kernel
expects an output pointer. This is an actual ABI break independent of any
version check.

The payloads differ as well. LG's CONNECT input has an initial bridge-flags
word followed by `ui32Flags`; TI's has only `ui32Flags` (LG lines 314-318,
TI lines 332-335). LG's CONNECT output is an error plus a native handle;
TI's has an error, a kernel-architecture byte, and a 64-bit services handle
(LG lines 712-720, TI lines 585-590). LG's GET_MISC input has an initial
bridge-flags word; TI's does not (LG lines 1767-1772, TI lines 1377-1380).
These examples show that payloads must be checked individually.

## SGX initialization and GPU protocol

The `SGX_DEVINITPART2` bridge wrapper in both trees contains a device handle
and `SGX_BRIDGE_INIT_INFO`, but LG adds an initial bridge-flags word
(`sgx_bridge.h:385-394`) and TI does not (`sgx_bridge.h:321-325`). The nested
`SGX_BRIDGE_INIT_INFO` also changes: the TI definition puts
`ui32ClientBuildOptions` before `sScripts`; LG puts it after `sScripts`
(LG `sgxinfo.h:77-107`, TI `sgxinfo.h:82-100`). TI drops older optional BRN
fields and adds other conditional fields. The identical `SGXMKIF_CMD_MAX=11`
does **not** establish binary compatibility for the rest of the structure.

TI's kernel checks client build options, then the microkernel's reported
structure sizes and build options in `sgxinit.c:2713-2862`. This is a second
protocol boundary after the services bridge. The size table has largely the
same named entries, but matching names do not prove matching values or field
semantics (`sgx_mkif_km.h:363-393` versus LG lines 363-382). The TI 1.17
microkernel image and initialization scripts must be characterized before a
source-built initializer can safely start the GPU.

The TI `libsrv_init.so` binary confirms continuity of the **startup sequence**:
its main SGX initialization routine calls `SGXGetInfoForSrvInit`, prepares
initialization data (including a 2,712-byte allocation), then calls
`SGXDevInitPart2`. The LG source makes those calls in the same broad order in
`srvinit/devices/sgx/sgxinit.c:5112-5212`. This supports porting the control
flow while rebuilding the data structures for 1.17; it does not establish
compatibility of the older scripts or microkernel image.

## Development sequence for our own userspace

1. Build a small ARM32 services client using **TI 1.17's released bridge
   headers** and our chosen libc/toolchain. Keep transport, command encoding,
   and payload marshalling in one module. First test CONNECT, device
   enumeration, and GET_MISC against a host-side mock of the expected bridge
   packets; record exact sizes and offsets from the ARM32 compiler.
2. Port service logic selectively from the older source, comparing each
   command's request and response to TI 1.17 headers. Use TI's binary as an
   observation target where headers leave behavior unclear. Do not copy an
   old bridge wrapper unchanged.
3. Compare the TI 1.17 initializer binary with the older source's SGX
   initialization stages. Establish the source and compatibility of the
   microkernel image, scripts, build options, and `SGXMKIF` layouts before
   attempting GPU initialization.
4. Only after the services and initialization protocol are understood,
   address the GLES/shader compiler and Mesa integration. Those are separate
   components and are not supplied as 1.17 source by the TI userspace repo.

The existing staged TI binary rootfs under `sgx-port/rootfs/` is superseded
as an implementation plan. It remains an offline reference; it is not a
dependency of the intended source-built userspace.
