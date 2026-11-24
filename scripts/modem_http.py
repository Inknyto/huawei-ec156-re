#!/usr/bin/env python3
"""HTTP + raw-TCP bridge for a Huawei EC156 CDMA modem.

The bridge is deliberately dependency-free: it uses the standard library and
the `ec156_modem` module next to this file.  It turns the modem into a
network-accessible AT endpoint for local automation or an IoT gateway.

Security defaults
-----------------
* binds to 127.0.0.1 only
* read-only AT commands unless --allow-write is given
* optional shared token (Authorization: Bearer ... or X-Auth-Token)

Examples
--------
  ./modem_http.py --serial auto --http-port 8080 --tcp-port 9000
  curl -s http://127.0.0.1:8080/api/status | jq
  curl -s 'http://127.0.0.1:8080/api/at?cmd=AT%5ESYSINFO' | jq
  curl -s -X POST http://127.0.0.1:8080/api/sms \
       -H 'Content-Type: application/json' \
       -d '{"to":"+15551234567","text":"hello"}'
  nc 127.0.0.1 9000      # then type: ATI
"""

from __future__ import annotations

import argparse
import json
import socketserver
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ec156_modem import AtModem, ModemError, find_at_port


class State:
    def __init__(self, modem: AtModem, allow_write: bool, token: str | None):
        self.modem = modem
        self.allow_write = allow_write
        self.token = token
        self.lock = threading.RLock()

    def authorized(self, headers) -> bool:
        if not self.token:
            return True
        supplied = headers.get("X-Auth-Token") or ""
        auth = headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return supplied == self.token


STATE: State


class HttpHandler(BaseHTTPRequestHandler):
    server_version = "ec156-modem-api/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, indent=2).encode() + b"\n"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code: int, text: str) -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        if not STATE.authorized(self.headers):
            self._json(401, {"ok": False, "error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._guard():
            return
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/docs"):
            self._text(200, __doc__ or "EC156 modem API")
            return
        if parsed.path == "/health":
            try:
                with STATE.lock:
                    resp = STATE.modem.command("AT", timeout=1.5)
                self._json(200, {"ok": "OK" in resp, "at": resp})
            except Exception as exc:
                self._json(503, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/status":
            try:
                with STATE.lock:
                    self._json(200, STATE.modem.status())
            except Exception as exc:
                self._json(503, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/signal":
            try:
                with STATE.lock:
                    self._json(200, {"ok": True, "response": STATE.modem.command("AT+CSQ")})
            except Exception as exc:
                self._json(503, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/at":
            cmd = (parse_qs(parsed.query).get("cmd") or [""])[0]
            if not cmd:
                self._json(400, {"ok": False, "error": "missing ?cmd="})
                return
            self._run_at(cmd)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._guard():
            return
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"ok": False, "error": "invalid JSON body"})
            return

        if parsed.path == "/api/at":
            self._run_at(str(payload.get("cmd", "")))
            return
        if parsed.path == "/api/sms":
            if not STATE.allow_write:
                self._json(403, {"ok": False, "error": "SMS requires --allow-write"})
                return
            number = str(payload.get("to", "")).strip()
            text = str(payload.get("text", ""))
            if not number or not text:
                self._json(400, {"ok": False, "error": "to and text are required"})
                return
            try:
                with STATE.lock:
                    result = STATE.modem.send_sms(number, text)
                self._json(200 if result.get("ok") else 502, result)
            except ModemError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def _run_at(self, cmd: str) -> None:
        if not cmd:
            self._json(400, {"ok": False, "error": "missing AT command"})
            return
        if not STATE.allow_write and not STATE.modem.read_only_command(cmd):
            self._json(403, {"ok": False, "error": "read-only mode; use --allow-write for this command"})
            return
        try:
            with STATE.lock:
                response = STATE.modem.command(cmd, timeout=10.0)
            self._json(200, {"ok": True, "command": cmd, "response": response})
        except Exception as exc:
            self._json(502, {"ok": False, "command": cmd, "error": str(exc)})


class TcpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(300)
        self.wfile.write(b"EC156 AT bridge. Type AT commands, one per line; QUIT to close.\r\n")
        while True:
            try:
                line = self.rfile.readline(4096)
            except OSError:
                return
            if not line:
                return
            cmd = line.decode("utf-8", "replace").strip()
            if not cmd:
                continue
            if cmd.upper() in ("QUIT", "EXIT"):
                self.wfile.write(b"bye\r\n")
                return
            if not STATE.allow_write and not STATE.modem.read_only_command(cmd):
                self.wfile.write(b"ERROR: read-only mode\r\n")
                continue
            try:
                with STATE.lock:
                    response = STATE.modem.command(cmd, timeout=10.0)
            except Exception as exc:
                response = f"ERROR: {exc}"
            self.wfile.write(response.replace("\n", "\r\n").encode("utf-8", "replace") + b"\r\n")


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    global STATE
    ap = argparse.ArgumentParser(description="EC156 HTTP/TCP AT bridge")
    ap.add_argument("--serial", default="auto", help="tty path or 'auto' (default)")
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--tcp-port", type=int, default=9000, help="0 disables the raw TCP bridge")
    ap.add_argument("--allow-write", action="store_true", help="allow SMS and non-query AT commands")
    ap.add_argument("--token", help="shared token for HTTP/TCP clients (optional)")
    args = ap.parse_args()

    device = args.serial
    if device == "auto":
        device = find_at_port()
        if not device:
            print("No AT-capable /dev/ttyUSB* port found. Try --serial /dev/ttyUSB0.", file=sys.stderr)
            return 2
    try:
        modem = AtModem(device, timeout=args.timeout)
    except Exception as exc:
        print(f"cannot open {device}: {exc}", file=sys.stderr)
        return 2

    STATE = State(modem, args.allow_write, args.token)
    tcp_server = None
    if args.tcp_port:
        tcp_server = ThreadedTCPServer((args.bind, args.tcp_port), TcpHandler)
        threading.Thread(target=tcp_server.serve_forever, daemon=True).start()

    httpd = ThreadingHTTPServer((args.bind, args.http_port), HttpHandler)
    print(f"AT port   : {device}", file=sys.stderr)
    print(f"read-only : {not args.allow_write}", file=sys.stderr)
    print(f"HTTP API  : http://{args.bind}:{args.http_port}", file=sys.stderr)
    if args.tcp_port:
        print(f"TCP bridge: {args.bind}:{args.tcp_port}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if tcp_server:
            tcp_server.shutdown()
        modem.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
