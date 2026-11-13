// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <alsa/asoundlib.h>

// Choose frame sizes explicitly. The rate plugin can leave a period-time
// interval unresolved in snd_pcm_set_params(); aplay uses explicit sizes.
static inline int perrier_setup_playback(snd_pcm_t *pcm, const char **stage)
{
    snd_pcm_hw_params_t *hw;
    snd_pcm_sw_params_t *sw;
    snd_pcm_uframes_t period = 1024, buffer = 4096;
    snd_pcm_hw_params_alloca(&hw);
    snd_pcm_sw_params_alloca(&sw);
#define PERRIER_SETUP(label, call) do { \
    *stage = label; int result = (call); if (result < 0) return result; \
} while (0)
    PERRIER_SETUP("hardware parameters", snd_pcm_hw_params_any(pcm, hw));
    PERRIER_SETUP("interleaved access", snd_pcm_hw_params_set_access(pcm, hw, SND_PCM_ACCESS_RW_INTERLEAVED));
    PERRIER_SETUP("S16_LE format", snd_pcm_hw_params_set_format(pcm, hw, SND_PCM_FORMAT_S16_LE));
    PERRIER_SETUP("mono channels", snd_pcm_hw_params_set_channels(pcm, hw, 1));
    PERRIER_SETUP("48 kHz rate", snd_pcm_hw_params_set_rate(pcm, hw, 48000, 0));
    PERRIER_SETUP("period frames", snd_pcm_hw_params_set_period_size_near(pcm, hw, &period, NULL));
    PERRIER_SETUP("buffer frames", snd_pcm_hw_params_set_buffer_size_near(pcm, hw, &buffer));
    PERRIER_SETUP("commit hardware parameters", snd_pcm_hw_params(pcm, hw));
    PERRIER_SETUP("read period frames", snd_pcm_hw_params_get_period_size(hw, &period, NULL));
    PERRIER_SETUP("read buffer frames", snd_pcm_hw_params_get_buffer_size(hw, &buffer));
    PERRIER_SETUP("software parameters", snd_pcm_sw_params_current(pcm, sw));
    PERRIER_SETUP("start threshold", snd_pcm_sw_params_set_start_threshold(pcm, sw, buffer));
    PERRIER_SETUP("available frames", snd_pcm_sw_params_set_avail_min(pcm, sw, period));
    PERRIER_SETUP("commit software parameters", snd_pcm_sw_params(pcm, sw));
    PERRIER_SETUP("prepare playback", snd_pcm_prepare(pcm));
#undef PERRIER_SETUP
    return 0;
}
