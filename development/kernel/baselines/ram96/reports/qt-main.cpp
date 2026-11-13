// SPDX-License-Identifier: GPL-2.0-only
#include <QGuiApplication>
#include <QQuickView>
#include <QQuickItem>
#include <QSocketNotifier>
#include <QTimer>
#include <QUrl>
#include <QStringList>
#include <algorithm>
#include <array>
#include <cerrno>
#include <climits>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <linux/gpio.h>
#include <linux/rtc.h>
#include <memory>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/signalfd.h>
#include <unistd.h>

class RamThermals : public QObject {
public:
    explicit RamThermals(QQuickItem *root) : m_root(root) {
        connect(&m_timer, &QTimer::timeout, this, [this] { sample(); });
        sample();
        m_timer.start(2000);
    }

private:
    static QByteArray readText(const QByteArray &path) {
        int fd = open(path.constData(), O_RDONLY | O_CLOEXEC);
        if (fd < 0) return {};
        char buffer[96] = {};
        ssize_t size = read(fd, buffer, sizeof(buffer) - 1);
        close(fd);
        return size > 0 ? QByteArray(buffer, size).trimmed() : QByteArray();
    }

    static int readMillidegrees(const QByteArray &path) {
        const QByteArray value = readText(path);
        if (value.isEmpty()) return INT_MIN;
        char *end = nullptr;
        long parsed = std::strtol(value.constData(), &end, 10);
        return end != value.constData() && *end == '\0' && parsed >= -40000 && parsed <= 150000
               ? int(parsed) : INT_MIN;
    }

    static int findTemperature(const char *pattern, const char *name) {
        glob_t paths = {};
        if (glob(pattern, 0, nullptr, &paths) != 0) return INT_MIN;
        int result = INT_MIN;
        for (size_t i = 0; i < paths.gl_pathc; ++i) {
            QByteArray path(paths.gl_pathv[i]);
            if (readText(path) != name) continue;
            path = path.left(path.lastIndexOf('/')) + "/temp";
            if (std::strstr(pattern, "/hwmon/")) path += "1_input";
            result = readMillidegrees(path);
            if (result != INT_MIN) break;
        }
        globfree(&paths);
        return result;
    }

    static QString display(int milliCelsius) {
        return milliCelsius == INT_MIN ? QStringLiteral("unavailable")
                                      : QString::number(milliCelsius / 1000.0, 'f', 1) + QStringLiteral(" °C");
    }

    void sample() {
        const int cpu = findTemperature("/sys/class/thermal/thermal_zone*/type", "cpu_thermal");
        const int board = findTemperature("/sys/class/hwmon/hwmon*/name", "tmp102");
        m_root->setProperty("cpuTemperature", display(cpu));
        m_root->setProperty("boardTemperature", display(board));
        QStringList power;
        for (int chip = 0x40; chip <= 0x41; ++chip) {
            QByteArray pattern = QByteArray("/sys/bus/i2c/devices/3-00") +
                                 QByteArray::number(chip, 16) + "/hwmon/hwmon*";
            glob_t paths = {};
            const bool found = glob(pattern.constData(), 0, nullptr, &paths) == 0 && paths.gl_pathc == 1;
            for (int channel = 1; channel <= 3; ++channel) {
                QByteArray base = found ? QByteArray(paths.gl_pathv[0]) : QByteArray();
                int mv = found ? readMillidegrees(base + "/in" + QByteArray::number(channel) + "_input") : INT_MIN;
                int ma = found ? readMillidegrees(base + "/curr" + QByteArray::number(channel) + "_input") : INT_MIN;
                QString prefix = QString::number(chip, 16) + "." + QString::number(channel) + "  ";
                power << (mv == INT_MIN || ma == INT_MIN ? prefix + "unavailable" :
                          prefix + QString::number(mv / 1000.0, 'f', 2) + " V  " +
                          QString::number(ma / 1000.0, 'f', 2) + " A");
            }
            globfree(&paths);
        }
        m_root->setProperty("powerReadings", power);
        if (cpu != m_cpu || board != m_board) {
            std::printf("PERRIER_QT_THERMAL cpu_mC=%d board_mC=%d\n", cpu, board);
            std::fflush(stdout);
            m_cpu = cpu;
            m_board = board;
        }
    }

