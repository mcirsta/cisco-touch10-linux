#!/usr/bin/env bash
# One bounded, GET_ID-only ROM USB reset trial with passive serial capture.
set -euo pipefail
cd /home/marius/ext_proj/touch10

serial=/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0
[[ -e "$serial" ]] || { echo "Touch 10 serial device missing" >&2; exit 2; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
prefix="evidence/rom-usb-reset-${stamp}"
serial_log="${prefix}-serial.log"
serial_error="${prefix}-serial-error.log"
usb_log="${prefix}-usb.log"

timeout 210s python3 tools/serial_probe.py \
  --port "$serial" --seconds 200 --log "$serial_log" \
  > /dev/null 2> "$serial_error" &
serial_pid=$!
trap 'kill "$serial_pid" 2>/dev/null || true; wait "$serial_pid" 2>/dev/null || true' EXIT
sleep 0.25
kill -0 "$serial_pid" 2>/dev/null || {
  cat "$serial_error" >&2
  echo "Serial capture failed" >&2
  exit 2
}

echo "READY: passive serial capture and pinned ROM probe; logs $serial_log $usb_log"
set +e
timeout 190s stdbuf -oL tools/omap_rom_usb_reset_probe --run 2-1.1.2 \
  > "$usb_log" 2>&1
result=$?
set -e
cat "$usb_log"
echo "Serial log: $serial_log"
exit "$result"
