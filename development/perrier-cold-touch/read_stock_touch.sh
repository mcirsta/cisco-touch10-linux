#!/bin/sh
# Read-only stock touch GPIO and mux inventory. No I2C transactions or GPIO writes.
set -eu
mounted=0
if ! grep -q ' /sys/kernel/debug debugfs ' /proc/mounts; then
    mount -t debugfs -o ro debugfs /sys/kernel/debug
    mounted=1
fi
trap '[ "$mounted" = 0 ] || umount /sys/kernel/debug' EXIT
uname -r
cat /sys/kernel/debug/gpio
for path in /sys/kernel/debug/omap_mux/*; do
    [ -f "$path" ] || continue
    if grep -Eq 'gpio_(120|121|141|142)([^0-9]|$)|i2c2_' "$path"; then
        printf '\n%s\n' "$path"
        cat "$path"
    fi
done
printf '\nInput devices\n'
cat /proc/bus/input/devices
printf '\nTouch client attributes\n'
ls -l /sys/bus/i2c/devices/2-0067/