    QQuickItem *m_root;
    QTimer m_timer;
    int m_cpu = INT_MIN + 1;
    int m_board = INT_MIN + 1;
};

class RamAuxStatus : public QObject {
public:
    explicit RamAuxStatus(QQuickItem *root) : m_root(root) {
        connect(&m_timer, &QTimer::timeout, this, [this] { sample(); });
        sample();
        m_timer.start(1000);
    }
private:
    void sample() {
        int fd = open("/dev/rtc0", O_RDONLY | O_CLOEXEC);
        struct rtc_time value = {};
        if (fd >= 0) {
            if (ioctl(fd, RTC_RD_TIME, &value) == 0)
                m_root->setProperty("rtcValue", QString::asprintf("%04d-%02d-%02d  %02d:%02d:%02d",
                    value.tm_year + 1900, value.tm_mon + 1, value.tm_mday,
                    value.tm_hour, value.tm_min, value.tm_sec));
            close(fd);
        }
        for (int index = 0; index < 16; ++index) {
            char path[40];
            std::snprintf(path, sizeof(path), "/dev/gpiochip%d", index);
            fd = open(path, O_RDONLY | O_CLOEXEC);
            if (fd < 0) continue;
            struct gpiochip_info info = {};
            if (ioctl(fd, GPIO_GET_CHIPINFO_IOCTL, &info) || info.lines != 8 || std::strcmp(info.label, "pcf8574")) {
                close(fd);
                continue;
            }
            struct gpio_v2_line_request request = {};
            request.num_lines = 8;
            std::strcpy(request.consumer, "perrier-qt-port");
            // Zero flags preserve direction, drive, bias and output latches.
            for (unsigned i = 0; i < 8; ++i) request.offsets[i] = i;
            if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &request) == 0) {
                struct gpio_v2_line_values levels = {};
                levels.mask = 0xff;
                if (ioctl(request.fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &levels) == 0) {
                    unsigned port = levels.bits & 255;
                    m_root->setProperty("gpioValue", QString::asprintf("0x%02X  ", port) +
                        QString::number(port, 2).rightJustified(8, '0'));
                }
                close(request.fd);
            }
            close(fd);
            break;
        }
    }
    QQuickItem *m_root;
    QTimer m_timer;
};

class RamBacklight {
public:
    explicit RamBacklight(QQuickItem *root) : m_root(root) {
        const int maximum = readNumber("/sys/class/backlight/backlight/max_brightness");
        const int current = readNumber("/sys/class/backlight/backlight/brightness");
        if (maximum != 4 || current < 1 || current > 4) {
            m_root->setProperty("brightnessAvailable", false);
            std::puts("PERRIER_QT_BACKLIGHT_UNAVAILABLE");
            std::fflush(stdout);
            return;
        }
        m_initial = m_level = current;
        m_available = true;
        m_root->setProperty("brightnessLevel", current);
        m_root->setProperty("brightnessAvailable", true);
        std::printf("PERRIER_QT_BACKLIGHT_READY level=%d max=%d\n", current, maximum);
        std::fflush(stdout);
    }

    ~RamBacklight() {
        if (m_available && m_level != m_initial)
            setLevel(m_initial);
    }

