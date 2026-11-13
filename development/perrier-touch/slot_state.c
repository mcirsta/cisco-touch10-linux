// SPDX-License-Identifier: GPL-2.0-only
/* Read current multitouch tracking IDs without consuming input events. */
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
	struct input_absinfo info;
	int ids[11] = { ABS_MT_TRACKING_ID };
	int fd, i;

	if (argc != 2) {
		fprintf(stderr, "usage: %s /dev/input/eventN\n", argv[0]);
		return 2;
	}
	fd = open(argv[1], O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		perror("open");
		return 1;
	}
	if (ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &info) < 0 || info.minimum != 0 ||
	    info.maximum != 9) {
		perror("EVIOCGABS(ABS_MT_SLOT)");
		close(fd);
		return 1;
	}
	if (ioctl(fd, EVIOCGMTSLOTS(sizeof(ids)), ids) < 0) {
		perror("EVIOCGMTSLOTS");
		close(fd);
		return 1;
	}
	for (i = 1; i < 11; i++)
		printf("slot %d tracking_id %d\n", i - 1, ids[i]);
	close(fd);
	return 0;
}
