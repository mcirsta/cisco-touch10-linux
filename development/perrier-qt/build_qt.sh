#!/bin/bash
# Build source Qt 6.12 for OMAP4460 with Ninja's default parallelism.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
python3 "$here/prepare_sources.py"
source_root="$here/sources"
base="$source_root/qtbase-everywhere-src-6.12.0"
declarative="$source_root/qtdeclarative-everywhere-src-6.12.0"
cmake -S "$base" -B "$here/build-local-qtbase" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$here/arm-toolchain.cmake" \
  -DCMAKE_INSTALL_PREFIX="$here/qt-arm" -DQT_HOST_PATH=/usr \
  -DCMAKE_BUILD_TYPE=MinSizeRel -DBUILD_SHARED_LIBS=ON \
  -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF -DBUILD_WITH_PCH=OFF \
  -DFEATURE_optimize_size=ON -DINPUT_opengl=no -DFEATURE_vulkan=OFF \
  -DFEATURE_egl=OFF -DFEATURE_eglfs=OFF -DFEATURE_linuxfb=ON \
  -DFEATURE_xcb=OFF -DFEATURE_xlib=OFF -DFEATURE_dbus=OFF \
  -DFEATURE_glib=OFF -DFEATURE_icu=OFF -DFEATURE_fontconfig=OFF \
  -DFEATURE_system_libb2=OFF -DFEATURE_system_md4c=OFF \
  -DFEATURE_libinput=OFF -DFEATURE_libudev=OFF -DFEATURE_tslib=OFF \
  -DFEATURE_xkbcommon=OFF -DFEATURE_openssl=OFF -DFEATURE_cups=OFF \
  -DFEATURE_sql=OFF -DFEATURE_widgets=OFF -DFEATURE_testlib=OFF \
  -DFEATURE_network=OFF -DFEATURE_concurrent=OFF -DFEATURE_xml=OFF \
  -DINPUT_freetype=qt -DINPUT_harfbuzz=qt -DINPUT_libpng=qt \
  -DINPUT_pcre=qt -DINPUT_zlib=qt -DINPUT_doubleconversion=qt
cmake --build "$here/build-local-qtbase"
cmake --install "$here/build-local-qtbase"
cmake -S "$declarative" -B "$here/build-local-qtdeclarative" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$here/arm-toolchain.cmake" \
  -DCMAKE_PREFIX_PATH="$here/qt-arm" -DCMAKE_INSTALL_PREFIX="$here/qt-arm" \
  -DQT_HOST_PATH=/usr -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF -DBUILD_WITH_PCH=OFF \
  -DFEATURE_qml_debug=OFF -DFEATURE_qml_network=OFF \
  -DFEATURE_qml_jit=OFF -DFEATURE_quick_designer=OFF \
  -DFEATURE_quickcontrols2=OFF -DFEATURE_quickdialogs2=OFF \
  -DFEATURE_quick_test=OFF -DFEATURE_quick_particles=OFF \
  -DFEATURE_quick_shapes=OFF -DFEATURE_quick_vectorimage=OFF
cmake --build "$here/build-local-qtdeclarative"
cmake --install "$here/build-local-qtdeclarative"
python3 "$here/../audio/build_application_audio.py"
cmake -S "$here/app" -B "$here/build-arm-a9-local" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$here/arm-toolchain.cmake" \
  -DCMAKE_PREFIX_PATH="$here/qt-arm" -DQT_HOST_PATH=/usr \
  -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build "$here/build-arm-a9-local"
python3 "$here/stage_runtime.py"
python3 "$here/preflight_qemu.py"
