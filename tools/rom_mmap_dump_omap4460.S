/* Bounded read of the 48 KiB OMAP4460 Boot ROM, 0x40030000..0x4003bfff.
 * Each 4 KiB page is mapped read-only and copied into a stack buffer using
 * user-mode loads. Only the RAM buffer is passed to write(2), avoiding a
 * kernel copy_from_user fault on a device mapping. Each complete page is
 * emitted before the next page is touched. If an inaccessible page causes
 * SIGBUS/SIGSEGV, the PC retains only preceding complete pages.
 * ARM Linux EABI, no libc; stdout is 49,152 bytes on success.
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
    blt     failed
    mov     r4, r0              @ fd

    sub     sp, sp, #4096       @ one-page RAM output buffer
    ldr     r10, =0x40030      @ first physical page
    mov     r11, #12           @ exactly 12 pages = 48 KiB
    ldr     r12, =0xfffff001   @ first negative Linux errno

page:
    mov     r7, #192           @ mmap2
    mov     r0, #0             @ chosen virtual address
    mov     r1, #4096          @ one page
    mov     r2, #1             @ PROT_READ
    mov     r3, #1             @ MAP_SHARED
    mov     r5, r10            @ physical page number
    svc     #0
    cmp     r0, r12
    bhs     failed
    mov     r6, r0             @ mapped page

    mov     r8, sp             @ RAM buffer cursor
    mov     r9, #1024          @ 1024 aligned words per page
copy_word:
    ldr     r0, [r6], #4       @ user-mode ROM read; may signal
    str     r0, [r8], #4
    subs    r9, r9, #1
    bne     copy_word

    mov     r8, sp             @ output cursor
    mov     r9, #4096          @ remaining bytes in page
write_page:
    mov     r0, #1             @ stdout
    mov     r1, r8
    mov     r2, r9
    mov     r7, #4             @ write
    svc     #0
    cmp     r0, #0
    ble     failed
    add     r8, r8, r0
    sub     r9, r9, r0
    cmp     r9, #0
    bne     write_page

    add     r10, r10, #1
    subs    r11, r11, #1
    bne     page
    mov     r0, #0
    b       exit

failed:
    mov     r0, #1
exit:
    mov     r7, #1             @ exit
    svc     #0

path:
    .asciz  "/dev/mem"
