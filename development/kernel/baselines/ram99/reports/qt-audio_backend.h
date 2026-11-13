// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <alsa/asoundlib.h>
#include <array>
#include <atomic>
#include <mutex>
#include <string>
#include <thread>

// Native mixer ownership and bounded 48 kHz application playback.
class PerrierAudio {
public:
    PerrierAudio();
    ~PerrierAudio();
    PerrierAudio(const PerrierAudio &) = delete;
    PerrierAudio &operator=(const PerrierAudio &) = delete;

    bool available() const { return m_available; }
    bool apply(int percent, bool muted);
    void toggleTest();
    void stopTest();
    bool playing() const { return m_playing.load(); }
    unsigned long frames() const { return m_frames.load(); }
    std::string error() const;
    int gain() const { return m_gain; }
    int route() const { return m_route; }

private:
    bool readControl(const char *name, snd_ctl_elem_type_t type,
                     long *values, unsigned count);
    bool writeControl(const char *name, snd_ctl_elem_type_t type,
                      const long *values, unsigned count);
    void setError(const std::string &message);
    void playback();

    snd_ctl_t *m_ctl = nullptr;
    bool m_available = false, m_restore = false;
    std::array<long, 2> m_initialGain{};
    long m_initialRoute = 0;
    int m_gain = -1, m_route = -1;
    std::thread m_worker;
    std::atomic<bool> m_stop{false}, m_playing{false};
    std::atomic<unsigned long> m_frames{0};
    mutable std::mutex m_errorMutex;
    std::string m_error;
};
