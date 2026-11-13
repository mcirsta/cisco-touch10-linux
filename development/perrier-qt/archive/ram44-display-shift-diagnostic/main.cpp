// SPDX-License-Identifier: GPL-2.0-only
#include <QGuiApplication>
#include <QQuickView>
#include <QQuickItem>
#include <QSocketNotifier>
#include <QTimer>
#include <QUrl>
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <fcntl.h>
#include <linux/input.h>
#include <memory>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/signalfd.h>
#include <unistd.h>

class RamTouchReader : public QObject {
public:
    explicit RamTouchReader(QQuickItem *root) : m_root(root) {
        if (const char *mode = std::getenv("PERRIER_TOUCH_X_MODE"))
            m_mirror = !std::strcmp(mode, "mirror");
        if (const char *offset = std::getenv("PERRIER_TOUCH_X_OFFSET"))
            m_offset = std::clamp(std::atoi(offset), -300, 300);
        m_root->setProperty("touchTransform",
                            QStringLiteral("%1 offset %2 px").arg(m_mirror ? "mirror" : "direct").arg(m_offset));
        m_fd = open("/dev/input/event0", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        char name[128] = {};
        if (m_fd < 0 || ioctl(m_fd, EVIOCGNAME(sizeof(name)), name) < 0 ||
            QString::fromLatin1(name) != QStringLiteral("Perrier CYTTSP4 RAM touch")) {
            std::fprintf(stderr, "PERRIER_QT_EVDEV_OPEN_ERROR errno=%d name=%s\n", errno, name);
            if (m_fd >= 0) close(m_fd);
            m_fd = -1;
            return;
        }
        m_notifier = new QSocketNotifier(m_fd, QSocketNotifier::Read, this);
        connect(m_notifier, &QSocketNotifier::activated, this, [this] { readEvents(); });
        std::puts("PERRIER_QT_EVDEV_READY event0 raw 1280x800");
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
                if (e.type == EV_ABS && e.code == ABS_MT_TRACKING_ID)
                    m_active = e.value >= 0;
                else if (e.type == EV_ABS && e.code == ABS_MT_POSITION_X)
                    m_x = e.value;
                else if (e.type == EV_ABS && e.code == ABS_MT_POSITION_Y)
                    m_y = e.value;
                else if (e.type == EV_SYN && e.code == SYN_REPORT) {
                    if (m_active && m_x >= 0 && m_x < 1280 && m_y >= 0 && m_y < 800) {
                        int mapped = std::clamp((m_mirror ? 1279 - m_x : m_x) + m_offset, 0, 1279);
                        int alternate = std::clamp((m_mirror ? m_x : 1279 - m_x) + m_offset, 0, 1279);
                        m_root->setProperty("rawX", m_x);
                        m_root->setProperty("rawY", m_y);
                        m_root->setProperty("mappedX", mapped);
                        m_root->setProperty("alternativeX", alternate);
                        m_root->setProperty("touched", true);
                        m_root->setProperty("reports", ++m_reports);
                        std::printf("PERRIER_QT_EVDEV raw_x=%d mapped_x=%d y=%d reports=%d\n",
                                    m_x, mapped, m_y, m_reports);
                        std::fflush(stdout);
                    }
                }
            }
        }
    }

    QQuickItem *m_root;
    QSocketNotifier *m_notifier = nullptr;
    int m_fd = -1;
    int m_x = -1, m_y = -1, m_reports = 0;
    bool m_active = false;
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
    int centerX = 640;
    if (const char *value = std::getenv("PERRIER_QT_CENTER_X"))
        centerX = std::clamp(std::atoi(value), 20, 1259);
    view.rootObject()->setProperty("centerX", centerX);
    std::printf("PERRIER_QT_CENTER_TARGET x=%d\n", centerX);
    int displayShiftX = 0;
    if (const char *value = std::getenv("PERRIER_QT_DISPLAY_SHIFT_X"))
        displayShiftX = std::clamp(std::atoi(value), -300, 300);
    view.rootObject()->setProperty("displayShiftX", displayShiftX);
    std::printf("PERRIER_QT_DISPLAY_SHIFT x=%d\n", displayShiftX);
    std::unique_ptr<RamTouchReader> touch;
    if (!qEnvironmentVariableIsSet("PERRIER_QT_TEST_NO_TOUCH")) {
        touch = std::make_unique<RamTouchReader>(view.rootObject());
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