    void handleTouch(int x, int y) {
        if (!m_available) return;
        const int left = m_root->property("sliderLeft").toInt();
        const int right = m_root->property("sliderRight").toInt();
        const int top = m_root->property("sliderTop").toInt();
        const int bottom = m_root->property("sliderBottom").toInt();
        if (right <= left || x < left || x > right || y < top || y > bottom)
            return;
        const int level = 1 + ((x - left) * 3 + (right - left) / 2) / (right - left);
        setLevel(std::clamp(level, 1, 4));
    }

private:
    static int readNumber(const char *path) {
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) return -1;
        char data[32] = {};
        ssize_t size = read(fd, data, sizeof(data) - 1);
        close(fd);
        if (size <= 0) return -1;
        char *end = nullptr;
        long value = std::strtol(data, &end, 10);
        return end != data && (*end == '\n' || *end == '\0') ? int(value) : -1;
    }

    void setLevel(int level) {
        if (level == m_level) return;
        int fd = open("/sys/class/backlight/backlight/brightness", O_WRONLY | O_CLOEXEC);
        if (fd < 0) {
            std::fprintf(stderr, "PERRIER_QT_BACKLIGHT_OPEN_ERROR errno=%d\n", errno);
            return;
        }
        char data[4];
        int size = std::snprintf(data, sizeof(data), "%d\n", level);
        ssize_t written = write(fd, data, size);
        int error = errno;
        close(fd);
        if (written != size) {
            std::fprintf(stderr, "PERRIER_QT_BACKLIGHT_WRITE_ERROR errno=%d\n", error);
            return;
        }
        m_level = level;
        m_root->setProperty("brightnessLevel", level);
        std::printf("PERRIER_QT_BACKLIGHT_LEVEL level=%d\n", level);
        std::fflush(stdout);
    }

    QQuickItem *m_root;
    int m_initial = 4;
    int m_level = 4;
    bool m_available = false;
};

class RamMuteLeds {
public:
    RamMuteLeds() {
        // Standard gpio-leds class devices from the Perrier DT. Do not use
        // the vendor LED names, GPIO export, or raw register access.
        for (unsigned i = 0; i < paths.size(); ++i) {
            if (readValue(i, "max_brightness") != 1) return;
            m_initial[i] = readValue(i, "brightness");
            if (m_initial[i] < 0 || m_initial[i] > 1) return;
        }
        m_available = true;
        std::puts("PERRIER_QT_MUTE_LEDS_READY red=GPIO122 green=GPIO119");
    }

    ~RamMuteLeds() {
        if (!m_available) return;
        writeValue(0, 0);
        writeValue(1, 0);
        writeValue(0, m_initial[0]);
        writeValue(1, m_initial[1]);
    }

    bool setMuted(bool muted) const {
        if (!m_available) return false;
        // Switch the old color off before lighting the other channel.
        if (!writeValue(muted ? 1 : 0, 0) || !writeValue(muted ? 0 : 1, 1))
            return false;
        const bool correct = readValue(0, "brightness") == int(muted) &&
                             readValue(1, "brightness") == int(!muted);
        std::printf("PERRIER_QT_MUTE_LEDS muted=%d verified=%d\n", muted, correct);
        std::fflush(stdout);
        return correct;
    }

private:
    static int readValue(unsigned index, const char *attribute) {
        char path[128], buffer[16] = {};
        std::snprintf(path, sizeof(path), "%s/%s", paths[index], attribute);
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) return -1;
        ssize_t count = read(fd, buffer, sizeof(buffer) - 1);
        close(fd);
        if (count <= 0) return -1;
        char *end = nullptr;
        long value = std::strtol(buffer, &end, 10);
        if (end == buffer || (*end != '\n' && *end != '\0') || value < 0 || value > 1)
            return -1;
        return int(value);
    }

    static bool writeValue(unsigned index, int value) {
        char path[128];
        std::snprintf(path, sizeof(path), "%s/brightness", paths[index]);
        int fd = open(path, O_WRONLY | O_CLOEXEC);
        if (fd < 0) return false;
        const char data = value ? '1' : '0';
        bool ok = write(fd, &data, 1) == 1;
        close(fd);
        if (!ok) std::fprintf(stderr, "PERRIER_QT_MUTE_LED_ERROR path=%s\n", path);
        return ok;
    }

    static constexpr std::array<const char *, 2> paths = {
        "/sys/class/leds/red:micmute", "/sys/class/leds/green:micmute"
    };
    std::array<int, 2> m_initial{};
    bool m_available = false;
};

