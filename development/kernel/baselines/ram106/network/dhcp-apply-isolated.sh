#!/bin/sh
# Apply only the fixed lease on the isolated PC link. Keep 10.77.10.11 intact.
set -eu

present() {
    /bin/ip -4 addr show dev eth0 | /bin/grep -q 'inet 10\.77\.10\.10/24 '
}

case "${1:-}" in
    deconfig)
        if present; then
            /bin/ip addr del 10.77.10.10/24 dev eth0
        fi
        /bin/rm -f /run/dhcp-bound
        echo deconfig > /run/dhcp-event
        ;;
    bound|renew)
        [ "${interface:-}" = eth0 ]
        [ "${ip:-}" = 10.77.10.10 ]
        [ "${subnet:-}" = 255.255.255.0 ]
        [ "$(/bin/ipcalc -p "$ip" "$subnet")" = PREFIX=24 ]
        [ -z "${router:-}" ]
        [ -z "${dns:-}" ]
        if ! present; then
            /bin/ip addr add 10.77.10.10/24 dev eth0
        fi
        printf '%s interface=%s ip=%s subnet=%s lease=%s\n' \
            "$1" "$interface" "$ip" "$subnet" "${lease:-unknown}" > /run/dhcp-bound
        printf '%s\n' "$1" > /run/dhcp-event
        ;;
    *)
        exit 1
        ;;
esac
