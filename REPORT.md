# Huawei EC156 CDMA modem — reverse-engineering report

**Date:** 2026-11-24  
**Target:** Huawei EC156, USB `12d1:140c` (descriptor product string `E180v`)  
**Deliverable:** `ec156-re/`  
**Device state at final verification:** plugged in; AT works on `/dev/ttyUSB0`
and `/dev/ttyUSB2`; QCDM works on `/dev/ttyUSB1`; QMI device
`/dev/cdc-wdm0` is now readable after the permission change (live QMI
session captured); no R-UIM inserted; not registered.

Legend: **[O]** observed directly on this unit or in the supplied files,
**[I]** inference from evidence, **[U]** unknown / not established.

---

## 1. Executive summary

The EC156 is a closed Qualcomm CDMA 1x/EV-DO USB modem with a conventional
Huawei firmware layout.  It is **fully usable as a programmable modem at the
AT/QCDM/QMI layer**, but the evidence does **not** support flashing a custom
firmware or a custom RTOS:

* **AT command channel:** works, with Huawei extensions such as `^SYSINFO`,
  `^HWVER`, `^GETPORTMODE`, `^CARDLOCK`, `^SYSCFG`.  The unit is unlocked
  (`^CARDLOCK: 2,3,0`) but has no R-UIM and no signal.
* **QCDM diagnostic channel:** works (Qualcomm DIAG).  ESN, status, version and
  NV items are readable.  A QCDM control frame (`29 00 00`) was observed to
  reboot the modem and recover a wedged AT parser.
* **QMI channel:** exposed through `/dev/cdc-wdm0` / `qmi_wwan`; the previous
  session captured useful `qmicli` identity/capability/serving-system data.
  Current host permissions block QMI without root; a udev rule is included.
* **USB layout:** five interfaces (AT, QMI/NDIS, DIAG, PCUI/AT, CD-ROM).  No
  supported AT command was found to change this composition.
* **Firmware update:** the CD contains the e-express dashboard and a generic
  online updater (`UpdateDog`/`LiveUpd`).  A component named `UTPS Flash` exists
  in the update metadata, but **no firmware image, downloader or signing
  material is present**.  The update server is still reachable but rejects an
  unsigned/generic request with `<status>-1</status>`.
* **Repurposing:** practical at the application layer — serial/HTTP/TCP modem,
  SMS gateway (with a provisioned R-UIM), PPP/QMI data modem, QCDM monitor,
  and an IoT webhook bridge.  The working tools and configs are in this folder.
* **Custom firmware / RTOS:** not demonstrated and not recommended on the only
  working unit.  It would require a vendor-signed firmware image, a download
  mode/recovery path, and a bootloader/signing bypass, none of which were
  found.

---

## 2. Scope and method

Work performed:

1. Inventoried the supplied tree (`copied_from_cdrom/`, `MobilePartner/`,
   `data.bin/`, prior notes) and extracted/hashed the vendor CD contents.
2. Captured live USB descriptors, interface mapping, kernel logs, AT, QCDM and
   (where permitted) QMI behavior.
3. Built dependency-free AT (`serial_at.py`, `ec156_modem.py`) and QCDM
   (`qcdm.py`) clients and validated them against the live device.
4. Ran REA static analysis on the vendor `DataCard_Verify` updater helper and
   on `libDeviceSrvPlugin.so`.  Ghidra is now available and was used for
   headless decompilation of both binaries (see `artifacts/ghidra/`); Hopper
   was the original provider.
5. Recovered the modem from a wedged AT state with a QCDM reset and verified
   the new port mapping.
6. Built the reusable HTTP/TCP bridge, health check, SMS/PPP/QMI configs, udev
   rule and this report.

The device accepts AT, QCDM, `qmicli` (with permissions) and `gammu`, matching
the user's prior notes.  `gammu --identify` succeeded against `/dev/ttyUSB0`
during this session.

---

## 3. Device identity and live state

### 3.1 Identity

