// SPDX-License-Identifier: GPL-2.0-only
// List and read stock ALSA controls; no playback, capture or control writes.
#include <fcntl.h>
#include <sound/asound.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main(void)
{
	int fd = open("/dev/snd/controlC0", O_RDONLY | O_CLOEXEC);
	if (fd < 0) { perror("ALSA control open"); return 1; }
	struct snd_ctl_card_info card = {0};
	struct snd_ctl_elem_list list = {0};
	if (ioctl(fd, SNDRV_CTL_IOCTL_CARD_INFO, &card) || ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list)) {
		perror("ALSA inventory"); return 1;
	}
	if (!list.count || list.count > 1024) return 1;
	printf("CARD %.32s driver=%.16s controls=%u\n", card.name, card.driver, list.count);
	list.space = list.count;
	list.pids = calloc(list.count, sizeof(*list.pids));
	if (!list.pids || ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list)) { perror("ALSA list"); return 1; }
	for (unsigned i = 0; i < list.used; i++) {
		struct snd_ctl_elem_info info = { .id = list.pids[i] };
		struct snd_ctl_elem_value value = { .id = list.pids[i] };
		if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &info)) continue;
		printf("CONTROL %u %.44s type=%u count=%u", info.id.numid, info.id.name, info.type, info.count);
		if (info.access & SNDRV_CTL_ELEM_ACCESS_READ && !ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &value)) {
			for (unsigned j = 0; j < info.count && j < 16; j++) {
				if (info.type == SNDRV_CTL_ELEM_TYPE_BOOLEAN || info.type == SNDRV_CTL_ELEM_TYPE_INTEGER)
					printf(" %ld", value.value.integer.value[j]);
				else if (info.type == SNDRV_CTL_ELEM_TYPE_ENUMERATED)
					printf(" %u", value.value.enumerated.item[j]);
			}
		}
		putchar('\n');
		if (info.type == SNDRV_CTL_ELEM_TYPE_ENUMERATED && info.value.enumerated.items <= 64) {
			unsigned count = info.value.enumerated.items;
			for (unsigned j = 0; j < count; j++) {
				info.value.enumerated.item = j;
				if (!ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &info))
					printf("ENUM %u %u %.64s\n", info.id.numid, j, info.value.enumerated.name);
			}
		}
	}
	free(list.pids); close(fd);
	return 0;
}
