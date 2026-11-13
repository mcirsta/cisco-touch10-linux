/* HISTORICAL, INCORRECT ADDRESS. This probes an OMAP4460 reserved region,
 * not its Boot ROM. Do not reuse as a ROM probe.
 * ARM EABI, read-only 16-byte probe at 0x40028000.
 * Uses /dev/mem mmap2 because this kernel's read() path returned EFAULT.
 * Exit status is errno on syscall failure; a bus abort may terminate by signal.
 * The only data transfer after mapping is write(1, mapped_address, 16).
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
    mov     r0, #0              @ chosen virtual address
    mov     r1, #4096           @ one page
    mov     r2, #1              @ PROT_READ
    mov     r3, #1              @ MAP_SHARED
    ldr     r5, =0x40028        @ physical page 0x40028000
    svc     #0
    ldr     r6, =0xfffff001    @ Linux errno return range
    cmp     r0, r6
    bhs     error

    mov     r1, r0              @ mapped ROM bytes
    mov     r0, #1              @ stdout
    mov     r2, #16
    mov     r7, #4              @ write
    svc     #0
    cmp     r0, #16
    bne     error
    mov     r0, #0
    b       exit

error:
    rsb     r0, r0, #0
exit:
    mov     r7, #1              @ exit
    svc     #0

path:
    .asciz  "/dev/mem"
