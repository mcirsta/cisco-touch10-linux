# Local OMAP4 HS ROM-USB loader inventory

Scope: offline file inventory and byte-level format comparison in the Touch 10 workspace. No panel command or state change was made. The Touch 10 ROM ASIC-ID response contains MPKH `8b846a5a4bd78d86fdbeee1c4ce0ed074e91b9f501f80652d1b6084b1c0fa742`.

The only local `.2nd` images are two reference OMAP4 phone loaders:

| File | Bytes | TOC image | Certificate layout | SHA-256 of 276-byte root key record |
| --- | ---: | --- | --- | --- |
| `firmware/reference/omapboot/images/lelus/p940-aboot.2nd` | 21,552 | `2ND` at `0x1a00`, size `0x3a30` | `CertPK_` `0x200`, `CertPPA` `0xc00`, `CertISW` `0x1a00` | `5f4092eccddf90fa43f546adf89508b31b9c74795e9516194c0ea6412fdcb7f6` |
| `firmware/reference/omapboot/images/wkpark/su760-aboot.2nd` | 21,504 | `2ND` at `0x1a00`, size `0x3a00` | `CertPK_` `0x200`, `CertPPA` `0xc00`, `CertISW` `0x1a00` | `5f4092eccddf90fa43f546adf89508b31b9c74795e9516194c0ea6412fdcb7f6` |

Both fit the Touch 10 ROM's 32,767-byte type-2 USB receive ceiling, but their root-key hash differs from this panel's burned MPKH. They are unsuitable as an authenticated recovery stage for this unit. Their companion U-Boot/fastboot files belong to those other boards and cannot cure the first-stage key mismatch.

The CE9.9.0 package (`firmware/codec-ce9.9.0/idefix.pkg`) contains one `CertPK_` marker; it belongs to the exact 41,024-byte Cisco `MLO` extracted from that package. This MLO's root-key SHA-256 **does** equal the panel MPKH, but its TOC name is `MLO` and its byte count exceeds the measured type-2 ROM USB ceiling. The saved reference eMMC image likewise contains a Cisco `MLO`, not a second USB-format loader. No file named `dnld_startup_omap4_hs_*`, `ULO`, or other signed Cisco `2ND` was found in the local workspace.

This inventory does not establish that no suitable loader exists elsewhere. It establishes that the two currently local USB-format candidates fail the unit's root-key match, while the locally available matching-key Cisco image has not booted through ROM USB. No board-compatible eMMC-writing recovery stage has been identified locally.
