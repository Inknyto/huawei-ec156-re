#!/usr/bin/env python3
"""Tiny dependency-free AT-command helper for /dev/ttyUSB* modems.

Usage:
  ./serial_at.py /dev/ttyUSB16 "ATI" "AT+CGSN" ...
  ./serial_at.py --scan            # identify which ttyUSB* answers AT
  ./serial_at.py --file cmds.txt /dev/ttyUSB16
"""
import os, sys, termios, select, time, argparse, glob, errno

def open_port(dev, baud=115200):
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    # iflag, oflag, cflag, lflag
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = termios.B115200 if baud == 115200 else termios.B9600
    attrs[5] = termios.B115200 if baud == 115200 else termios.B9600
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd

def read_until(fd, timeout=2.0, quiet=0.25, stop_tokens=(b"OK", b"ERROR", b"COMMAND NOT SUPPORT", b"+CME ERROR", b"+CMS ERROR")):
    """Read until a final response token appears or the line goes quiet."""
    buf = b""
    end = time.time() + timeout
    last = time.time()
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if data:
                buf += data
                last = time.time()
                # final response found on its own line
                if any(t in buf.split(b"\r\n")[-1] for t in stop_tokens):
                    # give a tick for the trailing CRLF
                    time.sleep(0.03)
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if r:
                        try: buf += os.read(fd, 4096)
                        except OSError: pass
                    break
        elif buf and (time.time() - last) > quiet:
            break
    return buf

def cmd(fd, line, timeout=2.0, wait=0.15):
    os.write(fd, line.encode() + b"\r")
    time.sleep(wait)
    return read_until(fd, timeout=timeout)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("port", nargs="?")
    ap.add_argument("cmds", nargs="*")
    args = ap.parse_args()

    if args.scan:
        for dev in sorted(glob.glob("/dev/ttyUSB*"), key=lambda p: int(p.split("USB")[1])):
            try:
                fd = open_port(dev)
                cmd(fd, "AT")
                resp = cmd(fd, "ATI", timeout=1.5)
                os.close(fd)
                first = " ".join(resp.decode(errors="replace").split())
                print(f"{dev}: {first[:160]}")
            except OSError as e:
                print(f"{dev}: open failed: {e}")
        return

    if not args.port:
        ap.error("port required")
    cmds = list(args.cmds)
    if args.file:
        with open(args.file) as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    cmds.append(ln)
    fd = open_port(args.port)
    for line in cmds:
        resp = cmd(fd, line, timeout=args.timeout)
        text = resp.decode(errors="replace").replace("\r\n", "\n").strip()
        print(f"### {line}")
        print(text if text else "(no response)")
        print()
    os.close(fd)

if __name__ == "__main__":
    main()
