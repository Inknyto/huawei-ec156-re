#!/usr/bin/env python3
"""Minimal QCDM (Qualcomm Diagnostic Monitor) client for Huawei CDMA modems.

Frame format (libqcdm):  <command byte><payload><crc16-le><0x7e>
with 0x7d/0x7e async escaping.  Verified against ModemManager libqcdm.

Usage:
  ./qcdm.py /dev/ttyUSB13 version
  ./qcdm.py /dev/ttyUSB13 esn
  ./qcdm.py /dev/ttyUSB13 status
  ./qcdm.py /dev/ttyUSB13 swver
  ./qcdm.py /dev/ttyUSB13 nv 10 178 442 562 1896 4964
  ./qcdm.py /dev/ttyUSB13 raw 00
  ./qcdm.py /dev/ttyUSB13 snapshot
  ./qcdm.py /dev/ttyUSB13 monitor 10     # dump frames for N seconds
"""
import os, sys, time, select, termios, fcntl, struct, binascii

CRC_TABLE = [
0x0000,0x1189,0x2312,0x329b,0x4624,0x57ad,0x6536,0x74bf,0x8c48,0x9dc1,0xaf5a,0xbed3,0xca6c,0xdbe5,0xe97e,0xf8f7,
0x1081,0x0108,0x3393,0x221a,0x56a5,0x472c,0x75b7,0x643e,0x9cc9,0x8d40,0xbfdb,0xae52,0xdaed,0xcb64,0xf9ff,0xe876,
0x2102,0x308b,0x0210,0x1399,0x6726,0x76af,0x4434,0x55bd,0xad4a,0xbcc3,0x8e58,0x9fd1,0xeb6e,0xfae7,0xc87c,0xd9f5,
0x3183,0x200a,0x1291,0x0318,0x77a7,0x662e,0x54b5,0x453c,0xbdcb,0xac42,0x9ed9,0x8f50,0xfbef,0xea66,0xd8fd,0xc974,
0x4204,0x538d,0x6116,0x709f,0x0420,0x15a9,0x2732,0x36bb,0xce4c,0xdfc5,0xed5e,0xfcd7,0x8868,0x99e1,0xab7a,0xbaf3,
0x5285,0x430c,0x7197,0x601e,0x14a1,0x0528,0x37b3,0x263a,0xdecd,0xcf44,0xfddf,0xec56,0x98e9,0x8960,0xbbfb,0xaa72,
0x6306,0x728f,0x4014,0x519d,0x2522,0x34ab,0x0630,0x17b9,0xef4e,0xfec7,0xcc5c,0xddd5,0xa96a,0xb8e3,0x8a78,0x9bf1,
0x7387,0x620e,0x5095,0x411c,0x35a3,0x242a,0x16b1,0x0738,0xffcf,0xee46,0xdcdd,0xcd54,0xb9eb,0xa862,0x9af9,0x8b70,
0x8408,0x9581,0xa71a,0xb693,0xc22c,0xd3a5,0xe13e,0xf0b7,0x0840,0x19c9,0x2b52,0x3adb,0x4e64,0x5fed,0x6d76,0x7cff,
0x9489,0x8500,0xb79b,0xa612,0xd2ad,0xc324,0xf1bf,0xe036,0x18c1,0x0948,0x3bd3,0x2a5a,0x5ee5,0x4f6c,0x7df7,0x6c7e,
0xa50a,0xb483,0x8618,0x9791,0xe32e,0xf2a7,0xc03c,0xd1b5,0x2942,0x38cb,0x0a50,0x1bd9,0x6f66,0x7eef,0x4c74,0x5dfd,
0xb58b,0xa402,0x9699,0x8710,0xf3af,0xe226,0xd0bd,0xc134,0x39c3,0x284a,0x1ad1,0x0b58,0x7fe7,0x6e6e,0x5cf5,0x4d7c,
0xc60c,0xd785,0xe51e,0xf497,0x8028,0x91a1,0xa33a,0xb2b3,0x4a44,0x5bcd,0x6956,0x78df,0x0c60,0x1de9,0x2f72,0x3efb,
0xd68d,0xc704,0xf59f,0xe416,0x90a9,0x8120,0xb3bb,0xa232,0x5ac5,0x4b4c,0x79d7,0x685e,0x1ce1,0x0d68,0x3ff3,0x2e7a,
0xe70e,0xf687,0xc41c,0xd595,0xa12a,0xb0a3,0x8238,0x93b1,0x6b46,0x7acf,0x4854,0x59dd,0x2d62,0x3ceb,0x0e70,0x1ff9,
0xf78f,0xe606,0xd49d,0xc514,0xb1ab,0xa022,0x92b9,0x8330,0x7bc7,0x6a4e,0x58d5,0x495c,0x3de3,0x2c6a,0x1ef1,0x0f78]

