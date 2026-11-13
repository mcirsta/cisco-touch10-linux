# Apple TV 2 USB host feasibility

Date: 2026-11-08. Target: A1378, AppleTV2,1, K66AP, Apple A4/S5L8930.

The A1378 firmware contains a concrete USB host implementation path: separate
EHCI/OHCI controller descriptions, host PHY settings, an Apple-specific
`force-usb-host` option, and code that switches the USB-complex role selection.
This makes a Linux host implementation credible. Operation through the external
Micro-USB connector remains unverified because its signal routing and downstream
5 V supply have not been measured. No working A1378 Linux host enumeration was
established.

The device was not connected and had no existing shell/debug access during this
investigation. All analysis used public source, photographs and downloaded Apple
firmware. No device commands, boots, firmware changes, boot-argument changes or
register writes were performed.

## Evidence files and firmware provenance

The [evidence directory](apple-tv2-usb-host-2026-11-08/) contains the original
firmware members, decoded DeviceTree, uncompressed kernel, selected IDA output,
historical source snapshots, FCC documents and reproduction scripts. The
[hash manifest](apple-tv2-usb-host-2026-11-08/SHA256.json) identifies these files.

Firmware: Apple TV Software 6.2.1, underlying iOS 7.1.2, build 11D258. The
[official Apple IPSW](https://secure-appldnld.apple.com/iOS8/031-07202.20140917.tF6Fs/AppleTV2,1_6.2.1_11D258_Restore.ipsw)
was accessed using HTTP ranges to obtain only DeviceTree and kernelcache members.
Their ZIP CRC32 values were verified; the complete IPSW was not downloaded or
checked against its published whole-archive hash. Public component AES values
came from the [11D258 key record](https://theapplewiki.com/wiki/Keys%3ASochi_11D258_%28AppleTV2%2C1%29).

The decrypted DeviceTree parses completely: 49,264 of 49,264 bytes. Its root
identifies K66AP and AppleTV2,1. Kernel decompression produced 11,759,616 bytes,
matching the compression header and Adler32 `11a95569`.

| File | SHA256 |
| --- | --- |
| DeviceTree.k66ap.img3 | `a3ff81244412b0d082410374bf3de4fbec3896c4da68af085f65876fa723d997` |
| DeviceTree.k66ap.bin | `a84ed6a2a3aefb8908f63d0b93f2ee0202431d9d6cd0c8e0c754458da3bf7616` |
| kernelcache.release.k66 | `b2d966bbdedcec60eadad10951bf8e99d3f65e80d1dc4ffdffef860f7039bcb0` |
| kernelcache.release.k66.macho | `2f500718f37a01a1ca7612480eea0a887c9a7dca67af6328f691f0b1e32bd7c1` |

Reproduce decoded outputs locally with:

```sh
python3 evidence/apple-tv2-usb-host-2026-11-08/decode_firmware.py
```

This command reads the saved members, verifies their SHA256 values, decrypts
them using OpenSSL and checks the decoded tree and kernel. It has no network
or device operations.

## Host controllers in the exact board DeviceTree

The [decoded USB nodes](apple-tv2-usb-host-2026-11-08/usb-nodes.json) describe:

| Block | Physical base | Interrupt | Compatible or purpose |
| --- | --- | --- | --- |
| USB PHY | `0x86000000` | — | `otgphyctrl,s5l8930x` |
| USB device controller | `0x86100000` | 13 | `usb-device,s5l8930x` |
| EHCI host controller | `0x86400000` | 14 | `usb-synopsys_ehci,s5l8930x` |
| OHCI0 host controller | `0x86500000` | 15 | `usb-ohci,s5l8930x` |
| USB-complex control | `0xbf108000` | — | USB_CTL role and clock control |

These addresses result from translating the nested Apple DeviceTree `ranges`,
not treating every node's raw `reg` value as a physical address. The controller
windows are each `0x10000` bytes. Both host nodes contain a port-1 child.

Independent historical A4 Linux source corroborates the PHY, device, EHCI and
OHCI addresses. Its [register map](https://github.com/scintill/iDroid-kernel/blob/2b1c269f5363911903b5cf7484d6ece0a7c51712/arch/arm/mach-s5l8930/include/mach/map.h)
also names a second OHCI block at `0x86600000`; that extra controller is not
described by this A1378 DeviceTree and is not an established board requirement.
Its [clock definitions](https://github.com/scintill/iDroid-kernel/blob/2b1c269f5363911903b5cf7484d6ece0a7c51712/arch/arm/mach-s5l8930/clock.c)
name register/PHY gate `0x1d`, device gate `0x18`, EHCI gate `0x19`, shared USB11
gate `0x1a`, and OHCI0 gate `0x1b`. These historical IDs are not interchangeable
with the newer stock DeviceTree's clock-mask encoding.

The same historical Linux [USB change](https://github.com/scintill/iDroid-kernel/commit/2b1c269f5363911903b5cf7484d6ece0a7c51712)
was demonstrated on iPad 1 with USB Ethernet gadget mode. It does not demonstrate
Linux host operation.

## Actual role selection in the Apple driver

IDA analysis of this kernel's AppleEmbeddedUSB and AppleS5L8930XUSB components
establishes more than the presence of unused strings. Full selected
decompilations are in [analysis-arbitrator.json](apple-tv2-usb-host-2026-11-08/analysis-arbitrator.json).
Addresses below refer to the uncompressed 11D258 kernel; Thumb function pointers
can have bit zero set.

| Address | Observed behavior |
| --- | --- |
| `0x80832744` | Arbitrator start parses Apple's `force-usb-host` boot argument into object offset `0xf0`, after subclass initialization succeeds. |
| `0x808335e8` | The forced-host state selects the remote `USBDevice` cable type, meaning the local box acts as host. |
| `0x80833564` | Remote USB host maps to publication mask 3; remote USB device maps to mask 5. |
| `0x808331a8` | A controller child is published when `publish-criteria & mask` is nonzero. |
| `0x80abc0fc` | A4 cable-change callback computes local-host from mask bit 2 and changes USB_CTL bit 0 accordingly. |
| `0x80abb590` | Asynchronous cable-change/reset path also switches USB_CTL bit 0 before restoring controller power. |

The A1378 host nodes have `publish-criteria=4`; the device node has value 3.
Thus these are genuine host-role publication criteria. The A4 subclass uses the
generic cable-selection method, and the inspected initialization path has no
A1378 model check prohibiting forced host selection.

There is a precedence condition: the arbitrator's `no-pmu` state overrides the
forced-host state and selects local-device mode. The saved USB tree contains no
such property. HSIC and optional second-OHCI flags can add publication bits but
do not change the decoded host/device bits.

`force-usb-host` is an **Apple kernel option**. Passing that text to an ordinary
Linux kernel would not implement this behavior. Linux needs equivalent platform
role/clock/PHY handling. No option was applied to the device.

## Stock host PHY implementation

AppleS5L8930XUSBPhy start at `0x80ad67ec` reads separate host and device tuning
properties. The A1378 DeviceTree supplies:

| PHY property | Device value | Host value |
| --- | --- | --- |
| `uotgtune1` | `0x349` | `0x34f` |
| `uotgtune2` | `0x733` | `0x6f3` |

The method identified by its own diagnostic as `enableHostMode`, at
`0x80ad7210`, selects the host values for PHY offsets `0x40` and `0x44`, handles
PHY reset at offset `0x08`, and sets bit 1 at offset `0x64` in the non-HSIC path.
The register-write, OR and AND helpers were verified through the PHY vtable,
disassembly and implementations at `0x80ad7344`, `0x80ad7360` and `0x80ad7354`.
See [analysis-phy.json](apple-tv2-usb-host-2026-11-08/analysis-phy.json).

The byte at PHY object offset `0x50`, which guards the last operation, is the
HSIC-enabled flag. Generic PHY start at `0x808308ac` sets it only when an
inherited `hsic-enabled` property and nonzero HSIC option are present. It is not
an A1378-specific host prohibition. The saved DeviceTree lacks that property.

These routines provide reference behavior, not a complete register-write recipe.
Their clock acquisition, locking, power levels, reset order and caller state
must be reconstructed together. Some decompiler output loses arguments to
virtual calls; the host-tuning arguments were checked in ARM disassembly.

## External port power and wiring

The board-level evidence does not yet establish whether an external drive can
be attached successfully.

- Retail iFixit photographs show board `820-2808-A`; Apple's FCC sample is
  `820-2808-10`. Micro-USB is stacked under HDMI in one connector assembly,
  obscuring enough of the breakout that data/ID/VBUS routing cannot be reliably
  traced from those photographs.
- The PSU photograph identifies an ADP-6BF S module with a 3.4 V, 1.75 A output.
  A normal downstream 5 V USB supply therefore needs another board circuit or
  a separately designed peripheral-power arrangement. This does not establish
  that a boost circuit is absent.
- The development board has a populated connector at the retail J7101 footprint.
  Its pinout and relevance to USB host remain unknown.
- Apple's FCC confidentiality letter withholds schematics, block diagram,
  theory of operation and BOM; the public record does not supply a circuit
  diagram that resolves these questions.

Sources: [iFixit's teardown](https://www.ifixit.com/Teardown/Apple+TV+2nd+Generation+Teardown/3625),
[Apple's FCC internal photographs](https://fccid.io/BCGA1378/Internal-Photos/Internal-Photos-1336469.pdf),
and [Apple's confidentiality request](https://fccid.io/BCGA1378/Letter/Confidentality-Request-Long-and-Short-Term-1336413.pdf).
Copies of the two FCC documents are retained in the evidence directory.

The K66 PMU DeviceTree property `force-usb-power` does **not** resolve downstream
power. Stock code at `0x80ac3fa4` normalizes its empty/one value to 500 mA; the
consumer at `0x80ac6ab8` uses it as a minimum USB **input-current** request.
Related code adjusts charging/input limits and samples external VBUS for droop.
It is not evidence of a 5 V output switch. See
[analysis-pmu.txt](apple-tv2-usb-host-2026-11-08/analysis-pmu.txt).

The raw host-port values `port-type=2` and `port-current-limit=50` remain
undecoded; they are not proof of an external port or a measured current supply.
Likewise, `standardMuxOnly` is a USB device-configuration string, not evidence
of a physical data multiplexer.

## Linux implementation and decisive checks

The strongest implementation route is Apple-specific USB_CTL role selection,
clock/reset and PHY support around the existing Linux
[EHCI platform driver](https://github.com/torvalds/linux/blob/master/drivers/usb/host/ehci-platform.c)
and [OHCI platform driver](https://github.com/torvalds/linux/blob/master/drivers/usb/host/ohci-platform.c).
No complete S5L8930/K66 host platform implementation was established in the
inspected Linux/OpeniBoot sources. Samsung Exynos code is an architectural
reference, not an interchangeable initialization sequence.

A DWC2 capability reading is useful only for the alternative device-controller
route. `GHWCFG2 & 7` values 0/1/2 describe dual-role synthesis; 3/4 describe
device-only synthesis. A device-only result there **does not rule out the
separate EHCI/OHCI blocks**. Linux can override ID selection on supported DWC2
hardware, so connector shape or an unwired ID pin alone is not a proof of
impossibility. See [DWC2 definitions](https://github.com/torvalds/linux/blob/master/drivers/usb/dwc2/hw.h)
and [role handling](https://github.com/torvalds/linux/blob/master/drivers/usb/dwc2/core.c).

Once an existing safe debug path is available, useful read-only observations are:

| Location | Observation |
| --- | --- |
| USB_CTL `0xbf108000` | Current bit-0 role and clock-gating state. |
| PHY `0x86000000` | Selected, known configuration registers; compare with stock driver semantics. |
| EHCI `0x86400000` | Capability header, HCSPARAMS and HCCPARAMS, after confirming the standard capability layout begins at block offset zero. |
| OHCI `0x86500000` | HcRevision and HcRhDescriptorA, after confirming its layout. |
| Device `0x86100000` | GSNPSID at `+0x40` and GHWCFG1–4 at `+0x44..0x50`, if evaluating the DWC2 alternative. |

These are **conditional audit locations**, not commands to issue blindly.
Unclocked MMIO reads can fault or hang. A normal Linux HCD probe resets/enables
hardware and is not a read-only audit. Avoid arbitrary register dumps: for
example, the DWC2 receive-status pop register changes FIFO state when read.

The remaining hardware questions are external D+/D− routing and VBUS
source/sense behavior. They require board measurements or a controlled powered
enumeration experiment. A powered hub alone is not an established wiring
solution; its upstream power behavior and the box's VBUS path must be understood.

After those questions are resolved and a separate bring-up scope is authorized,
a RAM-only Linux test with an independent console/recovery path can exercise
the host controllers. A known high-speed USB2 peripheral or high-speed hub is a
better initial EHCI test than a directly attached low/full-speed keyboard,
which can require the OHCI companion. Successful host-controller probing must
be followed by actual peripheral enumeration and transfers to establish support.
