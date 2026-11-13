#!/bin/sh
# Read only regulator names, voltages/state, consumer debug output, and LCD pads.
set -eu
mounted=0
if ! grep -q ' /sys/kernel/debug debugfs ' /proc/mounts; then
    mount -t debugfs -o ro debugfs /sys/kernel/debug
    mounted=1
fi
trap '[ "$mounted" = 0 ] || umount /sys/kernel/debug' EXIT
uname -r
for regulator in /sys/class/regulator/*; do
    printf '\n%s\n' "$regulator"
    for name in name type microvolts state status num_users; do
        path="$regulator/$name"
        [ -r "$path" ] || continue
        printf '%s=' "$name"
        cat "$path"
    done
    ls -l "$regulator/device" 2>/dev/null || true
done
if [ -d /sys/kernel/debug/regulator ]; then
    for path in /sys/kernel/debug/regulator/* /sys/kernel/debug/regulator/*/*; do
        [ -f "$path" ] || continue
        printf '\n%s\n' "$path"
        cat "$path"
    done
fi
for path in /sys/kernel/debug/omap_mux/*; do
    [ -f "$path" ] || continue
    if grep -Eq 'gpio_(102|151|157|163)([^0-9]|$)|i2c1_' "$path"; then
        printf '\n%s\n' "$path"
        cat "$path"
    fi
done
printf '\nI2C clients\n'
for path in /sys/bus/i2c/devices/*/name; do
    printf '%s=' "$path"
    cat "$path"
done
