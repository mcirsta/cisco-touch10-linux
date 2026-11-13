#!/bin/bash
set -euo pipefail
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
expected_commit=0fd0d8e9ea975696fdc05ad267a65f3efd415612
[[ $(git -C "$task_root/kexec-tools" rev-parse HEAD) == "$expected_commit" ]]
[[ $(/home/marius/.local/bin/zig version) == 0.15.2 ]]
cd "$task_root/kexec-tools"
./bootstrap
CC="$task_root/toolchain/arm-cc" LD=ld.lld AS=llvm-as AR=llvm-ar \
    OBJCOPY=llvm-objcopy STRIP=llvm-strip CFLAGS=-O2 LDFLAGS=-static \
    ./configure --build=x86_64-pc-linux-gnu --host=arm-linux-musleabihf \
    --target=arm-linux-musleabihf --without-zlib --without-lzma \
    --without-zstd --without-xen
make
qemu-arm build/sbin/kexec --version
sha256sum build/sbin/kexec
