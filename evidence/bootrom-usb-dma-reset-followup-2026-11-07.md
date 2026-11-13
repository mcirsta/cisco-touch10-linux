# OMAP4460 ROM USB DMA reset follow-up

Date: 2026-11-07. This is an offline interpretation of the already completed
[GET_ID/reset experiment](rom-usb-reset-2026-11-07.md), using this panel's
captured ROM, the OMAP4460 controller documentation, and upstream MUSB code.
No further device command was sent.

## The four-byte test did not exercise an RX DMA write

The ROM's receive descriptor selects its DMA-capable path at `0x33148`.
At `0x35226`–`0x35268`, that path programs endpoint 1 RX DMA control
`0x1d`: channel enable (bit 0), controller DMA mode 1 (bit 2), interrupt
enable (bit 3), and endpoint 1 (bit 4). The corresponding RXCSR setup at
`0x35254`–`0x35260` sets `DMAReqEnab` (bit 13) and `DMAReqMode` (bit 11)
along with `AutoClear`. Configuration 1 programs RXMAXP to `0x0200`
(512 bytes) for high speed at `0x3571e`/`0x3572e`; its packet multiplier
bits are zero. Host enumeration in the live trial was high speed.

[TI's OMAP4460 technical reference manual, §23.12.4.6.3.2, printed p. 5412](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=5412)
states that RX DMA request mode 1 initiates DMA only for a packet equal
to RXMAXP. A shorter packet raises the endpoint interrupt instead.
Consequently each four-byte GET_ID command was handled through the ROM's
residual FIFO path at `0x35454`–`0x354b2` under the documented controller
behavior. The original USB reset result demonstrates protocol recovery,
but **no DMA data transfer** before or after reset. The [Linux MUSB gadget
RX path](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/c7decec2f2d2ab0366567f9e30c0e1418cece43f/drivers/usb/musb/musb_gadget.c#591)
also treats short packets separately from mode-1 DMA; this is corroborating
driver behavior, not the basis for the silicon conclusion.

## What the post-reset reply does constrain

The ROM's residual handler reads channel RX `DMA_ADDR` at `0x4a0ab218`
(`0x3548c`), subtracts the descriptor's saved destination
(`0x35490`), adds RXCOUNT (`0x35496`), truncates the sum to 16 bits
(`0x35498`), and accepts only when it equals the requested count of four.
For the post-reset short GET_ID packet, this requires
`(DMA_ADDR - destination) mod 65536 = 0`. The command destination is a
nonzero-offset stack word under the ROM's `0x4030d000` stack top. A complete
reset of DMA_ADDR to zero would not meet this comparison. Configuration 1
at `0x35704`–`0x35784` does not write DMA_ADDR/COUNT/CONTROL or call the
RX-arm routine, so the successful response indicates that DMA_ADDR stayed
at the pending buffer address (at least modulo 65536), or that the
controller restored an equivalent value. It does **not** establish that
DMA enable or count survived.

The generic [MUSB specification, §9.1](https://linux-sunxi.org/images/7/73/Musbmhdrc.pdf)
says a peripheral USB bus reset flushes endpoint FIFOs and clears endpoint
control/status registers. On this ROM, configuration 1 subsequently
updates RXCSR at `0x3575e`–`0x35776` without setting its DMA request-enable
or request-mode bits; it does not rearm the pending DMA channel. The
post-reset four-byte packet is therefore expected to reach the CPU
residual-FIFO handler. This specification is generic MUSB documentation,
so the live reply is the stronger evidence for the address-register
constraint on this exact unit.

## Memory-write bound and remaining uncertainty

The first command receive programs a four-byte count and a ROM-selected
stack destination. The later image body uses a ROM-selected SRAM
destination and a length checked below 32,768 bytes on this HS unit.
TI's [TRM §23.12.4.6.3.3](https://www.ti.com/lit/ug/swpu235ab/swpu235ab.pdf#page=5412)
describes a programmed channel address and byte count but does not specify
the channel's bus-reset lifetime or an oversized-packet write bound.
The original [Mentor MUSB specification, §17.4.3](https://linux-sunxi.org/images/7/73/Musbmhdrc.pdf)
says a mode-1 DMA transfer exceeding its buffer stops unloading the FIFO
and interrupts the processor. The published [OMAP4460 ES1.1 errata](https://www.ti.com/lit/er/swpz017l/swpz017l.pdf)
do not list an HS USB OTG RX DMA reset/count fault. Those sources support
the programmed-count bound in ordinary operation; they do not prove there
is no silicon-specific race during reset or disconnect.

Upstream Linux's [MUSB DMA abort routine](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+/c7decec2f2d2ab0366567f9e30c0e1418cece43f/drivers/usb/musb/musbhsdma.c#224)
explicitly clears RXCSR DMA bits and DMA control/address/count. The ROM's
bus-RESET branch at `0x35bb6`–`0x35bbe` does not take that software path.
This supports a lifecycle question, but the Linux cleanup does not prove
what the OMAP4460 hardware does to an armed channel on reset.

A host reset during a **full 512-byte body packet** would actually exercise
mode-1 RX DMA. A subsequent USB response or stall would show protocol
behavior, not whether memory was written after the ROM's stack frame was
reused. A decisive memory-safety result needs controller-state and memory
instrumentation, or another direct readout of the affected RAM; none is
available from this ROM USB protocol. Repeating GET_ID/reset cannot answer
that question. The practical research path remains an offline controller
model or a separately reviewed RAM-only diagnostic on this SoC, while the
tested U-Boot RAM boot path remains available for firmware development.
