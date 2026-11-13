#!/bin/sh
# Read-only evidence for the DT-managed external USB PHY and Ethernet.
set -eu
uname -r
cat /run/guard.json
cat /sys/bus/usb/devices/1-1/idVendor /sys/bus/usb/devices/1-1/idProduct /sys/bus/usb/devices/1-1/speed
cat /sys/class/net/eth0/address /sys/class/net/eth0/carrier
cat /sys/class/net/eth0/statistics/rx_packets /sys/class/net/eth0/statistics/tx_packets
cat /sys/kernel/debug/gpio
grep -E 'auxclk1|sys_clkin_ck' /sys/kernel/debug/clk/clk_summary
for path in /sys/kernel/debug/pinctrl/*4a100040*/pinmux-pins /sys/kernel/debug/pinctrl/*4a100040*/pins; do
    [ -r "$path" ] || continue
    printf '\n%s\n' "$path"
    cat "$path"
done
cat /proc/mounts
dmesg
