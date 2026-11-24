# Evidence index and confidence ledger

**Investigation date:** 2026-11-24
**Target:** Huawei EC156, USB `12d1:140c`, firmware `11.106.25.00.000`,
hardware `CE1EC156M`, ESN `<redacted-esn>`.
**Purpose:** make every claim in `REPORT.md` traceable to a file, a live
observation, or a static-analysis evidence record.

Legend: **[O]** observed, **[I]** inferred, **[U]** unknown.

---

## 1. Live evidence files

| Path | What it shows | Confidence |
|---|---|---|
| `logs/live-2026-11-24/usb_inventory.txt` | `lsusb`, interface/driver mapping, tty nodes, `lsusb -t` | **[O]** |
| `logs/live-2026-11-24/at_baseline_ttyUSB0.log` | post-recovery AT identity/status probe, working commands | **[O]** |
| `logs/live-2026-11-24/qcdm_baseline_ttyUSB1.log` | QCDM version, ESN, status, snapshot, NV 10/178/442/562/1896/4964 | **[O]** |
| `logs/live-2026-11-24/recovery_qcdm_reset.txt` | QCDM `29 00 00` reset, kernel re-enumeration, old/new tty names | **[O]** (command reconstructed; kernel log primary) |
| `logs/live-2026-11-24/update_server_check.txt` | DNS, `CheckNewVersion.aspx` `<status>-1</status>`, `test.aspx` timestamp, `UpdateDone.aspx` 405 | **[O]** |
| `logs/live-2026-11-24/api_http_tcp_test.txt` | `/health`, `/api/status`, `/api/signal`, `/api/at`, read-only denials, raw TCP `ATI` | **[O]** |
| `logs/live-2026-11-24/final_healthcheck.txt` | final `ec156_healthcheck.py --no-reset` result | **[O]** |
| `logs/live-2026-11-24/live_verification.txt` | gammu timeout, qmicli permission denied, ATI, QCDM status at that moment | **[O]** |
| `logs/live-2026-11-24/api_status.json` | earlier `/api/status` JSON capture | **[O]** |
| `logs/live-2026-11-24/gammu_at_trace.log` | gammu AT trace from the successful identify attempt | **[O]** |
| `logs/live-2026-11-24/qmi_session.txt` | live QMI DMS/NAS/WDS/UIM session after permission change | **[O]** |
| `logs/live-2026-11-24/status_final.txt` | final AT status capture | **[O]** |
| `logs/live-2026-11-24/ports_final.txt` | final port discovery | **[O]** |
| `logs/live-2026-11-24/final_healthcheck2.txt` | final health check | **[O]** |
| `logs/at_probe_ttyUSB16.log` | full pre-reset probe and the `+CME ERROR:40` wedge | **[O]** |

### Notes on the reset transcript

The kernel lines are from `journalctl -k` and are verbatim. The exact serial
bytes sent to the DIAG port were not captured by a sniffer; the command
(`29 00 00`, `qcdm.py reset --yes`) is reconstructed from the session notes
and is consistent with the observed reboot. The file says so explicitly.
The USB re-enumeration itself is **[O]**.

---

## 2. Static evidence files

| Path | What it shows |
|---|---|
| `analysis/hashes.txt` | SHA-256 of the vendor installers, updater files and `DataCard_Verify` |
| `analysis/strings_hits.json` | command/URL strings from the extracted vendor libraries and drivers |
| `analysis/rea_datacard_analyze.json` | REA binary overview of `DataCard_Verify` |
| `analysis/rea_datacard_main.json` | REA main function of `DataCard_Verify` |
| `analysis/rea_datacard_main_decompile.json` | REA pseudocode of `DataCard_Verify` |
| `analysis/rea_device_srv_analyze.json` | REA analysis of `libDeviceSrvPlugin.so` |
| `artifacts/ghidra/datacard_verify_all.txt` | Ghidra headless decompilation of `DataCard_Verify` |
| `artifacts/ghidra/device_srv_filtered.txt` | Ghidra headless decompilation of `libDeviceSrvPlugin.so` |
| `artifacts/libqcdm/` | ModemManager `libqcdm` reference sources for framing/NV semantics |

The files are named `rea_*.json`; the table above intentionally shows the
actual names.

