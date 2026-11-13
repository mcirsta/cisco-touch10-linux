#!/bin/bash
# One-time, idempotent host setup; never changes the Touch 10 firmware.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run this installer with sudo or pkexec.' >&2; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
profile=594ea550-c638-49c0-88de-4d703e86b094
[[ $(nmcli -g connection.interface-name connection show "$profile") == enp7s0 ]]
[[ $(nmcli -g ipv4.addresses connection show "$profile") == 10.77.10.1/24 ]]
[[ $(nmcli -g ipv4.method connection show "$profile") == manual ]]
dnsmasq --test --conf-file="$source_dir/dnsmasq.conf"
install -d -m 0755 /etc/touch10-dev
install -m 0644 "$source_dir/dnsmasq.conf" /etc/touch10-dev/dnsmasq.conf
install -m 0644 "$source_dir/touch10-dev-dhcp.service" /etc/systemd/system/touch10-dev-dhcp.service
install -m 0644 "$source_dir/70-touch10-uart.rules" /etc/udev/rules.d/70-touch10-uart.rules
nmcli connection modify "$profile" connection.autoconnect yes ipv4.never-default yes
nmcli connection up "$profile"
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty --action=change
udevadm settle
# Apply access immediately as well as through the persistent uaccess rule.
uart=/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0
if [[ -e $uart ]]; then
    [[ $(udevadm info -q property -n "$uart" | sed -n 's/^ID_SERIAL_SHORT=//p') == D3081QEX ]]
    setfacl -m u:marius:rw "$uart"
fi
systemctl daemon-reload
systemctl enable --now touch10-dev-dhcp.service
systemctl --no-pager --full status touch10-dev-dhcp.service
