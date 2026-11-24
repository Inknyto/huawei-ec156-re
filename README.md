# Huawei EC156 reverse-engineering and reuse kit

This folder is the reusable result of the EC156 investigation.  It contains
live evidence, static analysis, working AT/QCDM clients, an HTTP/TCP modem
bridge, and configuration templates for SMS, PPP, QMI/NDIS and recovery.

Start with **[REPORT.md](REPORT.md)** for the full findings and the
observed/inferred/unknown split.  The short version:

* The modem identifies as **Huawei EC156**, firmware **11.106.25.00.000**,
  ESN **<redacted-esn>**, hardware **CE1EC156M**.
* It is a Qualcomm CDMA 1x/EV-DO modem.  USB ID **12d1:140c** exposes five
  interfaces: AT/MDM, QMI/NDIS, DIAG/QCDM, PCUI/AT, and a CD-ROM.
* AT, QCDM and (with root) QMI are usable.  The unit currently has **no
  R-UIM/SIM**, so it is not registered and cannot make data/SMS connections.
* The device can be repurposed as a **serial/HTTP/TCP modem, SMS gateway,
  PPP/QMI data modem, or QCDM telemetry source**.
* **Custom firmware / a custom RTOS is not supported by the available
  evidence.**  No firmware image, downloader protocol or signing material was
  found.  The vendor online updater only handles vendor components.
* A wedged AT parser (`+CME ERROR:40`) was recovered by a QCDM reset frame
  (`29 00 00`), which rebooted the modem and re-enumerated USB.

## Quick start

```sh
# 1. Identify the current ports (names change after a USB reset)
python3 scripts/ec156_modem.py ports

# 2. Read device status
python3 scripts/ec156_modem.py --serial auto status

# 3. Send a single AT command
python3 scripts/ec156_modem.py --serial auto at ATI

# 4. Run the HTTP + raw-TCP AT bridge (read-only by default)
python3 scripts/modem_http.py --serial auto --http-port 8080 --tcp-port 9000

# 5. QCDM diagnostics (DIAG port; default /dev/ttyUSB1 here)
python3 scripts/qcdm.py /dev/ttyUSB1 status
python3 scripts/qcdm.py /dev/ttyUSB1 nv 10 178 442 562

# 6. Health check / recovery
python3 scripts/ec156_healthcheck.py --no-reset   # diagnose only
python3 scripts/ec156_healthcheck.py              # reset if wedged
```

The HTTP API is read-only unless `--allow-write` is passed:

```sh
curl -s http://127.0.0.1:8080/api/status | jq
curl -s 'http://127.0.0.1:8080/api/at?cmd=AT%5ESYSINFO' | jq
printf 'ATI\r\nQUIT\r\n' | nc 127.0.0.1 9000
```

## Tree

```
ec156-re/
├── README.md                  this file
├── REPORT.md                  full technical report
├── scripts/
│   ├── ec156_modem.py         AT client/status/SMS CLI (stdlib only)
│   ├── modem_http.py          HTTP + TCP AT bridge
│   ├── qcdm.py                QCDM frame client (ESN/status/NV/reset)
│   ├── ec156_healthcheck.py   AT/QCDM health check and recovery
│   ├── serial_at.py           original minimal AT helper
│   ├── scan_strings.py        vendor-binary string scanner
│   └── at_probe.txt           original probe list (kept for evidence)
├── config/
│   ├── 99-huawei-ec156.rules  udev permissions for ttyUSB*/cdc-wdm0
│   ├── gammu-smsdrc           SMS daemon config
│   ├── sms_received.sh        RunOnReceive JSON/webhook hook
│   ├── ec156-modem-api.service
│   ├── ec156-smsd.service
│   ├── ppp/                   CDMA #777 PPP peer/chat scripts
│   ├── qmi/                   QMI/NDIS up/down scripts
│   └── README.md              install notes
├── analysis/
│   ├── at_command_map.md      supported/unsupported AT map
│   ├── qcdm.md                QCDM framing, NV and reset details
│   ├── firmware_and_rtos.md   update path and custom-firmware feasibility
│   ├── repurposing.md         reuse options matrix
│   ├── evidence.md            evidence index and hashes
│   ├── hashes.txt
│   ├── strings_hits.json      vendor-binary command/URL strings
│   └── rea_*.json             REA/Hopper evidence
└── (raw logs retained locally; identifiers redacted in published docs)
└── (no proprietary artifacts published)
```

## Current device caveats

* Port names are not stable across USB resets.  Use `ec156_modem.py ports` or
  the optional udev symlinks, not hard-coded `/dev/ttyUSB13`.
* `/dev/cdc-wdm0` was originally root-only (`0600`); after the permission change
  QMI was re-run successfully (raw session retained locally; identifiers
  redacted in the published docs).  Install the udev rule for a permanent
  setup.
* No R-UIM is inserted.  `AT+CPIN?` returns `+CME ERROR:R-UIM not inserted`,
  `AT+CSQ` returns `99,99`, and data/SMS cannot attach.
* `AT+CMGS` returned `COMMAND NOT SUPPORT` in the no-UIM state.  The SMS
  configuration is a template to test after a valid R-UIM is installed; it is
  not a claim that this unit can currently send SMS.
* Do not flash the only working unit.  Firmware/RTOS work is analyzed as a
  feasibility question, not attempted.
