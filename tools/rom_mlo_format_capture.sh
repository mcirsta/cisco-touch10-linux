#!/usr/bin/env bash
# Capture one volatile OMAP4 USB image-format test and passive serial output.
set -u
cd /home/marius/ext_proj/touch10 || exit 1

case "${1:-}" in
  mlo) mode=--usbfs-port; label=mlo ;;
  exact-mlo) mode=--usbfs-exact-port; label=exact-mlo ;;
  exact-ppa-2nd) mode=--usbfs-exact-ppa-2nd; label=exact-ppa-2nd ;;
  exact-ppa-2nd-plus4) mode=--usbfs-exact-ppa-2nd-plus4; label=exact-ppa-2nd-plus4 ;;
  2nd) mode=--usbfs-port-2nd-name; label=2nd ;;
  2nd-stream) mode=--usbfs-port-2nd-stream; label=2nd-stream ;;
  foreign-header) mode=--usbfs-foreign-header-only; label=foreign-header ;;
  foreign-header-long) mode=--usbfs-foreign-header-long-length; label=foreign-header-long ;;
  foreign-header-cisco-span) mode=--usbfs-foreign-header-cisco-span; label=foreign-header-cisco-span ;;
  foreign-header-32k) mode=--usbfs-foreign-header-32k; label=foreign-header-32k ;;
  foreign-header-24k) mode=--usbfs-foreign-header-24k; label=foreign-header-24k ;;
  foreign-header-28k) mode=--usbfs-foreign-header-28k; label=foreign-header-28k ;;
  foreign-header-31k) mode=--usbfs-foreign-header-31k; label=foreign-header-31k ;;
  foreign-header-34k) mode=--usbfs-foreign-header-34k; label=foreign-header-34k ;;
  *) echo "Usage: $0 mlo|exact-mlo|exact-ppa-2nd|exact-ppa-2nd-plus4|2nd|2nd-stream|foreign-header|foreign-header-long|foreign-header-cisco-span|foreign-header-32k|foreign-header-24k|foreign-header-28k|foreign-header-31k|foreign-header-34k" >&2; exit 2 ;;
esac
image_path=firmware/reference/image2/MLO
if [[ $label == exact-mlo || $label == exact-ppa-2nd || $label == exact-ppa-2nd-plus4 ]]; then
  image_path=firmware/codec-ce9.9.0/extracted/MLO
fi
if [[ $label == foreign-header || $label == foreign-header-long || $label == foreign-header-cisco-span || $label == foreign-header-32k || $label == foreign-header-24k || $label == foreign-header-28k || $label == foreign-header-31k || $label == foreign-header-34k ]]; then
  image_path=firmware/reference/omapboot/images/lelus/p940-aboot.2nd
fi

serial_path=/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D3081QEX-if00-port0
if [[ ! -e "$serial_path" ]]; then
  echo "Touch 10 FTDI serial node is missing." >&2
  exit 1
fi

rom_port=
for serial_file in /sys/bus/usb/devices/*/serial; do
  [[ -f "$serial_file" ]] || continue
  [[ $(<"$serial_file") == D3081QEX ]] || continue
  ftdi_dir=${serial_file%/serial}
  [[ $(<"$ftdi_dir/idVendor") == 0403 && $(<"$ftdi_dir/idProduct") == 6015 ]] || continue
  ftdi_port=${ftdi_dir##*/}
  [[ $ftdi_port == *-*.1 ]] || continue
  if [[ -n $rom_port ]]; then
    echo "Multiple Touch 10 FTDI nodes found; refusing an ambiguous probe." >&2
    exit 1
  fi
  rom_port=${ftdi_port%.1}.2
done
if [[ -z $rom_port ]]; then
  echo "Touch 10 FTDI sibling path was not found." >&2
  exit 1
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
prefix=evidence/rom-${label}-${stamp}
serial_log=${prefix}-serial.log
serial_error=${prefix}-serial-error.log
usb_log=${prefix}-usb.log
usbmon_pid=
if [[ $label == exact-mlo || $label == exact-ppa-2nd || $label == exact-ppa-2nd-plus4 || $label == 2nd-stream || $label == foreign-header || $label == foreign-header-long || $label == foreign-header-cisco-span || $label == foreign-header-32k || $label == foreign-header-24k || $label == foreign-header-28k || $label == foreign-header-31k || $label == foreign-header-34k ]]; then
  if ! modprobe usbmon; then
    echo 'Could not load usbmon for the continuous-transfer trace.' >&2
    exit 1
  fi
  usbmon_bus=${rom_port%%-*}
  timeout 660s tcpdump -i "usbmon${usbmon_bus}" -s 2048 -U \
    -w "${prefix}-usbmon.pcap" > /dev/null 2> "${prefix}-usbmon-error.log" &
  usbmon_pid=$!
  sleep 0.3
  if ! kill -0 "$usbmon_pid" 2>/dev/null; then
    echo 'usbmon capture did not start.' >&2
    cat "${prefix}-usbmon-error.log" >&2
    exit 1
  fi
fi

timeout 660s python3 tools/serial_probe.py \
  --port "$serial_path" --seconds 655 --log "$serial_log" \
  > /dev/null 2> "$serial_error" &
serial_pid=$!
trap 'kill "$serial_pid" ${usbmon_pid:+"$usbmon_pid"} 2>/dev/null || true; wait "$serial_pid" ${usbmon_pid:+"$usbmon_pid"} 2>/dev/null || true' EXIT
sleep 0.3
if ! kill -0 "$serial_pid" 2>/dev/null; then
  echo 'Serial capture did not start.' >&2
  cat "$serial_error" >&2
  exit 1
fi

echo "Capture active: ${label} on ${rom_port}. Power-cycle the Touch 10 once."
timeout 600s tools/omap_rom_signed_mlo_probe \
  "$image_path" "$mode" "$rom_port" \
  > "$usb_log" 2>&1
result=$?
cat "$usb_log"
echo "Keeping passive serial capture for 45 seconds; logs: $usb_log $serial_log"
sleep 45
exit "$result"