class RamSystemLed {
public:
    RamSystemLed() {
        m_initial = readAttribute("brightness");
        m_available = readAttribute("max_brightness") == 255 && m_initial >= 0 && m_initial <= 255;
        m_on = m_available && m_initial != 0;
    }
    ~RamSystemLed() { if (m_available) writeBrightness(m_initial); }
    bool available() const { return m_available; }
    bool on() const { return m_on; }
    void toggle() {
        if (!m_available) return;
        int level = m_on ? 0 : 10;
        if (writeBrightness(level) && readAttribute("brightness") == level) {
            m_on = level != 0;
            std::printf("PERRIER_QT_SYSTEM_LED brightness=%d verified=1\n", level);
            std::fflush(stdout);
        }
    }
private:
    static int readAttribute(const char *name) {
        char path[128], data[16] = {};
        std::snprintf(path, sizeof(path), "/sys/class/leds/white:status/%s", name);
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) return -1;
        ssize_t size = read(fd, data, sizeof(data) - 1);
        close(fd);
        char *end = nullptr;
        long result = std::strtol(data, &end, 10);
        return size > 0 && end != data && (*end == '\n' || *end == '\0') && result >= 0 && result <= 255 ? int(result) : -1;
    }
    static bool writeBrightness(int level) {
        int fd = open("/sys/class/leds/white:status/brightness", O_WRONLY | O_CLOEXEC);
        if (fd < 0) return false;
        char data[8]; int size = std::snprintf(data, sizeof(data), "%d", level);
        bool ok = write(fd, data, size) == size;
        close(fd);
        return ok;
    }
    int m_initial = 0;
    bool m_available = false, m_on = false;
};

class RamVolumeDemo {
public:
    explicit RamVolumeDemo(QQuickItem *root) : m_root(root) {
        publish();
        m_root->setProperty("muteLedsAvailable", m_leds.setMuted(m_muted));
        m_root->setProperty("whiteLedAvailable", m_white.available());
        m_root->setProperty("whiteLedOn", m_white.on());
    }

    void keypadReady(bool ready) {
        m_root->setProperty("keypadReady", ready);
        std::printf("PERRIER_QT_KEYPAD_%s\n", ready ? "READY" : "UNAVAILABLE");
        std::fflush(stdout);
    }

    void handleKey(unsigned int code, int value) {
        if (code != KEY_VOLUMEDOWN && code != KEY_VOLUMEUP && code != KEY_MUTE)
            return;
        if (value < 0 || value > 2) return;
        const char *name = code == KEY_MUTE ? "mute" :
                           code == KEY_VOLUMEUP ? "volume_up" : "volume_down";
        if (value == 2) {
            ++m_repeatEvents;
            m_root->setProperty("repeatEvents", m_repeatEvents);
        }
        std::printf("PERRIER_QT_KEY_EVENT key=%s code=%u value=%d repeats=%d\n",
                    name, code, value, m_repeatEvents);
        std::fflush(stdout);
        if (value == 0) return;
        if (code == KEY_MUTE) {
            if (value == 1) toggleMute("key");
            return;
        }
        auto now = std::chrono::steady_clock::now();
        if (value == 2 && now - m_lastVolumeRepeat < std::chrono::milliseconds(80))
            return;
        m_lastVolumeRepeat = now;
        const int step = value == 1 ? 5 : 2;
        setVolume(m_volume + (code == KEY_VOLUMEUP ? step : -step), "key");
    }

