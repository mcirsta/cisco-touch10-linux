#!/usr/bin/env python3
"""One-shot Touch 10 SSDP discovery probe; no pairing or firmware service.

Only the target's M-SEARCH receives one unicast response. The advertised HTTP
URL returns 404 by default. With --benign-description it returns a small
non-Cisco UPnP description. No control, pairing, or upgrade endpoint is served.
"""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import socket
import struct
import threading
import time
import uuid


SEARCH_TARGET = b"ST: urn:schemas-upnp-org:device:Basic:1"
MULTICAST_IP = "239.255.255.250"
HTTP_PORT = 18080
DESCRIPTION = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
               f'<root xmlns="urn:schemas-upnp-org:device-1-0">'
               f'<specVersion><major>1</major><minor>0</minor></specVersion>'
               f'<URLBase>http://HOST_IP_PLACEHOLDER:{HTTP_PORT}/</URLBase>'
               f'<device>'
               f'<deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>'
               f'<friendlyName>Touch10 local test device</friendlyName>'
               f'<manufacturer>Local test</manufacturer>'
               f'<manufacturerURL>http://HOST_IP_PLACEHOLDER:{HTTP_PORT}/probe-only</manufacturerURL>'
               f'<modelDescription>Discovery probe only</modelDescription>'
               f'<modelName>Discovery only</modelName>'
               f'<modelNumber>1</modelNumber>'
               f'<modelURL>http://HOST_IP_PLACEHOLDER:{HTTP_PORT}/probe-only</modelURL>'
               f'<UDN>uuid:9bc58e80-7f2d-4c3b-8589-9b91a300a610</UDN>'
               f'<serialNumber>LOCALTEST</serialNumber>'
               f'<UPC>000000000000</UPC>'
               f'<presentationURL>/probe-only</presentationURL>'
               f'</device></root>\n').encode('utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--host-ip", default="192.168.1.151")
    parser.add_argument("--location-hostname",
                        help="DNS name resolving to --host-ip for the SSDP LOCATION URL")
    parser.add_argument("--target-ip", default="192.168.1.161")
    parser.add_argument("--ipv6-interface", help="listen for IPv6 SSDP on this interface")
    parser.add_argument("--ipv6-target", help="IPv6 link-local address of the target")
    parser.add_argument("--benign-description", action="store_true")
    parser.add_argument("--friendly-name-length", type=int)
    parser.add_argument("--serial-number-length", type=int)
    parser.add_argument("--external-dtd", action="store_true")
    parser.add_argument("--codec-labels", action="store_true",
                        help="use Cisco-like display labels but no codec services or upgrade endpoints")
    parser.add_argument("--codec-presentation", action="store_true",
                        help="advertise an inert local codec-pairing presentation URL")
    args = parser.parse_args()
    host_ip = args.host_ip
    target_ip = args.target_ip
    for address in (host_ip, target_ip):
        try:
            socket.inet_aton(address)
        except OSError:
            parser.error(f"invalid IPv4 address: {address}")
    if bool(args.ipv6_interface) != bool(args.ipv6_target):
        parser.error("--ipv6-interface and --ipv6-target must be used together")
    if args.location_hostname:
        try:
            args.location_hostname.encode("ascii")
        except UnicodeEncodeError:
            parser.error("--location-hostname must be ASCII")
        if (len(args.location_hostname) > 253 or
                any(not label or len(label) > 63 or
                    not all(char.isalnum() or char == "-" for char in label)
                    for label in args.location_hostname.split("."))):
            parser.error("--location-hostname must be a valid DNS hostname")
    if args.codec_presentation and not args.benign_description:
        parser.error("--codec-presentation requires benign XML")
    if args.ipv6_target:
        try:
            socket.inet_pton(socket.AF_INET6, args.ipv6_target)
            ipv6_ifindex = socket.if_nametoindex(args.ipv6_interface)
        except OSError as exc:
            parser.error(str(exc))
    if args.friendly_name_length is not None:
        if not args.benign_description or not 1 <= args.friendly_name_length <= 300:
            parser.error("--friendly-name-length requires --benign-description and 1..300")
    if args.serial_number_length is not None:
        if not args.benign_description or not 1 <= args.serial_number_length <= 300:
            parser.error("--serial-number-length requires --benign-description and 1..300")
    events = []
    location_host = args.location_hostname or host_ip
    probe_uuid = str(uuid.uuid4())
    probe_path = f"/touch10-discovery-probe-{probe_uuid}.xml"
    dtd_path = f"/touch10-discovery-probe-{probe_uuid}.dtd"
    description = DESCRIPTION.replace(b"9bc58e80-7f2d-4c3b-8589-9b91a300a610",
                                      probe_uuid.encode("ascii"))
    description = description.replace(b"HOST_IP_PLACEHOLDER", host_ip.encode("ascii"))
    if args.codec_labels:
        description = description.replace(b"Touch10 local test device",
                                          b"Cisco TelePresence test codec")
        description = description.replace(b"Local test", b"Cisco Systems, Inc.")
        description = description.replace(b"Discovery only", b"Cisco TelePresence")
        description = description.replace(b"Discovery probe only", b"Discovery test only")
    if args.codec_presentation:
        description = description.replace(b"<presentationURL>/probe-only</presentationURL>",
                                          f"<presentationURL>http://{host_ip}:4053/</presentationURL>".encode("ascii"))
    if args.friendly_name_length is not None:
        display_name = (b"Cisco TelePresence test codec" if args.codec_labels
                        else b"Touch10 local test device")
        description = description.replace(display_name,
                                          b"A" * args.friendly_name_length)
    if args.serial_number_length is not None:
        description = description.replace(b"LOCALTEST",
                                          b"B" * args.serial_number_length)
    if args.external_dtd:
        if not args.benign_description:
            parser.error("--external-dtd requires --benign-description")
        doctype = (f'<!DOCTYPE root SYSTEM "http://{host_ip}:{HTTP_PORT}{dtd_path}">\n'
                   ).encode("ascii")
        description = description.replace(b"<root ", doctype + b"<root ", 1)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.client_address[0] != target_ip:
                self.send_error(403)
                return
            events.append({"event": "http_get", "path": self.path,
                           "source": self.client_address[0]})
            if args.benign_description and self.path == probe_path:
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(description)))
                self.end_headers()
                self.wfile.write(description)
                events.append({"event": "benign_description_served"})
            elif args.external_dtd and self.path == dtd_path:
                body = b"<!-- local DTD fetch probe -->\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/xml-dtd")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                events.append({"event": "external_dtd_fetched"})
            else:
                self.send_error(404, "Discovery probe only")

        def log_message(self, format, *message_args):
            pass

    server = HTTPServer((host_ip, HTTP_PORT), Handler)
    server.timeout = 0.25
    server_thread = threading.Thread(target=lambda: serve_until_deadline(), daemon=True)
    deadline = time.monotonic() + args.seconds

    def serve_until_deadline() -> None:
        while time.monotonic() < deadline:
            server.handle_request()

    family = socket.AF_INET6 if args.ipv6_interface else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if args.ipv6_interface:
            sock.bind(("::", 1900))
            membership = struct.pack("=16sI", socket.inet_pton(socket.AF_INET6, "ff02::c"),
                                     ipv6_ifindex)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, membership)
        else:
            sock.bind(("", 1900))
            membership = struct.pack("=4s4s", socket.inet_aton(MULTICAST_IP),
                                     socket.inet_aton(host_ip))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.settimeout(0.5)
        server_thread.start()
        sent = False
        while time.monotonic() < deadline:
            try:
                data, peer = sock.recvfrom(4096)
            except socket.timeout:
                continue
            expected = args.ipv6_target if args.ipv6_interface else target_ip
            if sent or peer[0].lower() != expected.lower() or not data.startswith(b"M-SEARCH "):
                continue
            if args.ipv6_interface and peer[3] != ipv6_ifindex:
                continue
            if SEARCH_TARGET not in data:
                continue
            response = ("HTTP/1.1 200 OK\r\n"
                        "CACHE-CONTROL: max-age=30\r\n"
                        "EXT:\r\n"
                        f"LOCATION: http://{location_host}:{HTTP_PORT}{probe_path}\r\n"
                        "SERVER: Touch10-Discovery-Probe/1.0 UPnP/1.0\r\n"
                        "ST: urn:schemas-upnp-org:device:Basic:1\r\n"
                        f"USN: uuid:{probe_uuid}::"
                        "urn:schemas-upnp-org:device:Basic:1\r\n\r\n").encode("ascii")
            sock.sendto(response, peer)
            sent = True
            events.append({"event": "ssdp_response", "source": peer[0],
                           "source_port": peer[1], "destination": host_ip,
                           "probe_uuid": probe_uuid,
                           "location": f"http://{location_host}:{HTTP_PORT}{probe_path}"})
            print(f"Sent one discovery-only response to {peer[0]}:{peer[1]}", flush=True)
        server_thread.join(timeout=1)
    finally:
        sock.close()
        server.server_close()
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(json.dumps({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                        "seconds": args.seconds,
                                        "host_ip": host_ip,
                                        "location_hostname": args.location_hostname,
                                        "target_ip": target_ip,
                                        "ipv6_interface": args.ipv6_interface,
                                        "ipv6_target": args.ipv6_target,
                                        "friendly_name_length": args.friendly_name_length,
                                        "serial_number_length": args.serial_number_length,
                                        "external_dtd": args.external_dtd,
                                        "codec_labels": args.codec_labels,
                                        "codec_presentation": args.codec_presentation,
                                        "events": events}, indent=2) + "\n")
    print(json.dumps(events, indent=2))


if __name__ == "__main__":
    main()
