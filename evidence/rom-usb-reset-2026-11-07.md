# OMAP4460 ROM USB reset during four-byte command receive

Date: 2026-11-07. Target: this Touch 10, ROM USB `0451:d010` on host path
`2-1.1.2`, with the adjacent FTDI service serial interface on `2-1.1.1`.
The ROM under study is the [captured 48 KiB image](omap4460-bootrom-2026-11-07.bin),
SHA-256 `7fd0176dbdf06cfa42f147a5c0a923abb1f2fa269b82d0352fa02a5bd3b8efff`.

## Question and scope

The ROM bus-RESET handler at `0x35bb6`–`0x35bbe` changes USB state but does
not visibly cancel the pending receive descriptor or DMA channel. This test
asked whether the ROM could still accept a four-byte command after a host
USB port reset while it was waiting for that command. It did not test an
oversized transfer, a late DMA write, or code execution.

The [probe](../tools/omap_rom_usb_reset_probe.c) verified the FTDI sibling's
VID/PID and serial `D3081QEX`, then pinned the TI device by physical port,
VID, and PID. It sent only the four-byte GET_ID command `03 00 03 f0`:
twice before reset and once after. Each reply had to be 81 bytes and match
the expected ASIC fields and this unit's MPKH. After the two baseline
replies, the probe waited 10 ms, called `libusb_reset_device` once, reopened
the same physical device, and requested the third ID. A passive serial
capture ran concurrently. The probe sent no image, boot command, storage
command, or serial input. The user cold power-cycled the panel to expose
ROM USB.

## Result

The [successful USB log](rom-usb-reset-20261107T211215Z-usb.log) shows:

| Event | Unix time | Result |
| --- | ---: | --- |
| First GET_ID reply | 1794085959.744453 | 81 bytes; identity matched |
| Second GET_ID reply | 1794085959.744720 | 81 bytes; identity matched |
| Begin host port reset | 1794085959.754798 | One reset of the pinned TI device |
| Reset call returns | 1794085959.906498 | Success after 0.152 s |
| Post-reset GET_ID reply | 1794085959.906974 | 81 bytes; same identity matched |

The [host kernel log](rom-usb-reset-20261107T211215Z-host-kernel.log)
records `0451:d010` enumeration at 1794085959.695703, the EHCI port reset
at 1794085959.818576, and a USB disconnect only at 1794085963.015566,
about three seconds *after* the post-reset reply. Thus the third reply
came from the same ROM USB appearance, not a new cold boot. The panel later
returned to normal Linux; read-only SSH succeeded and reported kernel
`3.4.113+` and boot ID `5b4d0514-dc81-49c4-adba-b5ee44f45d9f`.

The first cold-cycle attempt did not run the experiment: the unprivileged
host process could see the TI device but `libusb_open` returned
`LIBUSB_ERROR_ACCESS`, so it sent no USB request. Its [log](rom-usb-reset-20261107T211012Z-usb.log)
is retained separately. The successful attempt used graphical host
authorization for USB access.

The [concurrent serial capture](rom-usb-reset-20261107T211215Z-serial.log)
contains only three bytes, and the short [post-probe capture](rom-usb-reset-20261107T211215Z-postboot-serial.log)
contains two. The runner stopped the main serial capture when the USB
probe ended, so these logs do not establish the later boot sequence. SSH
establishes that the panel completed a normal boot.

## Interpretation, revised after controller documentation review

The four-byte command path recovered across this host port reset while the
ROM session was still present. That narrows the reset-state hypothesis: a
reset here did not strand the ROM command receiver or immediately fault it.
The [OMAP4460 controller review](bootrom-usb-dma-reset-followup-2026-11-07.md)
established that the ROM enabled RX DMA request mode 1 with a 512-byte
maximum packet. TI specifies that a four-byte packet in that mode takes the
endpoint interrupt/FIFO path; this test therefore did not exercise a DMA
memory write. The successful FIFO copy does imply that the DMA address
register still matched the pending command buffer modulo 65,536, because
the ROM uses that register in its completion check. It does not establish
that DMA enable or count survived. `libusb_reset_device` may also restore
the device configuration before the post-reset bulk transfer; this test
did not isolate SET_CONFIGURATION behavior.

No memory corruption, out-of-bounds write, ROM readback, or execution
advantage was observed. The remaining question is whether MUSB can make a
late or excessive write after reset/disconnect, particularly after a
receive timeout and stack reuse. Answering that requires controller-level
evidence or an instrumented RAM-only test; this three-command probe cannot
resolve it. See the [USB state-machine trace](bootrom-usb-state-machine-2026-11-07.md)
and [memory-sink audit](bootrom-usb-memory-sinks-2026-11-07.md).