| Property | Value | Evidence |
|---|---|---|
| USB VID:PID | `12d1:140c` | `lsusb`, [O] |
| Descriptor product | `HUAWEI Mobile` / `E180v` | `lsusb`, [O] |
| AT model | `EC156` | `ATI`, `AT+GMM`, [O] |
| Manufacturer | `HUAWEI TECHNOLOGIES CO., LTD` | `AT+GMI`, [O] |
| Firmware | `11.106.25.00.000` | `ATI`, `AT+GMR`, [O] |
| Hardware version | `CE1EC156M` | `AT^HWVER`, [O] |
| ESN | `<redacted-esn>` | `AT+GSN`, QCDM NV 0, [O] |
| MEID | `<redacted-meid>` | prior `qmicli --dms-get-ids`, [O] |
| IMSI | `<redacted-imsi>` | `AT+CIMI`, [O] |
| Card lock | `2,3,0` | `AT^CARDLOCK?`, [O] |
| QCDM version model | `SNAVAZ16` | QCDM cmd `0x00`, [O] |
| QCDM DIAG version | `1c0800` (DM version 8) | QCDM cmd `0x1c`, [O] |
| QCDM compile date | `Feb 15 2012` | QCDM cmd `0x00`, [O] |

The MEID was confirmed again in the live QMI session after the
`/dev/cdc-wdm0` permission change (`logs/live-2026-11-24/qmi_session.txt`);
the AT/ESN identity is also reproducible without root.

### 3.2 Current radio state

```text
AT+CPIN?   -> +CME ERROR:R-UIM not inserted
AT+CSQ     -> +CSQ:99,99
AT^SYSINFO -> ^SYSINFO:0,255,0,0,240,,0
AT^CARDLOCK? -> ^CARDLOCK: 2,3,0
AT+CFUN?   -> +CFUN: 1
```

**[O]** There is no usable R-UIM/SIM.  `CSQ 99,99` means no measured signal.
`^SYSINFO` reports the modem is not registered/attached.  The device is
powered and its AT parser is alive, but it cannot place calls, send SMS or
establish packet data until a valid R-UIM and CDMA provisioning are present.

---

## 4. USB topology and interface mapping

`lsusb -t` and the kernel log show five interfaces:

| USB interface | Linux driver | Device node | Role |
|---|---|---|---|
| `2-2:1.0` | `option` | `/dev/ttyUSB0` | MDM / AT |
| `2-2:1.1` | `qmi_wwan` | `/dev/cdc-wdm0`, `wwp0s20u2i1` | QMI / NDIS |
| `2-2:1.2` | `option` | `/dev/ttyUSB1` | DIAG / QCDM |
| `2-2:1.3` | `option` | `/dev/ttyUSB2` | PCUI / AT |
| `2-2:1.4` | `usb-storage` | `/dev/sr0`, `/dev/sdb` | CD-ROM / SD |

`AT^GETPORTMODE` returns:

```text
^GETPORTMODE:TYPE:EV-DO:Qualcomm,MDM:0,NDIS:1,DIAG:2,PCUI:3,CDROM:4
```

This is the firmware's own mapping and matches the Linux enumeration.  Both
`ttyUSB0` and `ttyUSB2` answer AT; `ttyUSB1` is the QCDM/DIAG port.  Port names
are **not stable across a USB reset**: the pre-reset session had
`ttyUSB9/13/16`, the post-reset session has `ttyUSB0/1/2`.  Scripts use
`ports`/`auto` discovery rather than hard-coded names.

**[O]** The device re-enumerated during a reset as `12d1:1505` (mass-storage
mode) for about 4 seconds, then returned as `12d1:140c`.  This two-stage boot
is useful for recovery: a re-enumeration is normal, not necessarily a failure.

**[I]** The five-interface composition is fixed by firmware.  The vendor
libraries contain `AT^U2DIAG=0` and `AT^SETPID?` strings, but the live device
returns `COMMAND NOT SUPPORT` for `AT^U2DIAG?` and `AT^SETPORT?`.  No supported
AT command to switch composition was found.

---

## 5. AT command interface

### 5.1 Supported/working commands

