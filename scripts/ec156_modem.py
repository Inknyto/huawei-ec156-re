#!/usr/bin/env python3
"""Dependency-free Huawei EC156 / CDMA modem helper.

Why this exists
---------------
The EC156 exposes a plain 3GPP AT command port (and a QCDM diagnostic port).
pyserial is not required here; the code uses Linux termios/fcntl/select only.

Examples
--------
  ./ec156_modem.py ports
  ./ec156_modem.py --serial auto at ATI
  ./ec156_modem.py --serial /dev/ttyUSB0 at 'AT^SYSINFO'
  ./ec156_modem.py --serial auto status
  ./ec156_modem.py --serial auto sms +15551234567 'hello from the modem'

Only read-only commands are used by the `status` command.  A non-empty UIM/SIM
and a provisioned CDMA account are required for SMS and data.

Safety
------
Do not send vendor `$QC...`, `AT^DDSETEX`, or unknown `AT^...` commands while
debugging: on this firmware, some queries can leave the AT parser returning
`+CME ERROR:40` until the modem is reset.  QCDM command 0x29 mode 0
(`29 00 00`) was observed to reboot the EC156 and restore the AT ports.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import select
import sys
import termios
import threading
import time
from typing import Iterable, Optional

BAUD = termios.B115200
FINAL_TOKENS = (
    b"OK",
    b"ERROR",
    b"COMMAND NOT SUPPORT",
    b"+CME ERROR",
    b"+CMS ERROR",
)


class ModemError(RuntimeError):
    pass


class AtModem:
    """A small thread-safe AT client for one tty."""

    def __init__(self, device: str, timeout: float = 2.0, baud: int = BAUD):
        self.device = device
        self.timeout = timeout
        self.baud = baud
        self._lock = threading.RLock()
        self._fd: Optional[int] = None
        self._open()

    def _open(self) -> None:
        fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0  # iflag
        attrs[1] = 0  # oflag
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[3] = 0  # lflag
        attrs[4] = self.baud
        attrs[5] = self.baud
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        self._fd = fd

    def close(self) -> None:
        with self._lock:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                finally:
                    self._fd = None

    def __enter__(self) -> "AtModem":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _read(self, timeout: Optional[float] = None, quiet: float = 0.20) -> bytes:
        assert self._fd is not None
        timeout = self.timeout if timeout is None else timeout
        buf = bytearray()
        end = time.time() + timeout
        last = time.time()
        while time.time() < end:
            ready, _, _ = select.select([self._fd], [], [], 0.05)
            if not ready:
                if buf and time.time() - last > quiet:
                    break
                continue
            try:
                chunk = os.read(self._fd, 8192)
            except OSError:
                break
            if not chunk:
                continue
            buf.extend(chunk)
            last = time.time()
            # Most 3GPP final responses arrive on their own line.  Checking the
            # last non-empty line avoids matching "OK" inside an echoed command.
            text = bytes(buf)
            lines = [ln.strip() for ln in re.split(rb"[\r\n]+", text) if ln.strip()]
            if lines and any(token in lines[-1] for token in FINAL_TOKENS):
                # Drain a trailing CRLF only; do not block on URCs.
                ready, _, _ = select.select([self._fd], [], [], 0.05)
                if ready:
                    try:
                        buf.extend(os.read(self._fd, 8192))
                    except OSError:
                        pass
                break
        return bytes(buf)

    def command(self, command: str, timeout: Optional[float] = None) -> str:
        """Send one AT command and return the raw response text (echo included)."""
        with self._lock:
            if self._fd is None:
                raise ModemError("port is closed")
            termios.tcflush(self._fd, termios.TCIFLUSH)
            os.write(self._fd, command.encode("ascii", "replace") + b"\r")
            raw = self._read(timeout=timeout)
        return raw.decode("utf-8", "replace").replace("\r\n", "\n").strip()

    def read_only_command(self, command: str) -> bool:
        """Conservative allow-list for commands that cannot intentionally write."""
        c = command.strip().upper()
        if c in {"AT", "ATI", "ATI1", "AT&F?", "ATZ"}:
            return True
        # 3GPP/Huawei read commands: +CGMI, +CSQ, ^SYSINFO, ^CARDLOCK?, etc.
        if c.endswith("?") or c.endswith("=?"):
            return True
        if re.fullmatch(r"AT(?:\+[A-Z0-9]+|[\^$][A-Z0-9]+)", c):
            return True
        return False

    def status(self) -> dict:
        """Collect read-only identity, UIM, signal, lock, and port information."""
        out: dict = {"device": self.device, "ok": False, "raw": {}}
        queries = {
            "identity": "ATI",
            "manufacturer": "AT+GMI",
            "model": "AT+GMM",
            "firmware": "AT+GMR",
            "esn": "AT+GSN",
            "capabilities": "AT+GCAP",
            "uim": "AT+CPIN?",
            "imsi": "AT+CIMI",
            "signal": "AT+CSQ",
            "functionality": "AT+CFUN?",
            "cardlock": "AT^CARDLOCK?",
            "sysinfo": "AT^SYSINFO",
            "hardware": "AT^HWVER",
            "portmode": "AT^GETPORTMODE",
            "syscfg": "AT^SYSCFG?",
        }
        for key, cmd in queries.items():
            try:
                out["raw"][key] = self.command(cmd)
            except Exception as exc:  # keep partial status useful
                out["raw"][key] = f"<error: {exc}>"

        text = "\n".join(out["raw"].values())
        out["ok"] = "EC156" in text or "HUAWEI" in text
        m = re.search(r"Revision:\s*(\S+)", out["raw"].get("identity", ""))
        if m:
            out["firmware"] = m.group(1)
        m = re.search(r"^EC156\s*$", out["raw"].get("model", ""), re.M)
        if m:
            out["model"] = "EC156"
        m = re.search(r"\+GSN:\s*([0-9A-Fa-f]+)", out["raw"].get("esn", ""))
        if m:
            out["esn"] = m.group(1)
        m = re.search(r"\+CIMI\s*\n\s*(\d+)", out["raw"].get("imsi", ""))
        if m:
            out["imsi"] = m.group(1)
        m = re.search(r"\+CSQ:\s*(\d+),(\d+)", out["raw"].get("signal", ""))
        if m:
            out["csq"] = int(m.group(1))
            out["ber"] = int(m.group(2))
        out["uim_present"] = "+CME ERROR" not in out["raw"].get("uim", "")
        return out

    def wait_for_prompt(self, timeout: float = 5.0) -> bytes:
        """Read until the SMS '>' prompt or a final error response."""
        assert self._fd is not None
        buf = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([self._fd], [], [], 0.05)
            if not ready:
                continue
            try:
                chunk = os.read(self._fd, 4096)
            except OSError:
                break
            if not chunk:
                continue
            buf.extend(chunk)
            if b">" in buf:
                break
            lines = [ln.strip() for ln in re.split(rb"[\r\n]+", bytes(buf)) if ln.strip()]
            if lines and any(t in lines[-1] for t in FINAL_TOKENS):
                break
        return bytes(buf)

    def send_sms(self, number: str, text: str, timeout: float = 40.0) -> dict:
        """Send a text-mode SMS.  Requires a UIM/SIM and network registration."""
        if not number or not text:
            raise ModemError("number and text are required")
        # Keep the payload 7-bit/GSM-safe.  Refuse control characters.
        if "\x1a" in text or "\x00" in text:
            raise ModemError("SMS text contains a forbidden control character")
        with self._lock:
            termios.tcflush(self._fd, termios.TCIFLUSH)
            os.write(self._fd, b'AT+CMGF=1\r')
            mode = self._read()
            if b"OK" not in mode:
                return {"ok": False, "step": "AT+CMGF=1", "response": mode.decode("utf-8", "replace")}
            termios.tcflush(self._fd, termios.TCIFLUSH)
            os.write(self._fd, f'AT+CMGS="{number}"\r'.encode("ascii", "replace"))
            prompt = self.wait_for_prompt(timeout=5.0)
            if b">" not in prompt:
                return {"ok": False, "step": "AT+CMGS prompt", "response": prompt.decode("utf-8", "replace")}
            os.write(self._fd, text.encode("utf-8", "replace") + b"\x1a")
            result = self._read(timeout=timeout, quiet=0.5)
        decoded = result.decode("utf-8", "replace").strip()
        return {
            "ok": "OK" in decoded and "+CMGS" in decoded,
            "step": "AT+CMGS result",
            "response": decoded,
        }


def scan_ports(pattern: str = "/dev/ttyUSB*") -> list[str]:
    return sorted(glob.glob(pattern), key=lambda p: int(re.search(r"(\d+)$", p).group(1)) if re.search(r"(\d+)$", p) else 0)


def find_at_port(ports: Optional[Iterable[str]] = None, timeout: float = 1.4) -> Optional[str]:
    """Return the first tty that answers ATI with Huawei/EC156 identity."""
    for dev in list(ports) if ports is not None else scan_ports():
        try:
            with AtModem(dev, timeout=timeout) as modem:
                ident = modem.command("ATI", timeout=timeout)
                if "EC156" in ident or "HUAWEI" in ident or "Huawei" in ident:
                    return dev
        except (OSError, ModemError, termios.error):
            continue
    return None


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Huawei EC156 AT helper (no pyserial)")
    p.add_argument("--serial", default="auto", help="tty path, or 'auto' (default)")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--json", action="store_true", help="JSON output where applicable")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list ttyUSB ports and probe AT identity")
    p_at = sub.add_parser("at", help="send one or more AT commands")
    p_at.add_argument("commands", nargs="+")
    sub.add_parser("status", help="read identity/UIM/signal status")
    p_sms = sub.add_parser("sms", help="send a text SMS")
    p_sms.add_argument("number")
    p_sms.add_argument("text")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.cmd == "ports":
        found = []
        for dev in scan_ports():
            row = {"device": dev, "identity": None}
            try:
                with AtModem(dev, timeout=1.4) as modem:
                    ident = modem.command("ATI", timeout=1.4)
                    if ident:
                        row["identity"] = " ".join(ident.split())[:180]
            except (OSError, ModemError, termios.error) as exc:
                row["error"] = str(exc)
            found.append(row)
        print(json.dumps(found, indent=2))
        return 0

    device = args.serial
    if device == "auto":
        device = find_at_port()
        if not device:
            print("No AT-capable /dev/ttyUSB* port found.", file=sys.stderr)
            return 2
    try:
        with AtModem(device, timeout=args.timeout) as modem:
            if args.cmd == "at":
                for command in args.commands:
                    print(f"### {command}")
                    print(modem.command(command) or "(no response)")
                    print()
                return 0
            if args.cmd == "status":
                status = modem.status()
                print(json.dumps(status, indent=2) if args.json else _pretty_status(status))
                return 0 if status["ok"] else 1
            if args.cmd == "sms":
                result = modem.send_sms(args.number, args.text)
                print(json.dumps(result, indent=2))
                return 0 if result["ok"] else 1
    except (OSError, ModemError, termios.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _pretty_status(status: dict) -> str:
    lines = [
        f"device      : {status['device']}",
        f"model       : {status.get('model', 'unknown')}",
        f"firmware    : {status.get('firmware', 'unknown')}",
        f"ESN         : {status.get('esn', 'unknown')}",
        f"IMSI        : {status.get('imsi', 'unknown')}",
        f"UIM present : {status.get('uim_present')}",
        f"CSQ         : {status.get('csq', 'unknown')} (99 = no signal)",
        f"ok          : {status.get('ok')}",
        "",
        "raw responses:",
    ]
    for key, value in status["raw"].items():
        lines.append(f"--- {key} ---")
        lines.append(value)
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
