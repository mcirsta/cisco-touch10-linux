/* SPDX-License-Identifier: GPL-2.0-only */
/* PID 1 for an isolated RAM trial. Storage access is read-only; never feeds the watchdog. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/fb.h>
#include <linux/loop.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/socket.h>
#include <sys/statvfs.h>
#include <sys/wait.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

static void show_file(const char *name)
{
    char buf[1024];
    int fd = open(name, O_RDONLY);
    printf("FILE %s\n", name);
    if (fd < 0) { perror(name); return; }
    ssize_t n;
    while ((n = read(fd, buf, sizeof(buf))) > 0) write(1, buf, n);
    close(fd);
    printf("\n");
}

static void show_directory(const char *path)
{
    DIR *dir = opendir(path);
    printf("PERRIER_DIR %s", path);
    if (!dir) { printf(" errno=%d\n", errno); return; }
    struct dirent *item;
    while ((item = readdir(dir)))
        if (item->d_name[0] != '.') printf(" %s", item->d_name);
    closedir(dir);
    printf("\n");
}

static void show_link(const char *path)
{
    char target[256];
    ssize_t n = readlink(path, target, sizeof(target)-1);
    if (n < 0) printf("PERRIER_LINK %s errno=%d\n", path, errno);
    else { target[n] = 0; printf("PERRIER_LINK %s target=%s\n", path, target); }
}

static void probe_native_display_state(void)
{
    show_file("/sys/kernel/debug/devices_deferred");
    show_link("/sys/bus/i2c/devices/2-000f/driver");
    show_link("/sys/bus/platform/devices/58004000.encoder/driver");
    show_link("/sys/bus/platform/devices/58001000.dispc/driver");
    show_link("/sys/bus/platform/devices/58000000.dss/driver");
    show_link("/sys/bus/platform/devices/48059000.gpio/driver");
    show_directory("/sys/class/drm");
}

static void configure_eth0(void)
{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) { printf("PERRIER_ETH_SOCKET errno=%d\n", errno); return; }
    struct ifreq ifr = {0};
    strncpy(ifr.ifr_name, "eth0", IFNAMSIZ - 1);
    if (ioctl(fd, SIOCGIFFLAGS, &ifr) < 0) {
        printf("PERRIER_ETH_ABSENT errno=%d\n", errno);
        close(fd);
        return;
    }
    struct sockaddr_in addr = {.sin_family = AF_INET};
    inet_pton(AF_INET, "10.77.10.10", &addr.sin_addr);
    memcpy(&ifr.ifr_addr, &addr, sizeof(addr));
    int address = ioctl(fd, SIOCSIFADDR, &ifr);
    inet_pton(AF_INET, "255.255.255.0", &addr.sin_addr);
    memcpy(&ifr.ifr_netmask, &addr, sizeof(addr));
    int mask = ioctl(fd, SIOCSIFNETMASK, &ifr);
    ioctl(fd, SIOCGIFFLAGS, &ifr);
    ifr.ifr_flags |= IFF_UP;
    int up = ioctl(fd, SIOCSIFFLAGS, &ifr);
    printf("PERRIER_ETH_CONFIG addr=%d mask=%d up=%d errno=%d\n",
           address, mask, up, errno);
    close(fd);
}

static void read_emmc_boot_sector(void)
{
    const char *path = "/dev/mmcblk0p1";
    uint8_t sector[512];
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) { printf("PERRIER_MMC_READ_OPEN errno=%d\n", errno); return; }
    ssize_t n = read(fd, sector, sizeof(sector));
    close(fd);
    if (n != sizeof(sector)) {
        printf("PERRIER_MMC_READ_SIZE n=%ld errno=%d\n", (long)n, errno);
        return;
    }
    uint32_t crc = ~0u;
    for (size_t i = 0; i < sizeof(sector); ++i) {
        crc ^= sector[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & -(crc & 1u));
    }
    crc = ~crc;
    printf("PERRIER_MMC_P1_CRC32 value=%08x expected=f5c4e784 match=%u\n",
           crc, crc == 0xf5c4e784u);
}

static int probe_stock_base(void)
{
    static int mounted;
    if (!mounted) {
        int result = mount("/dev/mmcblk0p14", "/mnt/base", "ext4",
                           MS_RDONLY | MS_NOATIME | MS_NOSUID | MS_NODEV,
                           "noload");
        printf("PERRIER_BASE_MOUNT result=%d errno=%d options=ro,noload\n",
               result, result ? errno : 0);
        if (result) return 0;
        mounted = 1;
    }
    struct statvfs status;
    int result = statvfs("/mnt/base", &status);
    printf("PERRIER_BASE_RDONLY result=%d ro=%u errno=%d\n",
           result, result ? 0u : !!(status.f_flag & ST_RDONLY),
           result ? errno : 0);
    show_directory("/mnt/base");
    show_directory("/mnt/base/active");
    show_file("/mnt/base/active/version");
    show_file("/mnt/base/active/osversion");
    return result == 0 && (status.f_flag & ST_RDONLY);
}

static void probe_squashfs_image(const char *name, const char *target, int index)
{
    char image[128], device[32];
    snprintf(image, sizeof(image), "/mnt/base/active/%s.img", name);
    snprintf(device, sizeof(device), "/dev/loop%d", index);
    int source = open(image, O_RDONLY | O_CLOEXEC);
    int loop = open(device, O_RDONLY | O_CLOEXEC);
    if (source < 0 || loop < 0) {
        printf("PERRIER_SQUASH_OPEN name=%s errno=%d\n", name, errno);
        if (source >= 0) close(source);
        if (loop >= 0) close(loop);
        return;
    }
    struct loop_config config = {0};
    config.fd = source;
    config.info.lo_flags = LO_FLAGS_READ_ONLY;
    int configured = ioctl(loop, LOOP_CONFIGURE, &config);
    int setup_error = errno;
    close(source);
    if (configured) {
        printf("PERRIER_SQUASH_LOOP name=%s errno=%d\n", name, setup_error);
        close(loop);
        return;
    }
    struct loop_info64 info = {0};
    int loop_ro = ioctl(loop, LOOP_GET_STATUS64, &info) == 0 &&
                  (info.lo_flags & LO_FLAGS_READ_ONLY);
    int result = mount(device, target, "squashfs",
                       MS_RDONLY | MS_NOATIME | MS_NOSUID | MS_NODEV, NULL);
    int mount_error = errno;
    struct statvfs status;
    int fs_ro = result == 0 && statvfs(target, &status) == 0 &&
                (status.f_flag & ST_RDONLY);
    printf("PERRIER_SQUASH_MOUNT name=%s result=%d errno=%d loop_ro=%d fs_ro=%d\n",
           name, result, result ? mount_error : 0, loop_ro, fs_ro);
    if (result) ioctl(loop, LOOP_CLR_FD);
    close(loop);
    if (!result) show_directory(target);
}

static void probe_stock_squashfs(void)
{
    static int mounted;
    if (mounted) return;
    mounted = 1;
    probe_squashfs_image("extra", "/extra", 0);
    probe_squashfs_image("gui", "/gui", 1);
    probe_squashfs_image("apps", "/apps", 2);
}

static void probe_i2c_adapter(unsigned controller, unsigned adapter)
{
    char path[64];
    snprintf(path, sizeof(path), "/sys/bus/i2c/devices/i2c-%u/name", adapter);
    char name[64] = {0};
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        printf("PERRIER_I2C%u_ADAPTER matched=0 errno=%d\n", controller, errno);
        return;
    }
    ssize_t n = read(fd, name, sizeof(name) - 1);
    close(fd);
    if (n <= 0) {
        printf("PERRIER_I2C%u_ADAPTER matched=0 errno=%d\n", controller, errno);
        return;
    }
    name[strcspn(name, "\n")] = 0;
    printf("PERRIER_I2C%u_ADAPTER matched=%d name=%s\n", controller,
           strcmp(name, "OMAP I2C adapter") == 0, name);
}

static void probe_touch_header(void)
{
    static int attempted;
    static int saved_errno;
    static ssize_t saved_count = -1;
    static uint8_t header[16];

    if (!attempted) {
        attempted = 1;
        int fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
        if (fd < 0) {
            saved_errno = errno;
        } else {
            // Match the stock transport: select register zero, then read.
            // This issues no reset, firmware command, rail or GPIO action.
            uint8_t reg = 0;
            if (ioctl(fd, I2C_SLAVE, 0x67) < 0)
                saved_errno = errno;
            else {
                ssize_t selected = write(fd, &reg, 1);
                if (selected != 1)
                    saved_errno = selected < 0 ? errno : EIO;
                else {
                    saved_count = read(fd, header, sizeof(header));
                    if (saved_count != sizeof(header))
                        saved_errno = saved_count < 0 ? errno : EIO;
                }
            }
            close(fd);
        }
    }
    printf("PERRIER_TOUCH_HEADER count=%zd errno=%d data=", saved_count, saved_errno);
    if (saved_count == sizeof(header))
        for (unsigned i = 0; i < sizeof(header); i++) printf("%02x", header[i]);
    printf("\n");
}

static void probe_dispc(int mem)
{
    volatile uint32_t *regs = mem < 0 ? MAP_FAILED :
        mmap(NULL, 4096, PROT_READ, MAP_SHARED, mem, 0x58001000);
    if (regs == MAP_FAILED) {
        printf("PERRIER_DISPC_MAP errno=%d\n", errno);
        return;
    }
    uint32_t line_before = regs[0x5c / 4];
    usleep(10000);
    uint32_t line_after = regs[0x5c / 4];
    printf("PERRIER_DISPC control=%08x gfx_ba0=%08x gfx_ba1=%08x gfx_pos=%08x gfx_size=%08x gfx_attr=%08x line_before=%08x line_after=%08x\n",
           regs[0x40 / 4], regs[0x80 / 4], regs[0x84 / 4],
           regs[0x88 / 4], regs[0x8c / 4], regs[0xa0 / 4],
           line_before, line_after);
    munmap((void *)regs, 4096);
}

static void probe_touch_one_ack(void)
{
    enum { BYTES = 64, SAMPLES = 300, MAX_LOGS = 64 };
    uint8_t current[BYTES], previous[BYTES] = {0};
    int fd = open("/dev/i2c-1", O_RDWR | O_CLOEXEC);
    if (fd < 0 || ioctl(fd, I2C_SLAVE, 0x67) < 0) {
        printf("PERRIER_TOUCH_ONE_ACK_OPEN errno=%d\n", errno);
        if (fd >= 0) close(fd);
        sleep(30);
        return;
    }
    uint8_t reg = 0;
    ssize_t selected = write(fd, &reg, 1);
    ssize_t count = selected == 1 ? read(fd, previous, BYTES) : -1;
    if (count != BYTES || (previous[0] != 0x80 && previous[0] != 0x00)) {
        printf("PERRIER_TOUCH_ONE_ACK_GUARD selected=%zd count=%zd mode=%02x errno=%d\n",
               selected, count, count == BYTES ? previous[0] : 0xff, errno);
        close(fd);
        sleep(30);
        return;
    }
    uint8_t ack[2] = {0, (uint8_t)(previous[0] ^ 0x80)};
    ssize_t sent = write(fd, ack, sizeof(ack));
    printf("PERRIER_TOUCH_ACK mode_before=%02x value=%02x bytes=%zd\n",
           previous[0], ack[1], sent);
    if (sent != sizeof(ack)) {
        close(fd);
        sleep(30);
        return;
    }
    printf("PERRIER_TOUCH_WINDOW_START samples=%u period_ms=100\n", SAMPLES);
    unsigned changes = 0, logged = 0, errors = 0, attempted = 0;
    for (unsigned sample = 0; sample < SAMPLES; ++sample) {
        attempted++;
        reg = 0;
        selected = write(fd, &reg, 1);
        count = selected == 1 ? read(fd, current, BYTES) : -1;
        if (selected != 1 || count != BYTES) {
            printf("PERRIER_TOUCH_RAW_ERROR sample=%u select=%zd read=%zd errno=%d\n",
                   sample, selected, count, errno);
            errors++;
            sleep((SAMPLES - sample + 9) / 10);
            break;
        }
        if (sample == 0 || memcmp(current, previous, BYTES)) {
            if (sample) changes++;
            if (logged < MAX_LOGS) {
                printf("PERRIER_TOUCH_RAW sample=%u data=", sample);
                for (unsigned i = 0; i < BYTES; i++) printf("%02x", current[i]);
                printf("\n");
                logged++;
            }
            memcpy(previous, current, BYTES);
        }
        usleep(100000);
    }
    printf("PERRIER_TOUCH_RAW_DONE samples=%u changes=%u logged=%u errors=%u\n",
           attempted, changes, logged, errors);
    close(fd);
}

static void probe_kms(void)
{
    pid_t child = fork();
    if (child < 0) {
        printf("PERRIER_DRM_PROBE_FORK errno=%d\n", errno);
        return;
    }
    if (child == 0) {
        execl("/kms-probe", "kms-probe", (char *)NULL);
        _exit(127);
    }
    int status = 0;
    if (waitpid(child, &status, 0) < 0)
        printf("PERRIER_DRM_PROBE_WAIT errno=%d\n", errno);
    else
        printf("PERRIER_DRM_PROBE_EXIT status=%d\n", status);
}

static void show_kms_pattern(void)
{
    pid_t child = fork();
    if (child < 0) {
        printf("PERRIER_PATTERN_FORK errno=%d\n", errno);
        return;
    }
    if (child == 0) {
        execl("/kms-pattern", "kms-pattern", (char *)NULL);
        _exit(127);
    }
    int status = 0;
    if (waitpid(child, &status, 0) < 0)
        printf("PERRIER_PATTERN_WAIT errno=%d\n", errno);
    else
        printf("PERRIER_PATTERN_EXIT status=%d\n", status);
}

int main(void)
{
    if (getpid() != 1) return 2;
    int console = open("/dev/console", O_RDWR);
    if (console >= 0) {
        dup2(console, 0); dup2(console, 1); dup2(console, 2);
        if (console > 2) close(console);
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("PERRIER_INIT_ENTER ram26\n");
    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);
    if (mount("debugfs", "/sys/kernel/debug", "debugfs", 0, NULL))
        printf("PERRIER_DEBUGFS_MOUNT errno=%d\n", errno);
    if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL))
        printf("PERRIER_DEVTMPFS_ERROR errno=%d\n", errno);
    struct utsname u;
    if (!uname(&u)) printf("PERRIER_KERNEL %s %s\n", u.release, u.machine);
    show_file("/proc/cmdline");
    show_file("/proc/mounts");
    show_file("/proc/partitions");
    DIR *blocks = opendir("/sys/block");
    int count = 0;
    if (blocks) {
        struct dirent *entry;
        while ((entry = readdir(blocks))) if (entry->d_name[0] != '.') count++;
        closedir(blocks);
    }
    printf("PERRIER_BLOCK_DEVICES %d\n", count);
    // Read-only WDT2 WCRR (counter). No watchdog open/ioctl or MMIO writes.
    int mem = open("/dev/mem", O_RDONLY | O_SYNC);
    volatile uint32_t *clock_page = mem < 0 ? MAP_FAILED :
        mmap(NULL, 4096, PROT_READ, MAP_SHARED, mem, 0x4a307000);
    if (clock_page == MAP_FAILED) perror("timer clock mmap");
    else printf("PERRIER_TIMER1_CLKCTRL value=%08x clksel=%u\n",
                clock_page[0x840 / 4], (clock_page[0x840 / 4] >> 24) & 1);
    volatile uint32_t *timer = mem < 0 ? MAP_FAILED :
        mmap(NULL, 4096, PROT_READ, MAP_SHARED, mem, 0x4a318000);
    if (timer == MAP_FAILED) perror("timer1 mmap");
    else printf("PERRIER_TIMER1_REGS tidr=%08x sysc=%08x tclr=%08x tcrr=%08x tldr=%08x tsicr=%08x\n",
                timer[0], timer[0x10 / 4], timer[0x24 / 4],
                timer[0x28 / 4], timer[0x2c / 4], timer[0x40 / 4]);
    volatile uint32_t *wdt = mem < 0 ? MAP_FAILED :
        mmap(NULL, 4096, PROT_READ, MAP_SHARED, mem, 0x4a314000);
    if (wdt == MAP_FAILED) perror("watchdog counter mmap");
    else {
        uint32_t before = wdt[0x28 / 4];
        unsigned remaining = sleep(1);
        printf("PERRIER_SLEEP_RESULT remaining=%u\n", remaining);
        uint32_t after = wdt[0x28 / 4];
        printf("PERRIER_WDT_RUNNING before=%08x after=%08x delta=%u\n",
               before, after, after - before);
    }
    show_directory("/sys/bus/usb/devices");
    show_directory("/sys/class/net");
    show_directory("/sys/bus/mmc/devices");
    show_directory("/sys/bus/i2c/devices");
    show_directory("/sys/class/drm");
    show_directory("/dev/dri");
    show_file("/sys/class/drm/card0/dev");
    show_file("/sys/class/drm/card0-Unknown-1/status");
    show_file("/sys/class/drm/card0-Unknown-1/modes");
    probe_i2c_adapter(2, 1);
    probe_i2c_adapter(3, 2);
    show_file("/sys/bus/mmc/devices/mmc0:0001/cid");
    show_file("/sys/block/mmcblk0/ro");
    configure_eth0();
    printf("PERRIER_INIT_READY ram26\n");
    unsigned seconds = 0;
    for (;;) {
        unsigned remaining = sleep(5);
        if (remaining) {
            printf("PERRIER_SLEEP_ERROR remaining=%u errno=%d\n", remaining, errno);
            for (;;) { /* watchdog will restore the factory kernel */ }
        }
        seconds += 5;
        if (wdt != MAP_FAILED)
            printf("PERRIER_WDT_TICK t=%u counter=%08x\n", seconds, wdt[0x28 / 4]);
        else printf("PERRIER_WAIT t=%u\n", seconds);
        if (seconds == 5 || seconds == 15) {
            show_directory("/sys/bus/usb/devices");
            show_directory("/sys/class/net");
            show_directory("/sys/bus/mmc/devices");
            show_directory("/sys/bus/i2c/devices");
            probe_i2c_adapter(2, 1);
            probe_i2c_adapter(3, 2);
            probe_touch_header();
            probe_native_display_state();
            if (seconds == 5) {
                // Native DRM owns DISPC and its clocks. Direct /dev/mem
                // reads hung on ram19 before a driver acquired those clocks.
                show_directory("/sys/class/drm");
                show_directory("/dev/dri");
                show_file("/sys/class/drm/card0/dev");
                show_file("/sys/class/drm/card0-Unknown-1/status");
                show_file("/sys/class/drm/card0-Unknown-1/modes");
                probe_kms();
                show_kms_pattern();
                // Keep touch idle while bringing up the LCD path.
            }
            show_file("/sys/bus/mmc/devices/mmc0:0001/cid");
            show_file("/proc/partitions");
            show_file("/sys/block/mmcblk0/ro");
            read_emmc_boot_sector();
            if (probe_stock_base()) probe_stock_squashfs();
            configure_eth0();
        }
        if (seconds == 30) {
            static const char marker[] = "PERRIER_SOFT_REBOOT_REQUESTED\n";
            write(1, marker, sizeof(marker) - 1);
            sleep(1); /* let the UART drain before the reset */
            reboot(RB_AUTOBOOT);
            printf("PERRIER_SOFT_REBOOT_FAILED errno=%d\n", errno);
            for (;;) pause(); /* the watchdog remains armed */
        }
    }
}
