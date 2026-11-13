/* SPDX-License-Identifier: GPL-2.0-only */
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) { perror("input open"); return 1; }
    setvbuf(stdout, NULL, _IONBF, 0);
    char name[128] = {0};
    ioctl(fd, EVIOCGNAME(sizeof(name)), name);
    printf("DEVICE %s record_size=%zu\n", name, sizeof(struct input_event));
    for (unsigned code=ABS_MT_POSITION_X; code<=ABS_MT_POSITION_Y; ++code) {
        struct input_absinfo a;
        if (!ioctl(fd, EVIOCGABS(code), &a))
            printf("AXIS %u min=%d max=%d\n", code, a.minimum, a.maximum);
    }
    struct input_event e;
    while (read(fd, &e, sizeof(e)) == sizeof(e))
        printf("EV %lld.%06lld type=%u code=%u value=%d\n",
               (long long)e.input_event_sec, (long long)e.input_event_usec,
               e.type, e.code, e.value);
    return 0;
}
