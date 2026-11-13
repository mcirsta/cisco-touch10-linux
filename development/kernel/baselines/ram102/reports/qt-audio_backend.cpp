// SPDX-License-Identifier: GPL-2.0-only
#include "audio_backend.h"
#include "pcm_setup.h"
#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace {
constexpr auto volumeName = "Handsfree Playback Volume";
constexpr auto routeName = "Handsfree Right Playback";
constexpr int maximumGain = 24; // Stock HFR setting observed in the factory UI.
}

PerrierAudio::PerrierAudio()
{
    int rc = snd_ctl_open(&m_ctl, "perrier", SND_CTL_NONBLOCK);
    if (rc < 0) {
        m_ctl = nullptr;
        setError(std::string("ALSA control: ") + snd_strerror(rc));
        return;
    }
    snd_ctl_card_info_t *card;
    snd_ctl_card_info_alloca(&card);
    long unused = -1;
    if (snd_ctl_card_info(m_ctl, card) < 0 ||
        std::strcmp(snd_ctl_card_info_get_id(card), "Perrier") ||
        !readControl(volumeName, SND_CTL_ELEM_TYPE_INTEGER, m_initialGain.data(), 2) ||
        !readControl(routeName, SND_CTL_ELEM_TYPE_ENUMERATED, &m_initialRoute, 1) ||
        !readControl("Handsfree Left Playback", SND_CTL_ELEM_TYPE_ENUMERATED, &unused, 1) || unused != 0 ||
        !readControl("Earphone Playback Switch", SND_CTL_ELEM_TYPE_BOOLEAN, &unused, 1) || unused != 0) {
        setError("Unexpected speaker card or output state");
        return;
    }
    snd_ctl_elem_info_t *info;
    snd_ctl_elem_info_alloca(&info);
    snd_ctl_elem_info_set_interface(info, SND_CTL_ELEM_IFACE_MIXER);
    snd_ctl_elem_info_set_name(info, volumeName);
    if (snd_ctl_elem_info(m_ctl, info) < 0 ||
        snd_ctl_elem_info_get_min(info) != 0 || snd_ctl_elem_info_get_max(info) != 29) {
        setError("Unexpected speaker gain range");
        return;
    }
    snd_ctl_elem_info_clear(info);
    snd_ctl_elem_info_set_interface(info, SND_CTL_ELEM_IFACE_MIXER);
    snd_ctl_elem_info_set_name(info, routeName);
    for (unsigned item = 0; item < 2; ++item) {
        snd_ctl_elem_info_set_item(info, item);
        const char *expected = item ? "HF DAC" : "Off";
        if (snd_ctl_elem_info(m_ctl, info) < 0 ||
            std::strcmp(snd_ctl_elem_info_get_item_name(info), expected)) {
            setError("Unexpected speaker route enumeration");
            return;
        }
    }
    m_available = true;
    std::puts("PERRIER_QT_ALSA_READY card=Perrier max_gain=24");
}

PerrierAudio::~PerrierAudio()
{
    stopTest();
    if (m_ctl) {
        if (m_restore) {
            const long off = 0;
            writeControl(routeName, SND_CTL_ELEM_TYPE_ENUMERATED, &off, 1);
            writeControl(volumeName, SND_CTL_ELEM_TYPE_INTEGER, m_initialGain.data(), 2);
            writeControl(routeName, SND_CTL_ELEM_TYPE_ENUMERATED, &m_initialRoute, 1);
        }
        snd_ctl_close(m_ctl);
    }
}

bool PerrierAudio::readControl(const char *name, snd_ctl_elem_type_t type,
                              long *values, unsigned count)
{
    snd_ctl_elem_info_t *info;
    snd_ctl_elem_value_t *value;
    snd_ctl_elem_info_alloca(&info);
    snd_ctl_elem_value_alloca(&value);
    snd_ctl_elem_info_set_interface(info, SND_CTL_ELEM_IFACE_MIXER);
    snd_ctl_elem_info_set_name(info, name);
    snd_ctl_elem_value_set_interface(value, SND_CTL_ELEM_IFACE_MIXER);
    snd_ctl_elem_value_set_name(value, name);
    if (snd_ctl_elem_info(m_ctl, info) < 0 || snd_ctl_elem_info_get_type(info) != type ||
        snd_ctl_elem_info_get_count(info) != count || snd_ctl_elem_read(m_ctl, value) < 0)
        return false;
    for (unsigned i = 0; i < count; ++i)
        values[i] = type == SND_CTL_ELEM_TYPE_ENUMERATED ? snd_ctl_elem_value_get_enumerated(value, i) :
                    type == SND_CTL_ELEM_TYPE_BOOLEAN ? snd_ctl_elem_value_get_boolean(value, i) :
                    snd_ctl_elem_value_get_integer(value, i);
    return true;
}