### REA evidence IDs

| ID | Target | Finding |
|---|---|---|
| `ev_0a8a60672fe2063449c98d34b94e2e98d4977dc9c1d4d84c42d7455c0dede514` | `DataCard_Verify` | binary overview |
| `ev_6657a0b7c77e5c4f33abb2677ffba5a5d0f20651c48be5fe5790b0af4f46f9bd` | `DataCard_Verify` | main function |
| `ev_812725717289ea2812956c11d22f0203a1af6489dd3ea77c673c5a1328a704a9` | `DataCard_Verify` | main pseudocode; three-argument version comparator |
| `ev_e795b4cd0aa1279ef1e31b97bb3ebbcc02e13ad6037e42d0398e3473a2a7190a` | `libDeviceSrvPlugin.so` | 4,813 procedures and command strings |

REA/Hopper was used for the original native static analysis. Ghidra is now
available on this host and was used for headless decompilation of
`DataCard_Verify` and `libDeviceSrvPlugin.so` (see
`artifacts/ghidra/`). The `rea` CLI and Hopper provider produced the records
above; the MCP server was not registered in this session, but the CLI fallback
was used.

---

## 3. Key observations

### 3.1 Identity **[O]**

```text
ATI:
  Manufacturer: HUAWEI TECHNOLOGIES CO., LTD
  Model: EC156
  Revision: 11.106.25.00.000
  ESN: <redacted-esn>
  +GCAP: +CIS707-A,CIS-856-A,+MS,+ES,+DS,+FCLASS

AT^HWVER: CE1EC156M
AT^CARDLOCK?: ^CARDLOCK: 2,3,0
AT^GETPORTMODE: MDM:0,NDIS:1,DIAG:2,PCUI:3,CDROM:4
QCDM version: SNAVAZ16, compiled Feb 15 2012 20:40:43
QCDM DIAG version: 1c 08 00
```

### 3.2 Radio state **[O]**

```text
AT+CPIN?    -> +CME ERROR:10 / R-UIM not inserted
AT+CSQ      -> +CSQ:99,99
AT^SYSINFO  -> ^SYSINFO:0,255,0,0,240,,0
AT+CFUN?    -> +CFUN: 1
```

No R-UIM, no measured signal, not registered. SMS/data cannot work in this
state.

### 3.3 The wedge and recovery **[O]**

The probe ended with `AT+CDIP?` returning `+CME ERROR:40`; every subsequent
command also returned `+CME ERROR:40`, including plain `AT`. QCDM `29 00 00`
rebooted the modem and restored AT. The reset caused multiple USB
re-enumerations: `12d1:1505` then `12d1:140c`, tty names changed from
`ttyUSB9/13/16` to `ttyUSB0/1/2`.

The exact trigger is **[U]**; the effect is reproducible in the sense that
the parser recovered with the reset.

### 3.4 QMI **[O/C]**

The prior `qmicli` session (preserved in `prompt.txt`) returned:

```text
Manufacturer: QUALCOMM INCORPORATED
ESN: <redacted-esn>
MEID: <redacted-meid>
Max TX: 307000, Max RX: 2400000
Data Service: simultaneous-cs-ps
SIM: supported
Networks: cdma20001x, evdo
Serving system: not-registered; CS/PS detached; radio interface none
```

Current `/dev/cdc-wdm0` is `0600 root:root`; `qmicli` as the normal user fails
with `Permission denied`. The udev rule in `config/` grants `uucp` access.
QMI WDS was not tested and needs a provisioned account.

### 3.5 Update server **[O]**

`update-africa.huaweidevice.com` resolves to `159.138.85.241`.
`CheckNewVersion.aspx` returns HTTP 200 with
`<root><status>-1</status></root>` for a generic request;
`test.aspx` returns a timestamp; `UpdateDone.aspx` returns 405 to GET.
This proves the service is alive but does not provide a firmware image.

### 3.6 Updater binaries **[O]**

`DataCard_Verify` is a version comparator, not a flasher. `libDeviceSrvPlugin`
is the device-service layer. No firmware image, downloader, signing key or
recovery image exists in the supplied tree.

---

## 4. Claim ledger

