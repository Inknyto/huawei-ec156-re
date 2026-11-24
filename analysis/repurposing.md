# EC156 repurposing and IoT options

This is the practical reuse guide. The EC156 is treated as a **programmable
peripheral on its vendor firmware**, not as a target for baseband replacement.
For the firmware question see `firmware_and_rtos.md`.

Legend: **[O]** observed working on this unit, **[C]** conditional (needs a
valid R-UIM and/or root), **[N]** not supported/not feasible, **[U]** unknown.

---

## 1. Current state and what it implies

| Fact | Consequence |
|---|---|
| EC156, firmware `11.106.25.00.000`, CDMA 1x/EV-DO **[O]** | no GSM/LTE registration path; use CDMA provisioning |
| No R-UIM inserted; `AT+CPIN?` error; `AT+CSQ:99,99` **[O]** | no calls, SMS or data until a valid R-UIM/account exists |
| AT works on MDM and PCUI **[O]** | full local automation |
| QCDM/DIAG works **[O]** | identity, status, NV reads, reset recovery |
| QMI device exists but is root-only here **[O]** | QMI data needs udev/root and a provisioned account |
| Five-interface composition is fixed for this firmware **[O/I]** | no supported USB mode switch found |
| No firmware image/downloader/signing material **[O]** | do not attempt a flash on the only unit |
| Port names change after reset **[O]** | always auto-discover ports |

---

## 2. Options matrix

| Option | Status | What works now | Prerequisites / limits |
|---|---|---|---|
| **AT CLI** | **[O] working** | `ec156_modem.py ports/at/status` | AT port; no pyserial needed |
| **HTTP + TCP AT bridge** | **[O] working** | `/health`, `/api/status`, `/api/signal`, `/api/at`, raw TCP | bind localhost; read-only default; token optional |
| **QCDM telemetry** | **[O] working** | version, ESN, status, snapshot, NV reads | DIAG port; no writes |
| **Health check / recovery** | **[O] working** | detect AT, find DIAG, reset, wait | reset changes tty names; may re-enumerate several times |
| **SMS gateway** | **[C]** | gammu config + webhook hook + API template | valid R-UIM and CDMA SMS provisioning; `AT+CMGS` was `COMMAND NOT SUPPORT` without UIM |
| **PPP data (`ATD#777`)** | **[C]** | peer/chat scripts, up/down helpers | R-UIM, CDMA account, signal |
| **QMI/NDIS data** | **[C]** | qmicli identity worked in the prior session; up/down scripts included | root/udev rule; WDS requires an account |
| **USB composition switch** | **[N]** | none found | `AT^U2DIAG?`, `AT^SETPORT?` rejected; `HWActivator` strings are vendor-only |
| **Custom firmware** | **[N]** | static analysis only | no image/downloader/signing/recovery |
| **Custom RTOS** | **[N]** | static analysis only | closed Qualcomm baseband; no BSP/JTAG evidence |
| **IoT webhook/gateway** | **[O] app layer** | HTTP/TCP + QCDM + optional SMS hook | SMS/data depend on UIM/account |

---

## 3. Working recipes

### 3.1 Local AT CLI

```sh
cd ec156-re
python3 scripts/ec156_modem.py ports
python3 scripts/ec156_modem.py --serial auto at ATI
python3 scripts/ec156_modem.py --serial auto status
python3 scripts/ec156_modem.py --serial auto at 'AT^SYSINFO'
```

`status` performs only read-only queries and returns a JSON-friendly summary.

### 3.2 HTTP/TCP bridge

```sh
python3 scripts/modem_http.py --serial auto --http-port 8080 --tcp-port 9000
```

Read-only by default. Examples:

```sh
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/status | jq
curl -s 'http://127.0.0.1:8080/api/at?cmd=AT%5ESYSINFO' | jq
printf 'ATI\r\nQUIT\r\n' | nc 127.0.0.1 9000
```

Write operations (SMS, non-query AT) require `--allow-write`. Add `--token` if
the bridge is ever exposed beyond localhost. The tested transcript is
`logs/live-2026-11-24/api_http_tcp_test.txt`.

### 3.3 QCDM telemetry

```sh
python3 scripts/qcdm.py /dev/ttyUSB1 version
python3 scripts/qcdm.py /dev/ttyUSB1 esn
python3 scripts/qcdm.py /dev/ttyUSB1 status
python3 scripts/qcdm.py /dev/ttyUSB1 nv 10 178 1896 4964
python3 scripts/qcdm.py /dev/ttyUSB1 monitor 30
```

Use this for an independent identity/health channel. Do not write NV.

### 3.4 Health check and recovery

```sh
python3 scripts/ec156_healthcheck.py --no-reset   # diagnose only
python3 scripts/ec156_healthcheck.py              # reset only if AT is wedged
```

Exit codes: `0` healthy/recovered, `1` failure, `2` diagnose-only and AT is
not answering. The script logs to stdout by default; use `--log ./health.log`
for a file.

### 3.5 systemd service

`config/ec156-modem-api.service` runs the HTTP/TCP bridge. Install per
`config/README.md` and adjust `--serial`, ports and token. Keep the bind
address at `127.0.0.1` unless a firewall/token protects it.

---

## 4. Conditional recipes

### 4.1 SMS gateway

What is included:

* `config/gammu-smsdrc` — gammu SMS daemon configuration.
* `config/sms_received.sh` — `RunOnReceive` hook that emits JSON and can call
  a webhook.
* `config/ec156-smsd.service` — systemd unit.
* `modem_http.py` `POST /api/sms` — direct send with `--allow-write`.

What is **not** proven:

* `AT+CMGS` returned `COMMAND NOT SUPPORT` in the no-R-UIM state. SMS sending
  is therefore **[C]**, not working.
