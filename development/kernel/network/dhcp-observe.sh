#!/bin/sh
# Record the isolated test LAN's DHCP answer without changing the rescue IP.
set -eu

case "${1:-}" in
    deconfig)
        exit 0
        ;;
    bound|renew)
        if [ "${interface:-}" != eth0 ] ||
           [ "${ip:-}" != 10.77.10.10 ] ||
           [ "${subnet:-}" != 255.255.255.0 ]; then
            printf 'unexpected interface=%s ip=%s subnet=%s\n' \
                "${interface:-}" "${ip:-}" "${subnet:-}" > /run/dhcp-lease
            exit 1
        fi
        printf 'bound interface=%s ip=%s subnet=%s lease=%s\n' \
            "$interface" "$ip" "$subnet" "${lease:-unknown}" > /run/dhcp-lease
        ;;
    *)
        exit 1
        ;;
esac
