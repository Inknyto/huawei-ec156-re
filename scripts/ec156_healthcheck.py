#!/usr/bin/env python3
"""Health check and recovery for a wedged Huawei EC156 AT port.

Observed failure mode
---------------------
After some vendor/Qualcomm AT queries the EC156 AT parser returns
`+CME ERROR:40` for every command, including `AT` and `ATI`.  A QCDM
`DIAG_CMD_CONTROL` frame with mode 0 (`29 00 00`) rebooted the modem, caused
USB re-enumeration (12d1:1505 -> 12d1:140c), and restored the AT ports.

This script:
  1. looks for an AT port that answers `AT`;
  2. if none answers, scans the other ttyUSB ports with a QCDM diag-version
     request;
  3. sends the reset frame to the first QCDM port;
  4. waits for the AT port to reappear.

It never writes NV items and makes no network connection.

Usage:
  ./ec156_healthcheck.py                       # log to stdout only
  ./ec156_healthcheck.py --log ./health.log    # also append to a file
  ./ec156_healthcheck.py --no-reset            # diagnose only
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from ec156_modem import AtModem, ModemError, find_at_port, scan_ports

try:
    from qcdm import Qcdm
except Exception as exc:  # pragma: no cover
    Qcdm = None
    QCDM_IMPORT_ERROR = exc
else:
    QCDM_IMPORT_ERROR = None


def log(path: str | None, message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    line = f"{stamp} {message}"
    print(line)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def at_is_healthy(dev: str, timeout: float = 1.5) -> bool:
    try:
        with AtModem(dev, timeout=timeout) as modem:
            response = modem.command("AT", timeout=timeout)
        return "OK" in response and "ERROR:40" not in response
    except (OSError, ModemError, Exception):
        return False


def find_diag_port(skip: set[str], timeout: float = 1.5) -> str | None:
    if Qcdm is None:
        return None
    for dev in scan_ports():
        if dev in skip:
            continue
        try:
            q = Qcdm(dev)
            try:
                response = q.request(bytes([0x1C]), want=0x1C, timeout=timeout)
            finally:
                q.close()
            if response and response[:3] == b"\x1c\x08\x00":
                return dev
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="EC156 AT/QCDM health check and reset")
    ap.add_argument("--log", default=None, help="optional file to append status lines to")
    ap.add_argument("--no-reset", action="store_true", help="diagnose only")
    ap.add_argument("--wait", type=float, default=45.0, help="seconds to wait for re-enumeration")
    args = ap.parse_args()

    at = find_at_port()
    if at and at_is_healthy(at):
        log(args.log, f"OK: AT port {at} answers")
        return 0

    log(args.log, "AT port did not answer; scanning for QCDM")
    diag = find_diag_port({at} if at else set())
    if not diag:
        log(args.log, "FAIL: no QCDM port answered; unplug/replug the modem")
        return 1
    log(args.log, f"QCDM port found: {diag}")
    if args.no_reset:
        log(args.log, "diagnose-only mode; reset not sent")
        return 2

    if Qcdm is None:
        log(args.log, f"FAIL: cannot import qcdm.py: {QCDM_IMPORT_ERROR}")
        return 1

    try:
        q = Qcdm(diag)
        try:
            q.send(bytes([0x29, 0x00, 0x00]))
        finally:
            q.close()
        log(args.log, "reset frame 29 00 00 sent; waiting for USB re-enumeration")
    except Exception as exc:
        log(args.log, f"FAIL: reset send failed: {exc}")
        return 1

    deadline = time.time() + args.wait
    while time.time() < deadline:
        time.sleep(1.0)
        at = find_at_port()
        if at and at_is_healthy(at):
            log(args.log, f"RECOVERED: AT port {at} answers")
            return 0
    log(args.log, "FAIL: modem did not recover before timeout; unplug/replug")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
