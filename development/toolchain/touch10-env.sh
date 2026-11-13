#!/bin/bash
# Source this file to use the Touch 10 Cortex-A9 userspace cross compiler.
touch10_toolchain_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../perrier-qt/sources/armv7-eabihf--musl--stable-2026.08-1" && pwd)
export TOUCH10_SYSROOT="$touch10_toolchain_root/arm-buildroot-linux-musleabihf/sysroot"
export CC="$touch10_toolchain_root/bin/arm-buildroot-linux-musleabihf-gcc"
export CXX="$touch10_toolchain_root/bin/arm-buildroot-linux-musleabihf-g++"
export AR="$touch10_toolchain_root/bin/arm-buildroot-linux-musleabihf-ar"
export STRIP="$touch10_toolchain_root/bin/arm-buildroot-linux-musleabihf-strip"
export PKG_CONFIG_SYSROOT_DIR="$TOUCH10_SYSROOT"
export PKG_CONFIG_LIBDIR="$TOUCH10_SYSROOT/usr/lib/pkgconfig:$TOUCH10_SYSROOT/usr/share/pkgconfig"
export TOUCH10_CFLAGS="-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard"
unset touch10_toolchain_root