| Command | Observed response | Meaning |
|---|---|---|
| `AT` | `OK` | parser alive |
| `ATI` | EC156 identity, FW, ESN | identity |
| `AT+GMI` / `AT+CGMI` | HUAWEI | manufacturer |
| `AT+GMM` / `AT+CGMM` | EC156 | model |
| `AT+GMR` / `AT+CGMR` | `11.106.25.00.000` | firmware |
| `AT+GSN` / `AT+CGSN` | `<redacted-esn>` | ESN |
| `AT+GCAP` | `+CIS707-A,CIS-856-A,+MS,+ES,+DS,+FCLASS` | capabilities |
| `AT+CPIN?` | `+CME ERROR:R-UIM not inserted` | no UIM |
| `AT+CIMI` | `<redacted-imsi>` | IMSI |
| `AT+CSQ` | `99,99` | no signal |
| `AT+CFUN?` | `+CFUN: 1` | online |
| `AT+CMEE?` | `+CMEE:2` | extended errors |
| `AT+CLCC` | `OK` (empty) | no calls |
| `AT+CNMI?` | `+CNMI: 1,1,0,2,0` | SMS indication config |
| `AT+CMGF?` | `+CMGF: 1` | text-mode SMS |
| `AT^CARDLOCK?` | `^CARDLOCK: 2,3,0` | unlocked according to vendor convention |
| `AT^SYSINFO` | `^SYSINFO:0,255,0,0,240,,0` | not registered |
| `AT^HWVER` | `^HWVER: CE1EC156M` | hardware |
| `AT^GETPORTMODE` | `MDM:0,NDIS:1,DIAG:2,PCUI:3,CDROM:4` | USB roles |
| `AT^SYSCFG?` | `^SYSCFG:8,255,3,1,255` | system config |

`AT+CSS?` returned an unusual `?, 0`; treat it as firmware-specific and do not
rely on it.

### 5.2 Unsupported / rejected commands

The full probe log is `logs/at_probe_ttyUSB16.log`.  Notable results:

* `AT+CREG?`, `AT+CGREG?`, `AT+CEREG?`, `AT+COPS?` → `COMMAND NOT SUPPORT`
  (this is a CDMA-only firmware; GSM registration commands are absent).
* `AT^SYSINFOEX`, `AT^CARDMODE?`, `AT^U2DIAG?`, `AT^SETPORT?`,
  `AT^SYSCFGEX?`, `AT^SYSINFOEX`, `AT^DATALOCK?`, `AT^DEVINFO?`,
  `AT^DIAG?`, `AT^PORT?`, `AT^UIM?`, `AT^UIMCNF?` → `COMMAND NOT SUPPORT`.
* `AT+CPAS`, `AT+CMGL=4`, `AT+CSCA?` → `COMMAND NOT SUPPORT`.
* `AT+CMGS` → `COMMAND NOT SUPPORT` in the current no-UIM state.  Do not
  assume SMS sending works even with `AT+CMGF: 1`.
* `AT^BOOT`, `AT^RESET`, `AT^UPDATE?` are **known strings from vendor
  libraries**, not proven live commands.  They were not sent because they can
  reboot or enter download mode.

### 5.3 The `+CME ERROR:40` wedge and recovery

During the broad probe the parser transitioned from normal responses to
`+CME ERROR:40` for *every* command, including `AT` and `ATI`.  The exact
trigger was not isolated, but the probe included vendor/Qualcomm queries such
as `AT$QCSYSMODE?`, `AT+CDIP?`, and `AT^DDSETEX?`; after those, the parser no
longer accepted commands on the PCUI or MDM port.

Recovery method that worked **[O]**:

1. Send QCDM `DIAG_CMD_CONTROL` (`0x29`) with mode 0 on the DIAG port:
   `29 00 00` (command + little-endian mode 0).
2. The modem disconnects from USB, briefly appears as `12d1:1505`, then
   re-enumerates as `12d1:140c`.
3. New tty names appear (in this session `ttyUSB0/1/2`); AT works again.

The helper is `scripts/qcdm.py <diag-port> reset --yes`, and
`scripts/ec156_healthcheck.py` automates the detect/reset/wait cycle.

Do not send QCDM NV writes, PRL writes, `AT^BOOT`, or `DIAG_CMD_DLOAD` on the
only device.  These are one-way doors without a recovery image.

---

## 6. QCDM / DIAG channel

### 6.1 Framing

QCDM uses:

```text
<command byte><payload><CRC16-CCITT little-endian><0x7e>
```

