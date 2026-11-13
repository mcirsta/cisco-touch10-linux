/* SPDX-License-Identifier: GPL-2.0-only */
/* First U-Boot cold-boot probe. It touches no storage, GPIO or watchdog. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/utsname.h>
#include <unistd.h>

int main(void)
{
    if (getpid() != 1)
        return 2;
    int console = open("/dev/console", O_RDWR);
    if (console >= 0) {
        dup2(console, STDIN_FILENO);
        dup2(console, STDOUT_FILENO);
        dup2(console, STDERR_FILENO);
        if (console > STDERR_FILENO)
            close(console);
    }
    setvbuf(stdout, NULL, _IONBF, 0);
    puts("PERRIER_COLD01_INIT_ENTER");
    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);
    struct utsname system;
    if (!uname(&system))
        printf("PERRIER_COLD01_KERNEL %s %s\n", system.release, system.machine);
    for (int second = 1; second <= 10; ++second) {
        sleep(1);
        if (second == 1 || second == 5 || second == 10)
            printf("PERRIER_COLD01_SECOND %d\n", second);
    }
    puts("PERRIER_COLD01_REBOOT_TO_STOCK");
    sync();
    sleep(1); /* let the UART marker drain */
    reboot(RB_AUTOBOOT);
    perror("PERRIER_COLD01_REBOOT_FAILED");
    return 1; /* PID 1 exit triggers the configured panic=5 reboot */
}
