cmake_minimum_required(VERSION 3.21)
project(PerrierTouchGrid VERSION 0.1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(Qt6 6.12 REQUIRED COMPONENTS Core Gui Qml Quick)
find_package(Threads REQUIRED)
set(PERRIER_ALSA_PREFIX "${CMAKE_CURRENT_SOURCE_DIR}/../../audio/app-install/usr"
    CACHE PATH "Touch10 ALSA target installation")
qt_add_executable(perrier-touch-grid main.cpp audio_backend.cpp)
target_include_directories(perrier-touch-grid PRIVATE "${PERRIER_ALSA_PREFIX}/include")
target_link_libraries(perrier-touch-grid PRIVATE Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick
    "${PERRIER_ALSA_PREFIX}/lib/libasound.so" Threads::Threads)
set_target_properties(perrier-touch-grid PROPERTIES
    BUILD_WITH_INSTALL_RPATH TRUE INSTALL_RPATH "$ORIGIN/../lib")
qt_add_resources(perrier-touch-grid "ui" PREFIX "/" FILES Main.qml)