    void handleTouch(int x, int y, bool newContact) {
        if (newContact && x >= 1020 && x <= 1240 && y >= 578 && y <= 650) {
            m_white.toggle();
            m_root->setProperty("whiteLedOn", m_white.on());
            return;
        }
        const int left = m_root->property("volumeSliderLeft").toInt();
        const int right = m_root->property("volumeSliderRight").toInt();
        const int top = m_root->property("volumeSliderTop").toInt();
        const int bottom = m_root->property("volumeSliderBottom").toInt();
        if (right > left && x >= left && x <= right && y >= top && y <= bottom) {
            const int level = ((x - left) * 100 + (right - left) / 2) / (right - left);
            setVolume(level, "touch");
            return;
        }
        if (newContact && x >= m_root->property("muteLeft").toInt() &&
            x <= m_root->property("muteRight").toInt() &&
            y >= m_root->property("muteTop").toInt() &&
            y <= m_root->property("muteBottom").toInt())
            toggleMute("touch");
    }

private:
    void publish() {
        m_root->setProperty("volumeLevel", m_volume);
        m_root->setProperty("muted", m_muted);
        m_root->setProperty("repeatEvents", m_repeatEvents);
    }

    void setVolume(int volume, const char *source) {
        volume = std::clamp(volume, 0, 100);
        if (volume == m_volume) return;
        m_volume = volume;
        m_root->setProperty("volumeLevel", volume);
        std::printf("PERRIER_QT_VOLUME level=%d muted=%d source=%s\n",
                    volume, m_muted, source);
        std::fflush(stdout);
    }

    void toggleMute(const char *source) {
        m_muted = !m_muted;
        m_root->setProperty("muteLedsAvailable", m_leds.setMuted(m_muted));
        ++m_mutePresses;
        m_root->setProperty("muted", m_muted);
        m_root->setProperty("mutePresses", m_mutePresses);
        std::printf("PERRIER_QT_MUTE muted=%d presses=%d source=%s\n",
                    m_muted, m_mutePresses, source);
        std::fflush(stdout);
    }

    QQuickItem *m_root;
    RamMuteLeds m_leds;
    RamSystemLed m_white;
    int m_volume = 50;
    int m_repeatEvents = 0;
    int m_mutePresses = 0;
    bool m_muted = false;
    std::chrono::steady_clock::time_point m_lastVolumeRepeat{};
};

class RamKeyReader : public QObject {
public:
    explicit RamKeyReader(RamVolumeDemo *volume) : m_volume(volume) {
        for (int index = 0; index < 8; ++index) {
            char path[40], name[128] = {};
            std::snprintf(path, sizeof(path), "/dev/input/event%d", index);
            int candidate = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (candidate < 0) continue;
            if (ioctl(candidate, EVIOCGNAME(sizeof(name)), name) >= 0 &&
                !std::strcmp(name, "4a31c000.keypad")) {
                m_fd = candidate;
                m_path = QString::fromLatin1(path);
                break;
            }
            close(candidate);
        }
        if (m_fd < 0) {
            m_volume->keypadReady(false);
            return;
        }
        m_notifier = new QSocketNotifier(m_fd, QSocketNotifier::Read, this);
        connect(m_notifier, &QSocketNotifier::activated, this, [this] { readEvents(); });
        m_volume->keypadReady(true);
        std::printf("PERRIER_QT_KEYPAD_DEVICE %s\n", m_path.toLocal8Bit().constData());
        std::fflush(stdout);
    }

    ~RamKeyReader() override { if (m_fd >= 0) close(m_fd); }
    bool ready() const { return m_fd >= 0; }

private:
    void readEvents() {
        input_event events[32];
        for (;;) {
            ssize_t n = read(m_fd, events, sizeof(events));
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return;
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0 || n % sizeof(events[0])) {
                std::fprintf(stderr, "PERRIER_QT_KEYPAD_READ_ERROR n=%ld errno=%d\n", (long)n, errno);
                m_notifier->setEnabled(false);
                return;
            }
            for (size_t i = 0; i < size_t(n) / sizeof(events[0]); ++i)
                if (events[i].type == EV_KEY)
                    m_volume->handleKey(events[i].code, events[i].value);
        }
    }

    RamVolumeDemo *m_volume;
    QSocketNotifier *m_notifier = nullptr;
    int m_fd = -1;
    QString m_path;
};