with `0x7d` escaping for `0x7d`/`0x7e`, matching ModemManager's `libqcdm`.
The implementation in `scripts/qcdm.py` was validated against live responses.

### 6.2 Useful commands

| Command | ID | Result |
|---|---|---|
| Version info | `0x00` | 55-byte build model `SNAVAZ16`, compile `Feb 15 2012 20:40:43` |
| ESN | `0x01` | `<redacted-esn>` (raw `01 1b 12 52 80`) |
| Status | `0x0C` | 48-byte status; ESN; `rf_mode=3` |
| DIAG version | `0x1C` | `1c 08 00` (DM version 8) |
| NV read | `0x26` | fixed 133-byte `DMCmdNVReadWrite` payload |
| Control | `0x29` | mode 0 = reset/reboot; mode 2 ACK did not visibly reset |
| Snapshot | `0x63` | 36-byte snapshot |

### 6.3 NV observations

Read-only NV dump (no writes):

| NV item | Raw data | Interpretation |
|---|---|---|
| 0 | `1b 12 52 80` | ESN |
| 4 | `3a` | unknown |
| 5 | `02` | unknown |
| 6 | `09` | unknown |
| 7 | `80 0f` | unknown |
| 8 | `77` | unknown |
| 9 | `ff ff` | unknown |
| 10 | `00 13` | mode preference `0x13` = 1X + HDR (CDMA-only) |
| 178 | `00 30 30 ...` | MDN field, effectively empty/zero |
| 442 | `00 ff` | unknown |
| 562 | `01` | unknown |
| 1896 | status 5 | inactive/not provisioned |
| 4964 | status 5 | inactive/not provisioned |

**[I]** NV 10 = `0x13` confirms a CDMA 1x + EV-DO mode preference, consistent
with the EC156 model and the absence of GSM/WCDMA commands.  `status 5` on
1896/4964 and an empty MDN are consistent with an unprovisioned unit, but the
exact NV semantics are vendor-specific.

### 6.4 QCDM reset evidence

The reset was observed in the kernel log: device 083 disappeared, `12d1:1505`
appeared, then `12d1:140c` reappeared; the AT ports moved from
`ttyUSB9/13/16` to `ttyUSB0/1/2`.  See
`logs/live-2026-11-24/recovery_qcdm_reset.txt`.

---

## 7. QMI / NDIS channel

The EC156 exposes a QMI function on interface 1.1.  A full read-only QMI
session was captured after the `/dev/cdc-wdm0` permission change; see
`logs/live-2026-11-24/qmi_session.txt`:

```text
DMS:
  ESN: <redacted-esn>
  IMEI: unknown
  MEID: <redacted-meid>
  Model: 119
  Manufacturer: QUALCOMM INCORPORATED
  Hardware revision: <redacted-hwrev>
  Operating mode: unknown (HW restricted: no)
  Power state: external-source (battery 0 %)
  Capabilities: max TX 307000, max RX 2400000; Data Service simultaneous-cs-ps;
                SIM supported; Networks cdma20001x, evdo
NAS:
  Serving system: not-registered; CS/PS detached; radio interface none
  Home network: MCC 597, MNC 92 (unprovisioned/placeholder mapping)
WDS:
  Packet service: disconnected
  Data bearer technology: unavailable (invalid command on this firmware)
  Current settings: OutOfCall
  Profile list (3gpp2): empty
UIM:
  uim service: not present (QMI error 31 InvalidServiceType)
```

**[O]** `/dev/cdc-wdm0` is now readable by the normal user after the permission
change; `qmicli` returns the values above.  The supplied udev rule grants the
`uucp` group access for a permanent setup.  With access, the standard sequence is
in `config/qmi/ec156-qmi-up.sh`:

```sh
qmicli -d /dev/cdc-wdm0 --dms-get-ids
qmicli -d /dev/cdc-wdm0 --nas-get-serving-system
ip link set wwp0s20u2i1 up
qmicli -d /dev/cdc-wdm0 --wds-start-network="ip-type=4" --client-no-release-cid
dhclient wwp0s20u2i1
```

