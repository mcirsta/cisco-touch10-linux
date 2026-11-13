/* SPDX-License-Identifier: GPL-2.0-only */
/* ARM zImage-shaped watchdog handoff test. No storage, clock or power writes.
 * Emits one marker through the already configured UART3, then stalls until
 * the independently armed hardware watchdog restores normal eMMC boot.
 */
.syntax unified
.arm
.section .text
.global _start
_start:
    b code
    .rept 8
    nop
    .endr
    .word 0x016f2818
    .word 0
    .word image_end - _start
code:
    cpsid if
    movw r4, #0x0000
    movt r4, #0x4802
    adr r5, message
next_character:
    ldrb r0, [r5], #1
    cmp r0, #0
    beq stall
    mov r2, #0x100000
poll_uart:
    ldr r1, [r4, #0x14]
    tst r1, #0x20
    bne send_character
    subs r2, r2, #1
    bne poll_uart
    b stall
send_character:
    str r0, [r4]
    b next_character
stall:
    b stall
message:
    .asciz "TOUCH10_KEXEC_RAM_STALL\r\n"
    .balign 4
image_end:
