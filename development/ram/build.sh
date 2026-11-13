#!/bin/bash
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
"$task_root/toolchain/arm-cc" -O2 -static -o "$task_root/ram/arm-watchdog" "$task_root/ram/arm_watchdog.c"
clang --target=arm-none-eabi -mcpu=cortex-a9 -nostdlib -fuse-ld=lld \
    -Wl,-Ttext=0x80008000 -Wl,--build-id=none \
    -o "$task_root/ram/kexec-stall.elf" "$task_root/ram/kexec_stall.S"
llvm-objcopy -O binary "$task_root/ram/kexec-stall.elf" "$task_root/ram/kexec-stall.zImage"
sha256sum "$task_root/ram/arm-watchdog" "$task_root/ram/kexec-stall.zImage"
