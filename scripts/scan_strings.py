#!/usr/bin/env python3
"""Scan binaries for ASCII and UTF-16LE strings matching modem-control patterns."""
import os, re, sys, json

PATTERNS = [
    r"AT[\+\^$][A-Za-z0-9_?=&%,\"\.\-]{1,60}",
    r"\^[A-Z][A-Z0-9_]{2,30}",
    r"(?i)(firmware|flash|download|upgrade|update|bootloader|qdload|sahara|firehose|diag|nvitem|nv_item|efs|u2diag|setport|getportmode|portmode|usbcom|composition|imei|meid|esn|prl|spc|msl|carrier|unlock|simlock|cardlock)",
    r"(?i)(https?://[^\s\"'<>]{5,120})",
    r"(?i)([A-Za-z0-9_\-]+\.(bin|fw|mbn|elf|hex|pac|nb0|img|dat))",
]

def strings(data, minlen=4):
    # ascii
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, data):
        yield m.start(), m.group().decode("ascii", "replace")
    # utf-16le
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen, data):
        yield m.start(), m.group().decode("utf-16le", "replace")

def main():
    roots = sys.argv[1:] or ["."]
    seen = set()
    out = []
    for root in roots:
        if os.path.isfile(root):
            files = [root]
        else:
            files = []
            for dp, dn, fn in os.walk(root):
                for f in fn:
                    p = os.path.join(dp, f)
                    try:
                        if os.path.getsize(p) > 80_000_000: continue
                    except OSError: continue
                    files.append(p)
        for path in files:
            try:
                data = open(path, "rb").read()
            except OSError:
                continue
            hits = []
            for off, s in strings(data):
                if any(re.search(p, s) for p in PATTERNS):
                    key = (path, s)
                    if key in seen: continue
                    seen.add(key)
                    hits.append((off, s))
            if hits:
                out.append({"file": path, "hits": hits})
    json.dump(out, sys.stdout, indent=1)

if __name__ == "__main__":
    main()