**[I]** The modem's QMI DMS/NAS/WDS services are present, but WDS data requires a
provisioned CDMA account and R-UIM.  No data connection is possible with no R-UIM
and `CSQ 99,99`.  The `uim` QMI service is absent on this firmware, consistent
with the AT `+CME ERROR: R-UIM not inserted`.  Some DMS/NAS queries
(firmware preference, software version, time, activation state, PRL version,
band capabilities, signal info, system info, data bearer technology) return
`InvalidQmiCommand` on this old firmware; they are not available through QMI.

---

## 8. Vendor CD, updater and firmware path

### 8.1 What is on the CD

The mounted CD is an e-express/MobilePartner installer, not a firmware image:

| File | SHA-256 | Role |
|---|---|---|
| `Linux/MobilePartner.bin` | `cfd8292f...` | 7-Zip dashboard archive |
| `Linux/data.bin` | `f6ff7b16...` | 7-Zip driver/PPP/plugin archive |
| `Linux/install` | `ebd6a625...` | installer; version `21.005.22.00.606` |
| `Linux/DataCard_Verify` | `5527f6c0...` | version comparator (REA-analysed) |
| `UpdateDog/LiveUpd` | `f2289c95...` | generic online updater |
| `UpdateDog/UpdateInfo.dat` | `4059d330...` | component list/server config |
| `UpdateDog/LiveUpdate.dat` | `a1a97b06...` | update settings/URLs |

`DataCard_Verify` is **not** a flasher.  REA evidence `ev_0a8a6067...`
(binary overview) and `ev_6657a0b7...`/`ev_81272571...` (main function and
pseudocode) show a three-argument version comparator: it parses the fourth
dot-separated segment and accepts a `|`-separated equal-version list.  It is
used by update packages to decide whether to replace a component.  The same
conclusion was independently confirmed with Ghidra headless decompilation
(`artifacts/ghidra/datacard_verify_all.txt`): `main` performs only string
parsing/version comparison and prints `Install!`/`Run!`; there is no flash,
download or boot-mode code.

### 8.2 Update metadata

`UpdateInfo.dat` lists three components:

```xml
<component><name>UTPS</name><processname>MobilePartner.bin</processname>...
<component><name>TCPU</name>...
<component><name>UTPS Flash</name>...
```

`LiveUpdate.dat` contains:

```xml
<QueryUrl>/UrlCommand/CheckNewVersion.aspx</QueryUrl>
<SubmitUrl>/UrlCommand/UpdateDone.aspx</SubmitUrl>
<Encrypt>IMSI-IMEI</Encrypt>
<SubmitField>IMEI</SubmitField>
```

and points at `update-africa.huaweidevice.com` (HTTP, port 80, virtual
directory `africa`).

**[O]** On 2026-11-24 the server resolved to `159.138.85.241` and returned
`HTTP 200` for `CheckNewVersion.aspx`; an unsigned request returned:

```xml
<?xml version="1.0" encoding="UTF-8"?><root><status>-1</status></root>
```

The test endpoint returned a timestamp.  This proves the update service is
alive but requires the correct encrypted/IMEI-bearing request and a supported
client/version.  It does **not** provide a firmware image directly.

### 8.3 Firmware feasibility conclusion

* **[O]** No `.mbn`, `.fw`, `.pac`, `firmware/`, QPST/QFIL or downloader payload
  exists in the supplied CD tree.
* **[O]** The updater has a `UTPS Flash` component name and firmware-update
  language strings, but no local flash executable or image.
* **[O]** Ghidra headless analysis of `libDeviceSrvPlugin.so`
  (`artifacts/ghidra/device_srv_filtered.txt`) shows only host-side device
  service helpers (card lock, PRL read/write, firmware version queries,
  reset).  No firmware download mode, flash routine, bootloader or signing
  code exists in the recovered vendor libraries.
* **[I]** Firmware installation is vendor-controlled and likely signed; the
  updater is a generic HTTP component downloader, not a public flashing tool.
* **[U]** The exact download-mode protocol, signing scheme and recovery image
  are unknown.  Attempting `AT^BOOT`, `DIAG_CMD_DLOAD` or a random `.bin` is
  unsafe on the only unit.

---

## 9. Repurposing / IoT options

