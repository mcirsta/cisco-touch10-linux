#!/bin/bash
# Remove only the development host setup; leave the current data link active.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo or pkexec.' >&2; exit 1; }
systemctl disable --now touch10-dev-dhcp.service
rm -f /etc/systemd/system/touch10-dev-dhcp.service
rm -f /etc/touch10-dev/dnsmasq.conf
rmdir /etc/touch10-dev 2>/dev/null || true
rm -f /etc/udev/rules.d/70-touch10-uart.rules
nmcli connection modify 594ea550-c638-49c0-88de-4d703e86b094 connection.autoconnect no
systemctl daemon-reload
udevadm control --reload-rules