* `AT+CSCA?` and `AT+CMGL=4` were not validated in a healthy state.

Acceptance test after inserting a provisioned R-UIM:

```sh
python3 scripts/ec156_modem.py --serial auto at 'AT+CPIN?'
python3 scripts/ec156_modem.py --serial auto at 'AT+CSQ'
python3 scripts/ec156_modem.py --serial auto at 'AT+CMGF?'
gammu --identify
gammu sendsms TEXT +1... -text 'test'
```

### 4.2 PPP data (`#777`)

The scripts in `config/ppp/` implement the classic CDMA dial-up:

```sh
sudo cp config/ppp/peers/ec156 /etc/ppp/peers/
sudo cp config/ppp/chatscripts/ec156-* /etc/chatscripts/
sudo pon ec156
```

Prerequisites: valid R-UIM, CDMA account/provisioning, signal. With
`AT+CSQ:99,99` and `^SYSINFO` not registered, PPP cannot attach. The scripts
are templates, not a tested data path.

### 4.3 QMI/NDIS data

The prior session recorded successful `qmicli` identity/capability queries, and
QMI was re-run after the `/dev/cdc-wdm0` permission change (see
`logs/live-2026-11-24/qmi_session.txt`). The device was originally
`0600 root:root`; the udev rule grants the `uucp` group:

```sh
sudo install -m 0644 config/99-huawei-ec156.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
# replug, then:
qmicli -d /dev/cdc-wdm0 --dms-get-ids
qmicli -d /dev/cdc-wdm0 --nas-get-serving-system
```

The up/down helpers are in `config/qmi/`. WDS data needs an account; the
no-UIM state cannot attach.

---

## 5. IoT architectures that fit this modem

### A. Local serial-to-HTTP appliance

```
sensor/PLC --serial--> host (Pi/router) --USB--> EC156
                          |
                          +-- HTTP/TCP API (modem_http.py)
                          +-- QCDM health monitor
```

The host owns the logic; the modem is a telephony peripheral. This works
today with no UIM for AT/QCDM, and gains SMS/data when a UIM is fitted.

### B. SMS-to-webhook gateway

```
EC156 --USB--> host --gammu-smsd--> sms_received.sh --> HTTPS webhook/JSON
```

Conditional on a provisioned R-UIM. Useful for alarm panels, utilities and
remote sites that still use CDMA SMS. Keep the webhook retry-safe and
idempotent; store the raw SMS ID if the upstream needs deduplication.

### C. Telemetry/health beacon

```
cron/systemd timer --> ec156_healthcheck.py --no-reset
                   --> qcdm.py status/esn
                   --> JSON log / MQTT publish on the host
```

Works without a UIM. This is the safest "IoT" use: identity, presence and
recovery monitoring, with no dependency on the baseband data path.

### D. Data uplink / failover

Use PPP or QMI only after confirming a provisioned R-UIM and signal. Treat
the link as metered and slow (CDMA 1x/EV-DO), and keep a local queue for
outages. This is **[C]** and was not exercised.

### E. Voice/PCVoice

The dashboard libraries expose `UTPS_CallSrv_Flash`, `PCVoice` and call-log
services. These are vendor application paths, not a documented AT API. No
voice call was attempted, and there is no UIM. **[U]/[N]** for practical use.

---

## 6. Security and operations

* Bind the HTTP/TCP bridge to `127.0.0.1` by default. If remote access is
  required, put it behind a VPN/reverse proxy and set `--token`.
* Run the bridge as a dedicated user in `uucp`/`dialout`; do not run it as
  root. Only the QMI/udev step needs root, and only once.
* The AT bridge can change modem state. Keep `--allow-write` off unless the
  endpoint is trusted and the command set is constrained upstream.
* Do not expose the DIAG port. QCDM is low-level and read/write capable in
  principle; this kit implements reads and reset only.
* Log rotation: the bridge writes access logs to stderr; use journald or a
  logrotate rule.
* After any reset, re-discover ports. Never hard-code `/dev/ttyUSB1`.
* Do not flash the only working unit. See `firmware_and_rtos.md`.

---

## 7. Acceptance checklist

| Capability | How to verify | Expected now |
|---|---|---|
| Device identity | `ec156_modem.py status` | EC156 / `11.106.25.00.000` / ESN `<redacted-esn>` |
| AT parser | `ec156_modem.py at AT` | `OK` |
| HTTP health | `curl /health` | `{"ok": true}` |
| HTTP status | `curl /api/status` | model/firmware/ESN, `uim_present: false`, `csq: 99` |
| Raw TCP | `printf 'ATI\r\nQUIT\r\n' \| nc ...` | identity + `OK` |
| QCDM | `qcdm.py <diag> version` | `SNAVAZ16`, compile `Feb 15 2012` |
| Recovery | `ec156_healthcheck.py --no-reset` | `OK: AT port ... answers` |
| SMS | after R-UIM | **[C]** not yet verified |
| PPP/QMI data | after R-UIM/account | **[C]** not yet verified |
| Custom firmware | — | **[N]** not supported by available evidence |

---

## 8. Files

| Path | Purpose |
|---|---|
| `scripts/ec156_modem.py` | AT client, status, ports, SMS CLI |
| `scripts/modem_http.py` | HTTP + raw TCP bridge |
| `scripts/qcdm.py` | QCDM client, NV reads, reset |
| `scripts/ec156_healthcheck.py` | health check and recovery |
| `config/99-huawei-ec156.rules` | udev permissions |
| `config/gammu-smsdrc`, `config/sms_received.sh` | SMS daemon + webhook |
| `config/ppp/` | CDMA `#777` PPP templates |
| `config/qmi/` | QMI/NDIS up/down helpers |
| `logs/live-2026-11-24/` | live evidence and transcripts |