class RamTouchReader : public QObject {
public:
    explicit RamTouchReader(QQuickItem *root, RamBacklight *backlight,
                            RamVolumeDemo *volume)
        : m_root(root), m_backlight(backlight), m_volume(volume) {
        if (const char *mode = std::getenv("PERRIER_TOUCH_X_MODE"))
            m_mirror = !std::strcmp(mode, "mirror");
        if (const char *offset = std::getenv("PERRIER_TOUCH_X_OFFSET"))
            m_offset = std::clamp(std::atoi(offset), -300, 300);
        m_root->setProperty("touchTransform",
                            QStringLiteral("%1 offset %2 px").arg(m_mirror ? "mirror" : "direct").arg(m_offset));
        for (int index = 0; index < 8; ++index) {
            char path[40], name[128] = {};
            input_absinfo x = {}, y = {};
            std::snprintf(path, sizeof(path), "/dev/input/event%d", index);
            int candidate = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (candidate < 0) continue;
            bool rightDevice = ioctl(candidate, EVIOCGNAME(sizeof(name)), name) >= 0 &&
                (QString::fromLatin1(name) == QStringLiteral("Perrier CYTTSP4 RAM touch") ||
                 QString::fromLatin1(name) == QStringLiteral("Cypress CYTTSP4"));
            if (rightDevice && ioctl(candidate, EVIOCGABS(ABS_MT_POSITION_X), &x) >= 0 &&
                ioctl(candidate, EVIOCGABS(ABS_MT_POSITION_Y), &y) >= 0 &&
                x.maximum == 1279 && y.maximum == 799) {
                m_fd = candidate;
                m_path = QString::fromLatin1(path);
                break;
            }
            close(candidate);
        }
        if (m_fd < 0) {
            std::fprintf(stderr, "PERRIER_QT_EVDEV_OPEN_ERROR errno=%d\n", errno);
            return;
        }
        m_notifier = new QSocketNotifier(m_fd, QSocketNotifier::Read, this);
        connect(m_notifier, &QSocketNotifier::activated, this, [this] { readEvents(); });
        std::printf("PERRIER_QT_EVDEV_READY %s raw 1280x800\n", m_path.toLocal8Bit().constData());
        std::fflush(stdout);
    }
    ~RamTouchReader() override { if (m_fd >= 0) close(m_fd); }
    bool ready() const { return m_fd >= 0; }

private:
    void readEvents() {
        struct input_event events[64];
        for (;;) {
            ssize_t n = read(m_fd, events, sizeof(events));
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return;
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0 || n % sizeof(events[0])) {
                std::fprintf(stderr, "PERRIER_QT_EVDEV_READ_ERROR n=%ld errno=%d\n", (long)n, errno);
                m_notifier->setEnabled(false);
                return;
            }
            for (size_t i = 0; i < size_t(n) / sizeof(events[0]); ++i) {
                const auto &e = events[i];
                if (e.type == EV_ABS && e.code == ABS_MT_SLOT &&
                    e.value >= 0 && e.value < static_cast<int>(m_slots.size()))
                    m_slot = e.value;
                else if (e.type == EV_ABS && e.code == ABS_MT_TRACKING_ID) {
                    m_slots[m_slot].active = e.value >= 0;
                    m_slots[m_slot].id = e.value;
                }
                else if (e.type == EV_ABS && e.code == ABS_MT_POSITION_X)
                    m_slots[m_slot].x = e.value;
                else if (e.type == EV_ABS && e.code == ABS_MT_POSITION_Y)
                    m_slots[m_slot].y = e.value;
                else if (e.type == EV_SYN && e.code == SYN_DROPPED) {
                    for (auto &slot : m_slots) slot.active = false;
                    m_lastTouchId = -1;
                    m_desynced = true;
                } else if (e.type == EV_SYN && e.code == SYN_REPORT) {
                    if (m_desynced) { m_desynced = false; continue; }
                    auto selected = std::find_if(m_slots.begin(), m_slots.end(), [](const Slot &slot) {
                        return slot.active && slot.x >= 0 && slot.x < 1280 &&
                               slot.y >= 0 && slot.y < 800;
                    });
                    if (selected != m_slots.end()) {
                        int x = selected->x, y = selected->y;
                        int mapped = std::clamp((m_mirror ? 1279 - x : x) + m_offset, 0, 1279);
                        m_root->setProperty("rawX", x);
                        m_root->setProperty("rawY", y);
                        m_root->setProperty("mappedX", mapped);
                        m_root->setProperty("touched", true);
                        m_root->setProperty("reports", ++m_reports);
                        m_backlight->handleTouch(mapped, y);
                        const bool newContact = selected->id != m_lastTouchId;
                        m_volume->handleTouch(mapped, y, newContact);
                        m_lastTouchId = selected->id;
                        std::printf("PERRIER_QT_EVDEV raw_x=%d mapped_x=%d y=%d reports=%d\n",
                                    x, mapped, y, m_reports);
                        std::fflush(stdout);
                    } else {
                        m_root->setProperty("touched", false);
                        m_lastTouchId = -1;
                    }
                }
            }
        }
    }

    QQuickItem *m_root;
    RamBacklight *m_backlight;
    RamVolumeDemo *m_volume;
    QSocketNotifier *m_notifier = nullptr;
    int m_fd = -1;
    struct Slot { int x = -1, y = -1, id = -1; bool active = false; };
    std::array<Slot, 10> m_slots;
    QString m_path;
    int m_slot = 0, m_reports = 0;
    int m_lastTouchId = -1;
    bool m_desynced = false;
    bool m_mirror = false;
    int m_offset = 0;
};

