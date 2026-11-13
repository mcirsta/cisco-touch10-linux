#!/bin/sh
# Read-only stock GPIO, pinmux, and auxiliary clock inventory.
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
    if grep -Eq 'gpio_(110|158)|fref_clk1_out|usbb1_ulpitll|usbb1_hsic' "$path"; then
        printf '\n%s\n' "$path"
        cat "$path"
    fi
done
if [ -d /sys/kernel/debug/clock ]; then
    for directory in $(find /sys/kernel/debug/clock -type d -name '*auxclk1*'); do
        for path in "$directory"/*; do
            [ -f "$path" ] || continue
            printf '\n%s\n' "$path"
            cat "$path"
        done
    done
fi