def crc16(data):
    crc = 0xffff
    for b in data:
        crc = CRC_TABLE[(crc ^ b) & 0xff] ^ (crc >> 8)
    return (~crc) & 0xffff

def escape(data):
    out = bytearray()
    for b in data:
        if b in (0x7d, 0x7e):
            out += bytes((0x7d, b ^ 0x20))
        else:
            out.append(b)
    return bytes(out)

def unescape(data):
    out = bytearray(); esc = False
    for b in data:
        if esc:
            out.append(b ^ 0x20); esc = False
        elif b == 0x7d:
            esc = True
        else:
            out.append(b)
    return bytes(out)

def frame(payload):
    body = bytes(payload) + struct.pack("<H", crc16(bytes(payload)))
    return escape(body) + b"\x7e"

def open_port(dev):
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0; a[1] = 0
    a[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    a[3] = 0
    a[4] = termios.B115200; a[5] = termios.B115200
    a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    try:
        fcntl.ioctl(fd, termios.TIOCMBIS, bytes([termios.TIOCM_DTR | termios.TIOCM_RTS]))
    except OSError:
        pass
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd

class Qcdm:
    def __init__(self, dev, verbose=False):
        self.fd = open_port(dev); self.buf = b""; self.verbose = verbose
    def close(self):
        os.close(self.fd)
    def send(self, payload):
        os.write(self.fd, frame(payload))
    def recv_frames(self, timeout=1.0):
        """Yield decoded frames (payload without CRC)."""
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try:
                    self.buf += os.read(self.fd, 8192)
                except OSError:
                    return
                while b"\x7e" in self.buf:
                    pkt, self.buf = self.buf.split(b"\x7e", 1)
                    if len(pkt) < 3:
                        continue
                    raw = unescape(pkt)
                    if len(raw) < 3:
                        continue
                    body, got = raw[:-2], struct.unpack("<H", raw[-2:])[0]
                    if crc16(body) != got:
                        if self.verbose: print(f"  [bad crc frame {body.hex()}]")
                        continue
                    yield body
    def request(self, payload, want=None, timeout=2.0):
        self.send(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            for body in self.recv_frames(0.5):
                if want is None or (body and body[0] == want):
                    return body
                if self.verbose:
                    print(f"  [skip cmd 0x{body[0]:02x}: {body[:24].hex()}]")
        return None

def show_version(b):
    code = b[0]; r = b[1:]
    def cstr(off, n):
        return r[off:off+n].decode("ascii", "replace").rstrip("\0 ")
    print(f"cmd=0x{code:02x} len={len(b)}")
    print(f"  comp_date : {cstr(0,11)}")
    print(f"  comp_time : {cstr(11,8)}")
    print(f"  rel_date  : {cstr(19,11)}")
    print(f"  rel_time  : {cstr(30,8)}")
    print(f"  model     : {cstr(38,8)}")
    if len(r) >= 55:
        scm, mob_cai, mob_model = r[46], r[47], r[48]
        fw = struct.unpack_from("<H", r, 49)[0]
        slot, msm = r[51], r[52]
        print(f"  scm=0x{scm:02x} mob_cai_rev={mob_cai} mob_model={mob_model} mob_fw_rev=0x{fw:04x} slot_cycle={slot} msm_ver=0x{msm:02x}")

def show_esn(b):
    # libqcdm swaps to big-endian when rendering
    print("  ESN: " + "".join(f"{x:02X}" for x in b[1:5][::-1]))
    print("  raw:", b.hex())

def show_status(b):
    print(f"cmd=0x{b[0]:02x} len={len(b)}")
    print("  raw:", b.hex())
    if len(b) >= 1+3+4+2:
        esn = b[4:8]
        rf = struct.unpack_from("<H", b, 8)[0]
        print(f"  esn(raw)={esn.hex()} rf_mode={rf}")

def nv_read(dev, item, profile=0, timeout=2.0):
    # request struct is fixed-size DMCmdNVReadWrite (133 bytes)
    payload = struct.pack("<BH", 0x26, item) + bytes([profile]) + b"\0" * 127 + b"\0\0"
    q = Qcdm(dev)
    try:
        b = q.request(payload, want=0x26, timeout=timeout)
    finally:
        q.close()
    if b is None:
        print(f"NV {item}: no response")
        return None
    # response: code, nv_item, data[128], status[2]
    if len(b) < 133:
        print(f"NV {item}: short response ({len(b)}): {b.hex()}")
        return b
    rit = struct.unpack_from("<H", b, 1)[0]
    data = b[3:131]
    status = struct.unpack_from("<H", b, 131)[0]
    print(f"NV {item}: item={rit} status={status} data={data[:32].hex()}")
    return b

def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    dev, op = sys.argv[1], sys.argv[2]
    q = Qcdm(dev, verbose=True)
    try:
        if op == "version":
            b = q.request(bytes([0x00]), want=0x00)
            print("no response" if b is None else ""); show_version(b) if b else None
        elif op == "esn":
            b = q.request(bytes([0x01]), want=0x01)
            print("no response" if b is None else ""); show_esn(b) if b else None
        elif op == "status":
            b = q.request(bytes([0x0C]), want=0x0C)
            print("no response" if b is None else ""); show_status(b) if b else None
        elif op == "swver":
            b = q.request(bytes([0x38]), want=0x38)
            if b:
                print(f"cmd=0x{b[0]:02x} len={len(b)}")
                print("  raw:", b.hex())
                print("  ascii:", "".join(chr(c) if 32 <= c < 127 else "." for c in b[1:]))
            else:
                print("no response")
        elif op == "snapshot":
            b = q.request(bytes([0x63]), want=0x63, timeout=3)
            print(f"cmd=0x{b[0]:02x} len={len(b)}" if b else "no response")
            if b: print("  raw:", b.hex())
        elif op == "diagver":
            b = q.request(bytes([0x1C]), want=0x1C)
            print(f"cmd=0x{b[0]:02x} len={len(b)} raw={b.hex()}" if b else "no response")
        elif op == "nv":
            for item in map(int, sys.argv[3:]):
                nv_read(dev, item)
        elif op == "raw":
            payload = bytes.fromhex(sys.argv[3])
            b = q.request(payload)
            print(b.hex() if b else "no response")
        elif op == "reset":
            # Observed on the EC156: DIAG_CMD_CONTROL (0x29) with mode 0
            # causes a full modem reboot and USB re-enumeration.  This is the
            # recovery path when the AT parser is stuck returning +CME ERROR:40.
            if len(sys.argv) < 4 or sys.argv[3] != "--yes":
                print("refusing destructive reset; pass --yes to confirm")
                return 2
            q.send(bytes([0x29, 0x00, 0x00]))
            print("reset command sent; USB re-enumeration expected")
            time.sleep(1.0)
        elif op == "monitor":
            secs = float(sys.argv[3]) if len(sys.argv) > 3 else 10
            end = time.time() + secs
            while time.time() < end:
                for b in q.recv_frames(0.5):
                    print(f"{time.strftime('%H:%M:%S')} cmd=0x{b[0]:02x} len={len(b)} {b[:48].hex()}")
        else:
            print(__doc__); return 1
    finally:
        q.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
