// SPDX-License-Identifier: GPL-2.0-only
// Exercise the Qt app's exact setup function with three seconds of silence.
#include "../perrier-qt/app/pcm_setup.h"
#include <errno.h>
#include <stdio.h>

int main(void)
{
    snd_pcm_t *pcm = NULL;
    const char *stage = "open";
    int result = snd_pcm_open(&pcm, "default", SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
    if (result >= 0) result = perrier_setup_playback(pcm, &stage);
    if (result < 0) {
        fprintf(stderr, "SETUP_FAIL %s: %s\n", stage, snd_strerror(result));
        if (pcm) snd_pcm_close(pcm);
        return 1;
    }
    snd_output_t *output;
    snd_output_stdio_attach(&output, stdout, 0);
    snd_pcm_dump(pcm, output);
    snd_output_close(output);
    short silence[480] = {0};
    unsigned frames = 0;
    while (frames < 144000) {
        unsigned remaining = 144000 - frames;
        snd_pcm_sframes_t count = snd_pcm_writei(pcm, silence, remaining < 480 ? remaining : 480);
        if (count > 0) frames += count;
        else if (count == -EAGAIN) snd_pcm_wait(pcm, 50);
        else { fprintf(stderr, "WRITE_FAIL %ld\n", count); snd_pcm_close(pcm); return 1; }
    }
    snd_pcm_drop(pcm);
    snd_pcm_close(pcm);
    printf("SETUP_PASS frames=%u\n", frames);
    return 0;
}
