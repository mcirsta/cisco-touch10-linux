#!/bin/sh
# DHCP state for the volatile RAM image. 10.77.10.11 is a separate rescue IP.
set -eu
set -f

IP=${PERRIER_DHCP_IP_BIN:-/bin/ip}
IPCALC=${PERRIER_DHCP_IPCALC_BIN:-/bin/ipcalc}
GREP=${PERRIER_DHCP_GREP_BIN:-/bin/grep}
RUN=${PERRIER_DHCP_RUN_DIR:-/run}
RESOLV=${PERRIER_DHCP_RESOLV_CONF:-/etc/resolv.conf}
ADDRESS_FILE=$RUN/dhcp-managed-address
GATEWAY_FILE=$RUN/dhcp-managed-gateway

valid_ipv4() {
    case "$1" in ''|.*|*.|*..*|*[!0-9.]*) return 1 ;; esac
    saved_ifs=$IFS
    IFS=.
    set -- $1
    IFS=$saved_ifs
    [ "$#" -eq 4 ] || return 1
    for octet do
        case "$octet" in
            0|[1-9]|[1-9][0-9]|[1-9][0-9][0-9]) ;;
            *) return 1 ;;
        esac
        [ "$octet" -le 255 ] || return 1
    done
}

remove_managed() {
    if [ -f "$GATEWAY_FILE" ]; then
        old_gateway=$(cat "$GATEWAY_FILE")
        "$IP" -4 route del default via "$old_gateway" dev eth0 metric 100 2>/dev/null || :
        rm -f "$GATEWAY_FILE"
    fi
    if [ -f "$ADDRESS_FILE" ]; then
        old_address=$(cat "$ADDRESS_FILE")
        "$IP" -4 addr del "$old_address" dev eth0 2>/dev/null || :
        rm -f "$ADDRESS_FILE"
    fi
    rm -f "$RESOLV" "$RUN/dhcp-bound"
}

case "${1:-}" in
    deconfig)
        remove_managed
        printf '%s\n' deconfig > "$RUN/dhcp-event"
        ;;
    bound|renew)
        event=$1
        [ "${interface:-}" = eth0 ]
        valid_ipv4 "${ip:-}"
        valid_ipv4 "${subnet:-}"
        prefix=$("$IPCALC" -p "$ip" "$subnet")
        case "$prefix" in PREFIX=[0-9]|PREFIX=[0-9][0-9]) ;; *) exit 1 ;; esac
        prefix=${prefix#PREFIX=}
        [ "$prefix" -le 32 ]
        address=$ip/$prefix
        [ "$address" != 10.77.10.11/24 ]

        # Validate every untrusted DHCP token before touching network state.
        set -- ${router:-}
        [ "$#" -le 1 ]
        gateway=${1:-}
        [ -z "$gateway" ] || valid_ipv4 "$gateway"
        set -- ${dns:-}
        [ "$#" -le 3 ]
        for server do valid_ipv4 "$server"; done

        if ! "$IP" -4 addr show dev eth0 | "$GREP" -Fq "inet $address "; then
            "$IP" -4 addr add "$address" dev eth0
        fi
        if [ -f "$ADDRESS_FILE" ]; then
            old_address=$(cat "$ADDRESS_FILE")
            if [ "$old_address" != "$address" ]; then
                "$IP" -4 addr del "$old_address" dev eth0
            fi
        fi
        printf '%s\n' "$address" > "$ADDRESS_FILE"

        if [ -f "$GATEWAY_FILE" ]; then
            old_gateway=$(cat "$GATEWAY_FILE")
            if [ "$old_gateway" != "$gateway" ]; then
                "$IP" -4 route del default via "$old_gateway" dev eth0 metric 100 2>/dev/null || :
                rm -f "$GATEWAY_FILE"
            fi
        fi
        if [ -n "$gateway" ]; then
            "$IP" -4 route replace default via "$gateway" dev eth0 metric 100
            printf '%s\n' "$gateway" > "$GATEWAY_FILE"
        fi

        if [ -n "${dns:-}" ]; then
            : > "$RUN/dhcp-resolv.tmp"
            for server in $dns; do
                printf 'nameserver %s\n' "$server" >> "$RUN/dhcp-resolv.tmp"
            done
            mv "$RUN/dhcp-resolv.tmp" "$RESOLV"
        else
            rm -f "$RESOLV"
        fi
        printf '%s interface=%s ip=%s subnet=%s router=%s dns=%s lease=%s\n' \
            "$event" "$interface" "$ip" "$subnet" "${router:-}" "${dns:-}" \
            "${lease:-unknown}" > "$RUN/dhcp-bound"
        printf '%s\n' "$event" > "$RUN/dhcp-event"
        ;;
    *) exit 1 ;;
esac