bool PerrierAudio::writeControl(const char *name, snd_ctl_elem_type_t type,
                               const long *values, unsigned count)
{
    snd_ctl_elem_value_t *value;
    snd_ctl_elem_value_alloca(&value);
    snd_ctl_elem_value_set_interface(value, SND_CTL_ELEM_IFACE_MIXER);
    snd_ctl_elem_value_set_name(value, name);
    for (unsigned i = 0; i < count; ++i) {
        if (type == SND_CTL_ELEM_TYPE_ENUMERATED)
            snd_ctl_elem_value_set_enumerated(value, i, values[i]);
        else
            snd_ctl_elem_value_set_integer(value, i, values[i]);
    }
    if (snd_ctl_elem_write(m_ctl, value) < 0) return false;
    std::array<long, 2> actual{};
    return count <= actual.size() && readControl(name, type, actual.data(), count) &&
           std::equal(actual.begin(), actual.begin() + count, values);
}

bool PerrierAudio::apply(int percent, bool muted)
{
    if (!m_available) return false;
    percent = std::clamp(percent, 0, 100);
    const int gain = (percent * maximumGain + 50) / 100;
    const long route = !muted && percent != 0 ? 1 : 0;
    const std::array<long, 2> gains{m_initialGain[0], gain};
    m_restore = true;
    bool ok = true;
    if (!route) ok = writeControl(routeName, SND_CTL_ELEM_TYPE_ENUMERATED, &route, 1);
    if (ok) ok = writeControl(volumeName, SND_CTL_ELEM_TYPE_INTEGER, gains.data(), 2);
    if (ok && route) ok = writeControl(routeName, SND_CTL_ELEM_TYPE_ENUMERATED, &route, 1);
    if (!ok) {
        const long off = 0;
        writeControl(routeName, SND_CTL_ELEM_TYPE_ENUMERATED, &off, 1);
        setError("Speaker mixer write/readback failed");
        m_available = false;
        return false;
    }
    m_gain = gain;
    m_route = route;
    std::printf("PERRIER_QT_ALSA_APPLIED volume=%d muted=%d gain=%d route=%ld verified=1\n",
                percent, muted, gain, route);
    std::fflush(stdout);
    return true;
}

void PerrierAudio::setError(const std::string &message)
{
    std::lock_guard<std::mutex> lock(m_errorMutex);
    m_error = message;
    std::fprintf(stderr, "PERRIER_QT_ALSA_ERROR %s\n", message.c_str());
}

std::string PerrierAudio::error() const
{
    std::lock_guard<std::mutex> lock(m_errorMutex);
    return m_error;
}

void PerrierAudio::stopTest()
{
    m_stop = true;
    if (m_worker.joinable()) m_worker.join();
}

void PerrierAudio::toggleTest()
{
    if (playing()) { stopTest(); return; }
    if (!available()) return;
    if (m_worker.joinable()) m_worker.join();
    m_stop = false;
    m_frames = 0;
    {
        std::lock_guard<std::mutex> lock(m_errorMutex);
        m_error.clear();
    }
    m_playing = true;
    m_worker = std::thread(&PerrierAudio::playback, this);
}

void PerrierAudio::playback()
{
    snd_pcm_t *pcm = nullptr;
    const char *stage = "open default PCM";
    int rc = snd_pcm_open(&pcm, "default", SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);
    if (rc >= 0)
        rc = perrier_setup_playback(pcm, &stage);
    if (rc < 0) {
        setError(std::string("48 kHz ") + stage + ": " + snd_strerror(rc));
    } else {
        std::puts("PERRIER_QT_AUDIO_TEST_START rate=48000 channels=1 format=S16_LE seconds=30");
        std::fflush(stdout);
        std::array<short, 480> data{};
        constexpr unsigned total = 48000 * 30;
        unsigned written = 0;
        unsigned recoveries = 0;
        while (!m_stop && written < total) {
            for (unsigned i = 0; i < data.size(); ++i) {
                const unsigned sample = written + i;
                const unsigned phase = sample % 48000;
                const double envelope = phase < 19200 ?
                    std::min({1.0, phase / 480.0, (19200 - phase) / 480.0}) : 0.0;
                data[i] = static_cast<short>(2048 * envelope * std::sin(6.283185307179586 * 660 * sample / 48000));
            }
            unsigned offset = 0;
            while (!m_stop && offset < data.size()) {
                snd_pcm_sframes_t count = snd_pcm_writei(pcm, data.data() + offset, data.size() - offset);
                if (count > 0) {
                    offset += count;
                    written += count;
                    m_frames = written;
                } else if (count == -EAGAIN || count == 0) {
                    snd_pcm_wait(pcm, 50);
                } else if (++recoveries > 3 || snd_pcm_recover(pcm, count, 1) < 0) {
                    setError(std::string("Audio write: ") + snd_strerror(count));
                    m_stop = true;
                }
            }
        }
        std::printf("PERRIER_QT_AUDIO_TEST_END frames=%u stopped=%d recoveries=%u\n",
                    written, m_stop.load(), recoveries);
        std::fflush(stdout);
    }
    if (pcm) { snd_pcm_drop(pcm); snd_pcm_close(pcm); }
    m_playing = false;
}