int main(int argc, char **argv)
{
    sigset_t stopSignals;
    sigemptyset(&stopSignals);
    sigaddset(&stopSignals, SIGINT);
    sigaddset(&stopSignals, SIGTERM);
    if (sigprocmask(SIG_BLOCK, &stopSignals, nullptr) < 0) return 2;
    int signalFd = signalfd(-1, &stopSignals, SFD_NONBLOCK | SFD_CLOEXEC);
    if (signalFd < 0) return 2;
    QGuiApplication app(argc, argv);
    QSocketNotifier signalNotifier(signalFd, QSocketNotifier::Read);
    QObject::connect(&signalNotifier, &QSocketNotifier::activated, &app, [&] {
        signalfd_siginfo signalInfo;
        if (read(signalFd, &signalInfo, sizeof(signalInfo)) == sizeof(signalInfo))
            app.quit();
    });
    QQuickView view;
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    view.setSource(QUrl(QStringLiteral("qrc:/Main.qml")));
    if (view.status() == QQuickView::Error) {
        std::puts("PERRIER_QT_QML_ERROR");
        return 1;
    }
    view.resize(1280, 800);
    view.showFullScreen();
    app.processEvents();
    std::puts("PERRIER_QT_READY touch-grid 1280x800");
    std::fflush(stdout);
    int duration = 50000;
    if (const char *value = std::getenv("PERRIER_QT_DURATION_MS")) {
        int requested = std::atoi(value);
        if (requested == 0 || (requested >= 1000 && requested <= 600000))
            duration = requested;
    }
    view.rootObject()->setProperty("secondsLeft", duration ? duration / 1000 : -1);
    RamBacklight backlight(view.rootObject());
    RamThermals thermals(view.rootObject());
    RamAuxStatus auxStatus(view.rootObject());
    RamVolumeDemo volume(view.rootObject());
    RamKeyReader keys(&volume);
    std::unique_ptr<RamTouchReader> touch;
    if (!qEnvironmentVariableIsSet("PERRIER_QT_TEST_NO_TOUCH")) {
        touch = std::make_unique<RamTouchReader>(view.rootObject(), &backlight, &volume);
        if (!touch->ready()) return 2;
    }
    if (duration)
        QTimer::singleShot(duration, &app, &QCoreApplication::quit);
    int result = app.exec();
    std::printf("PERRIER_QT_EXIT status=%d\n", result);
    std::fflush(stdout);
    signalNotifier.setEnabled(false);
    close(signalFd);
    return result;
}