| Option | Feasibility | What works now | Limits / prerequisites |
|---|---|---|---|
| **AT-over-TCP / HTTP API** | **Working** | `modem_http.py`: `/api/status`, `/api/at`, `/api/signal`, raw TCP `ATI` | read-only by default; bind to localhost; use token if exposed |
| **Programmatic AT client** | **Working** | `ec156_modem.py at/status/ports` | no `pyserial` dependency |
| **QCDM telemetry/monitor** | **Working** | ESN, status, version, NV reads | DIAG port; no NV writes |
| **Health check / auto-recovery** | **Working** | detects wedged AT, scans QCDM, sends reset, waits for re-enum | reset changes tty names; requires udev/root for QMI |
| **SMS gateway** | Conditional | gammu config + `gammu-smsd` hook | needs provisioned R-UIM; `AT+CMGS` returned `COMMAND NOT SUPPORT` without UIM |
| **PPP data (`ATD#777`)** | Conditional | peer/chat scripts | needs R-UIM, CDMA provisioning, signal |
| **QMI/NDIS data** | Conditional | qmi scripts; prior `qmicli` identity works | root/udev rule; WDS requires account |
| **USB composition switch** | Not supported | none | `^U2DIAG`/`^SETPORT` rejected; no live command found |
| **Custom firmware** | Not feasible | static analysis only | no image, downloader, signing or recovery |
| **Custom RTOS** | Not feasible | static analysis only | closed Qualcomm baseband; no BSP/JTAG evidence |
| **IoT webhook bridge** | Working at app layer | API + `sms_received.sh` webhook template | network/SMS depend on UIM/account |

The practical "IoT" design is therefore an **appliance around the modem**:
the EC156 stays on its vendor firmware, and a host (Pi, router, container)
exposes HTTP/TCP, polls AT/QCDM, forwards SMS to a webhook, and optionally
brings up PPP/QMI.  This is reliable and reversible; baseband replacement is
not.

---

## 10. Custom firmware / custom RTOS assessment

### What would be required

1. A firmware image for this exact hardware/firmware branch (`CE1EC156M`,
   `11.106.25.00.000`) or a compatible EC156 image.
2. Knowledge of the download mode (Qualcomm Sahara/Firehose or Huawei
   download mode), USB IDs, packet framing and authentication.
3. A signed/authorized image, or a verified signing bypass.
4. A recovery path (vendor flash tool, test point, bootloader backup) if the
   image fails.
5. A board support package for the baseband, peripherals and RF calibration.

### Evidence

* The vendor UI exposes only version checks and a generic component updater.
* The product is a closed Qualcomm CDMA modem; no source, BSP, JTAG header,
  serial console or open bootloader was found.
* `AT^BOOT`/`AT^RESET` strings exist in `libDeviceSrvPlugin.so`, and
  `DIAG_CMD_DLOAD` exists in the Qualcomm command set, but sending them without
  a recovery image is a brick risk.  They were deliberately **not** sent.
* Ghidra analysis did not reveal any firmware download/flash routine in the
  recovered vendor libraries; `SetBootCmd`/`GetFirmwareVersion`/`UpdatePRL` are
  host-side helpers only.
* The only local binary REA examined (`DataCard_Verify`) is a comparator, not a
  flasher.

### Verdict

**Do not attempt custom firmware or a custom RTOS on the only working unit.**
The evidence supports application-layer repurposing, not baseband replacement.
If firmware research is pursued, use a second identical unit and a hardware
recovery path; start by capturing a full flash dump and identifying the
download mode, not by writing.

---

## 11. Recovery runbook

### A. AT parser wedged (`+CME ERROR:40` on every command)

1. Find the DIAG port (`/dev/ttyUSB1` in the current mapping; it changes after
   reset).
2. Send the QCDM control reset:

   ```sh
   python3 scripts/qcdm.py /dev/ttyUSB1 reset --yes
   ```

   or simply:

   ```sh
   python3 scripts/qcdm.py /dev/ttyUSB1 raw 290000
   ```

3. Wait 10–45 seconds.  The device may disappear, appear as `12d1:1505` for a
   few seconds, then return as `12d1:140c`.
4. Re-scan:

   ```sh
   python3 scripts/ec156_modem.py ports
   ```

