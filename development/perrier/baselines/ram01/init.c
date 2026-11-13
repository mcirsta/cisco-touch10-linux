/* SPDX-License-Identifier: GPL-2.0-only */
/* PID 1 for an isolated RAM trial. Never opens storage or feeds the watchdog. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/reboot.h>
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

int main(void)
{
    if (getpid() != 1) return 2;
    int console = open("/dev/console", O_RDWR);
    if (console >= 0) {
        dup2(console, 0); dup2(console, 1); dup2(console, 2);
        if (console > 2) close(console);
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("PERRIER_INIT_ENTER ram01\n");
    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);
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
    printf("PERRIER_INIT_READY ram01\n");
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
        if (seconds == 15) {
            static const char marker[] = "PERRIER_SOFT_REBOOT_REQUESTED\n";
            write(1, marker, sizeof(marker) - 1);
            sleep(1); /* let the UART drain before the reset */
            reboot(RB_AUTOBOOT);
            printf("PERRIER_SOFT_REBOOT_FAILED errno=%d\n", errno);
            for (;;) pause(); /* the watchdog remains armed */
        }
    }
}