| Claim | Type | Basis | Remaining uncertainty |
|---|---|---|---|
| Device is EC156 on firmware `11.106.25.00.000` | **[O]** | `ATI`, `AT+GMR` | none |
| USB composition is five interfaces | **[O]** | `lsusb`, kernel log, `AT^GETPORTMODE` | none |
| AT works on two ports and QCDM on one | **[O]** | live probes | port names change after reset |
| No R-UIM/SIM is present | **[O]** | `AT+CPIN?`, `AT+CSQ` | none |
| SMS sending is unsupported **in this state** | **[O]** | `AT+CMGS` returned `COMMAND NOT SUPPORT` | whether it works with a valid R-UIM: **[U]** |
| QMI identity/capabilities exist | **[O]** | prior `qmicli` output in `prompt.txt` | current host permission; WDS untested |
| QCDM reset recovers a wedged AT parser | **[O]** | kernel journal + post-reset AT | exact wedge trigger: **[U]** |
| USB composition can be changed by AT | **[I]/[N]** | `AT^U2DIAG?`, `AT^SETPORT?` rejected; vendor strings only | `AT^SETPID` write untested and risky |
| No firmware image/downloader in the tree | **[O]** | inventory + hashes | a vendor server package may exist behind auth: **[U]** |
| Firmware update is vendor-controlled/signed | **[I]** | updater behavior, `<status>-1</status>`, no public tooling | exact signing scheme: **[U]** |
| Custom firmware/RTOS is not feasible here | **[I]** | no image/tool/signing/BSP/recovery | a second unit + hardware dump could change this |
| Application-layer IoT reuse works | **[O]** | HTTP/TCP bridge, QCDM, health check tested | SMS/data still conditional on UIM |

---

## 5. Reproduction commands

```sh
cd /home/nyto/Documents/huawei/ec156-re

# Identify current ports and identity
python3 scripts/ec156_modem.py ports
python3 scripts/ec156_modem.py --serial auto status

# QCDM baseline (pick the DIAG port from `ports`)
python3 scripts/qcdm.py /dev/ttyUSB1 version
python3 scripts/qcdm.py /dev/ttyUSB1 esn
python3 scripts/qcdm.py /dev/ttyUSB1 nv 10 178 1896 4964

# Health check (no reset)
python3 scripts/ec156_healthcheck.py --no-reset

# HTTP/TCP bridge test
python3 scripts/modem_http.py --serial auto --http-port 8080 --tcp-port 9000
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/status | jq
printf 'ATI\r\nQUIT\r\n' | nc 127.0.0.1 9000

# Update server check (generic, unsigned request)
curl -sS -i 'http://update-africa.huaweidevice.com/africa/UrlCommand/CheckNewVersion.aspx'
```

Do **not** run the reset recipe unless AT itself is wedged:

```sh
python3 scripts/qcdm.py <diag-port> reset --yes
```

---

## 6. Integrity and handling

* All vendor hashes are recorded in `analysis/hashes.txt`. Recompute with:
  `sha256sum <file>`.
* `DataCard_Verify` SHA-256:
  `5527f6c07f03f24eb0ce66cc4d20628727f43f5631185bcf2c1f1d08f03fce55`.
* Live logs are append-only by convention. If a test is repeated, write a new
  timestamped file instead of editing old evidence.
* The reset log is explicitly marked as having a reconstructed command; do
  not present it as a packet capture.
* No NV/EFS/PRL writes were performed. No firmware writes were attempted.
* The working unit was not opened. Test-point/JTAG presence remains **[U]**.

---

## 7. What is still unknown

1. Exact command or timing that triggers `+CME ERROR:40`.
2. Whether `AT+CMGS`, `AT+CMGL`, `AT+CSCA?` work with a valid R-UIM.
3. Whether the unit can register on a live CDMA network and what provisioning
   (MDN/MIN/A-key/PRL) it needs.
4. QMI WDS/APN behavior on CDMA and whether NDIS is usable.
5. The `UTPS Flash` component's package format, signature scheme and download
   protocol.
6. Whether the PCB has a test point/JTAG and whether a flash dump is readable.
7. Whether any vendor-only USB composition command (`AT^SETPID`) works without
   changing the PID irreversibly.

These are recorded as open questions, not as completed work.