5. Verify `ATI` and `AT^GETPORTMODE`.

### B. No QCDM response

* Unplug/replug the modem (the user-level recovery that always works).
* If a replug is not possible, a USB port reset needs root (`usbreset` or
  `USBDEVFS_RESET`); normal users cannot do it.
* Do not repeatedly send unknown vendor commands; they can re-wedge the parser.

### C. QMI permission denied

```sh
sudo install -m 0644 config/99-huawei-ec156.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
# replug, then:
qmicli -d /dev/cdc-wdm0 --dms-get-ids
```

### D. Flashing failure (hypothetical)

No tested recovery image exists.  A failed baseband flash would require a
vendor service tool/test point.  This is why flashing is out of scope for this
unit.

---

## 12. Evidence index

| ID / path | What it shows |
|---|---|
| `logs/live-2026-11-24/at_baseline_ttyUSB0.log` | post-recovery AT identity/status probe |
| `logs/live-2026-11-24/qcdm_baseline_ttyUSB1.log` | QCDM version/status/NV baseline |
| `logs/live-2026-11-24/usb_inventory.txt` | lsusb, interface mapping, device nodes |
| `logs/live-2026-11-24/live_verification.txt` | gammu (failed due port), qmicli permission, ATI, QCDM |
| `logs/live-2026-11-24/api_status.json` | HTTP bridge `/api/status` output |
| `logs/live-2026-11-24/recovery_qcdm_reset.txt` | QCDM reset and re-enumeration evidence |
| `logs/live-2026-11-24/update_server_check.txt` | Huawei update server responses |
| `logs/live-2026-11-24/qmi_session.txt` | Live QMI DMS/NAS/WDS/UIM session after permission change |
| `logs/live-2026-11-24/status_final.txt` | Final AT status capture |
| `logs/live-2026-11-24/ports_final.txt` | Final port discovery |
| `logs/live-2026-11-24/final_healthcheck2.txt` | Final health check |
| `artifacts/ghidra/datacard_verify_all.txt` | Ghidra decompilation of `DataCard_Verify` (version comparator) |
| `artifacts/ghidra/device_srv_filtered.txt` | Ghidra decompilation of `libDeviceSrvPlugin.so` (host helpers) |
| `logs/at_probe_ttyUSB16.log` | original full probe and the `+CME ERROR:40` transition |
| `analysis/hashes.txt` | SHA-256 of vendor files |
| `analysis/strings_hits.json` | vendor-binary command/URL strings |
| `analysis/rea_datacard_analyze.json` | REA `binary_overview`, `ev_0a8a6067...` |
| `analysis/rea_datacard_main.json` | REA main function, `ev_6657a0b7...` |
| `analysis/rea_datacard_main_decompile.json` | REA pseudocode, `ev_81272571...` |
| `analysis/rea_device_srv_analyze.json` | REA `libDeviceSrvPlugin`, `ev_e795b4cd...` |
| `artifacts/libqcdm/` | libqcdm reference sources for framing/NV semantics |

---

## 13. Unknowns and limitations

* Exact trigger for the `+CME ERROR:40` wedge; it is reproducible in effect but
  not isolated to a single command.
* Whether `AT+CMGS` works with a valid R-UIM; current response is
  `COMMAND NOT SUPPORT` in the no-UIM state.
* Exact CDMA provisioning state (MDN/MIN/A-key) and whether the unit can
  register on a live CDMA network.  No R-UIM/account was available.
* QMI WDS behavior and APN requirements on CDMA; the WDS path was not tested.
* The `UTPS Flash` component's exact package format, signature scheme and
  download-mode protocol.
* Whether any test point/JTAG is present on the PCB; the case was not opened.
* Custom firmware/RTOS feasibility remains **unproven**, not merely untested.

---

## 14. Bottom line

The EC156 is a good **application-layer** IoT/telephony brick: it speaks AT,
QCDM and QMI, and it can be exposed over HTTP/TCP with the included tools.  It
is a poor candidate for custom firmware or a custom RTOS with the information
and hardware access available here.  The responsible next step is to use the
modem as a programmable peripheral (with a valid R-UIM for SMS/data), not to
flash the only working unit.
