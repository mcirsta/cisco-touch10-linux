/* HISTORICAL, INCORRECT ADDRESS: this read targeted an OMAP4460 reserved
 * region and triggered a kernel external abort at physical 0x4002f000.
 * Do not rerun it on the live unit as a ROM probe.
 * ARM EABI, read-only attempt at the wrong 48 KiB address range.
 * It maps 0x40028000..0x40033fff via /dev/mem and streams it to stdout.
 */
    .syntax unified
    .arm
    .global _start
    .text
_start:
    mov     r7, #5              @ open
    adr     r0, path
    mov     r1, #0              @ O_RDONLY
    svc     #0
    cmp     r0, #0
    blt     error
    mov     r4, r0              @ fd

    mov     r7, #192            @ mmap2
    mov     r0, #0
    ldr     r1, =0xc000         @ 48 KiB
    mov     r2, #1              @ PROT_READ
    mov     r3, #1              @ MAP_SHARED
    ldr     r5, =0x40028        @ physical page 0x40028000
    svc     #0
    ldr     r6, =0xfffff001    @ Linux errno return range
    cmp     r0, r6
    bhs     error

    mov     r8, r0              @ next byte to write
    ldr     r9, =0xc000         @ bytes remaining
write_more:
    mov     r0, #1              @ stdout
    mov     r1, r8
    mov     r2, r9
    mov     r7, #4              @ write
    svc     #0
    cmp     r0, #0
    blt     error
    beq     short_write
    add     r8, r8, r0
    subs    r9, r9, r0
    bne     write_more
    mov     r0, #0
    b       exit

short_write:
    mov     r0, #5              @ EIO
    b       exit
error:
    rsb     r0, r0, #0
exit:
    mov     r7, #1              @ exit
    svc     #0

path:
    .asciz  "/dev/mem"
