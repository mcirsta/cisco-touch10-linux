# Touch 10 userspace cross toolchain

The local GCC 15.3 ARMv7 hard-float musl cross compiler is verified and
unpacked by [prepare_sources.py](../perrier-qt/prepare_sources.py). Its archive
SHA-256 is pinned there. The target CPU flags are `-mcpu=cortex-a9
-mfpu=neon -mfloat-abi=hard`; the OMAP4460 has VFPv3, so Cortex-A7/VFPv4
binaries from the Mija project are unsuitable.

For CMake projects, pass
`-DCMAKE_TOOLCHAIN_FILE=$PWD/development/perrier-qt/arm-toolchain.cmake`.
For direct C/C++ builds in Bash, run
`source development/toolchain/touch10-env.sh`, then use `$CC` or `$CXX`
with `$TOUCH10_CFLAGS` and your project's include/library flags.
The Touch 10 Qt source build and QEMU Cortex-A9 preflight are described in
[perrier-qt/README.md](../perrier-qt/README.md).

The kernel image uses Clang/LLVM, while the small static early-init tools
currently use Zig 0.15.2 configured for Cortex-A9. These are independent of
the Qt/userspace cross compiler.
