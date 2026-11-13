/* Bounded OMAP4460 Boot ROM access test.
 * Map only physical 0x40030000 read-only; load one 32-bit word in user mode.
 * A bus/security fault may signal this process. Never stream the mapped
 * address directly to write(2), which would fault inside the kernel.
 * ARM Linux EABI, no libc. stdout is exactly four bytes on success.
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
    mov     r4, r0

    mov     r7, #192            @ mmap2
    mov     r0, #0              @ chosen virtual address
    mov     r1, #4096           @ one page only
    mov     r2, #1              @ PROT_READ
    mov     r3, #1              @ MAP_SHARED
    ldr     r5, =0x40030        @ physical 0x40030000 / 4096
    svc     #0
    ldr     r8, =0xfffff001    @ first negative Linux errno
    cmp     r0, r8
    bhs     error

    ldr     r6, [r0]            @ one user-mode load, possible SIGBUS
    sub     sp, sp, #8
    str     r6, [sp]
    mov     r0, #1              @ stdout
    mov     r1, sp
    mov     r2, #4
    mov     r7, #4              @ write
    svc     #0
    cmp     r0, #4
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
