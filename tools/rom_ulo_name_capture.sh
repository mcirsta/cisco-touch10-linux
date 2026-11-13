#!/usr/bin/env bash
# One volatile format comparison against the owner's Touch 10 on USB path 3-1.2.
set -u
cd /home/marius/ext_proj/touch10 || exit 1
serial_log=evidence/rom-ulo-name-serial-2026-11-07.log
serial_error=evidence/rom-ulo-name-serial-error-2026-11-07.log
usb_log=evidence/rom-ulo-name-usb-2026-11-07.log
timeout 240s python3 tools/serial_probe.py \
  --port /dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0 \
  --seconds 235 --log "$serial_log" > /dev/null 2> "$serial_error" &
serial_pid=$!
trap 'kill "$serial_pid" 2>/dev/null || true; wait "$serial_pid" 2>/dev/null || true' EXIT
sleep 0.3
if ! kill -0 "$serial_pid" 2>/dev/null; then
  echo 'Serial capture did not start.' >&2
  cat "$serial_error" >&2
  exit 1
fi
echo 'Serial capture active; ROM USB probe waiting at path 3-1.2.'
timeout 240s tools/omap_rom_signed_mlo_probe \
  firmware/reference/image2/MLO --usbfs-port-ulo-name 3-1.2 \
  > "$usb_log" 2>&1
result=$?
cat "$usb_log"
echo 'Keeping passive serial capture for 45 seconds after USB result.'
sleep 45
exit "$result"
