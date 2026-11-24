# EC156 AT command map

**Device:** Huawei EC156, USB `12d1:140c`, firmware `11.106.25.00.000`,
hardware `CE1EC156M`, ESN `<redacted-esn>`.
**Ports:** AT/MDM and PCUI both answer AT. In the post-reset mapping these were
`/dev/ttyUSB0` and `/dev/ttyUSB2`; the names are not stable.
**Method:** live probes on 2026-11-24. Full transcripts:
`logs/at_probe_ttyUSB16.log` (pre-reset, 571 lines) and
`logs/live-2026-11-24/at_baseline_ttyUSB0.log` (post-recovery).

Legend: **[O]** observed live, **[I]** inferred from evidence, **[U]** unknown.
Status words are the literal final result codes: `OK`, `ERROR`,
`COMMAND NOT SUPPORT`, `+CME ERROR:<n>`.

---

## 1. Commands that worked

| Command | Observed response | Meaning |
|---|---|---|
| `AT` | `OK` | parser alive |
| `ATI` | EC156 / `11.106.25.00.000` / ESN `<redacted-esn>` | identity |
| `AT+GMI`, `AT+CGMI` | `+GMI: HUAWEI TECHNOLOGIES CO., LTD` | manufacturer |
| `AT+GMM`, `AT+CGMM` | `EC156` | model |
| `AT+GMR`, `AT+CGMR` | `11.106.25.00.000` | firmware |
| `AT+GSN`, `AT+CGSN` | `+GSN:<redacted-esn>` | ESN |
| `AT+GCAP` | `+CIS707-A,CIS-856-A,+MS,+ES,+DS,+FCLASS` | CDMA 1x/EV-DO capabilities |
| `AT+CPIN?` | `+CME ERROR:10` or `R-UIM not inserted` | no R-UIM |
| `AT+CIMI` | `<redacted-imsi>` | IMSI (from modem provisioning) |
| `AT+CSQ` | `+CSQ:99,99` | no measured signal |
| `AT+CFUN?` | `+CFUN: 1` | online |
| `AT+CMEE?` | `+CMEE:2` | verbose error codes |
| `AT+CLCC` | `OK` (empty) | no calls |
| `AT+CNMI?` | `+CNMI: 1,1,0,2,0` | SMS indications configured |
| `AT+CMGF?` | `+CMGF: 1` | text-mode SMS selected |
| `AT^CARDLOCK?` | `^CARDLOCK: 2,3,0` | vendor unlock state (see note) |
| `AT^SYSINFO` | `^SYSINFO:0,255,0,0,240,,0` | not registered/attached |
| `AT^HWVER` | `^HWVER: CE1EC156M` | hardware |
| `AT^GETPORTMODE` | `TYPE:EV-DO:Qualcomm,MDM:0,NDIS:1,DIAG:2,PCUI:3,CDROM:4` | fixed USB role map |
| `AT^SYSCFG?` | `^SYSCFG:8,255,3,1,255` | system configuration |
| `AT+CSS?` | `?, 0` | firmware-specific, not standard; do not rely on it |

`ATI` also emits unsolicited lines such as `^MODE: 0`, `^RSSILVL:0`,
`^HRSSILVL:0`, `^CRSSI: 99`, `^HDRRSSI: 99` on some reads. Treat them as URCs,
not command output.

`^CARDLOCK: 2,3,0` is the vendor convention for an unlocked unit, but the exact
field semantics are **[I]**, not documented here. It is not a network
registration indicator.

---

## 2. Commands rejected in the current firmware/state

### 2.1 Cleanly rejected before the parser wedge

| Command | Response | Interpretation |
|---|---|---|
| `ATI1` | `ERROR` | no extended identity |
| `AT+CCID` | `COMMAND NOT SUPPORT` | no UICC ICCID path |
| `AT^ICCID?` | `ERROR` | not implemented |
| `AT+CNUM` | `COMMAND NOT SUPPORT` | no subscriber number |
| `AT+CREG?`, `AT+CGREG?`, `AT+CEREG?`, `AT+COPS?` | `COMMAND NOT SUPPORT` | GSM/LTE registration absent (CDMA firmware) |
| `AT+CLAC` | `COMMAND NOT SUPPORT` | cannot list all commands |
| `AT+CPWD=?`, `AT+CLCK="PN",2` | `+CME ERROR:10` | no SIM PIN path |
| `AT^CARDMODE?` | `COMMAND NOT SUPPORT` | — |
| `AT^SYSINFOEX` | `COMMAND NOT SUPPORT` | only `^SYSINFO` exists |
| `AT^U2DIAG?` | `COMMAND NOT SUPPORT` | USB composition switch absent |
| `AT^SETPORT?` | `COMMAND NOT SUPPORT` | port remap absent |
| `AT^SYSCFGEX?` | `COMMAND NOT SUPPORT` | extended syscfg absent |
| `AT^MODE?`, `AT^VERSION?`, `AT^VER?` | `COMMAND NOT SUPPORT` | — |
| `AT^DATALOCK?` | `COMMAND NOT SUPPORT` | — |
| `AT^DEVINFO?`, `AT^HVER?`, `AT^SERNUM?` | `COMMAND NOT SUPPORT` | identity only via `ATI`/`^HWVER` |
| `AT^DIAG?`, `AT^TRACECTRL?` | `COMMAND NOT SUPPORT` | DIAG is a separate USB interface |
| `AT^PORTSET?`, `AT^PORT?` | `COMMAND NOT SUPPORT` | — |
| `AT^SIGQUAL?`, `AT^HCSQ?` | `COMMAND NOT SUPPORT` | use `AT+CSQ`/URCs |
| `AT^DDSETEX?` | `ERROR` | dangerous vendor path; not usable as a query |
| `AT^DSFLOWQRY?`, `AT^DSFLOWCLR?` | `COMMAND NOT SUPPORT` | no data-flow counters |

### 2.2 Post-wedge results are not evidence of support

After `AT+CDIP?`, every remaining command returned `+CME ERROR:40`. That
includes `AT+CMGF?`, `AT+CLCC`, `AT+CPAS`, `AT^RESET?`, `AT^BOOT?`,
`AT^DOWNLOAD?`, `AT^UPDATE?`, `AT^U2DIAG=?`, `AT^SETPORT=?`, `AT^UIM?`,
`AT^GPIO?`, `AT^TEMP?`, `AT^BATT?`, and dozens of GSM/UMTS commands.

**Do not read `+CME ERROR:40` as "command exists but is disabled."** In this
state the parser rejected even `AT`. The honest conclusion is **[O]**: after
the wedge, no AT command was usable; no support conclusion can be drawn for
those names until the modem is reset and each one is retried individually.

### 2.3 SMS and data commands

| Command | State observed | Conclusion |
|---|---|---|
| `AT+CMGS` | `COMMAND NOT SUPPORT` (no R-UIM state) | sending not proven; retry only after a valid R-UIM is present |
| `AT+CMGL=4` | `COMMAND NOT SUPPORT` (post-wedge) | unknown in healthy state |
| `AT+CSCA?` | `COMMAND NOT SUPPORT` (post-wedge) | unknown |
| `AT+CPBS?` | `+CME ERROR:operation not allowed` (post-recovery) | phonebook unavailable without UIM |
| `AT+CGDCONT?` | `+CME ERROR:40` (post-wedge) | unknown; CDMA path uses PPP `#777` anyway |

The unit cannot place calls, send SMS or establish packet data without a
provisioned R-UIM and CDMA service. `AT+CSQ:99,99` and
`^SYSINFO:0,255,...` are the consistent state markers.

---

## 3. The `+CME ERROR:40` wedge

Exact tail of the broad probe (`logs/at_probe_ttyUSB16.log`) **[O]**:

```text
### AT$QCSYSMODE?
AT$QCSYSMODE?
^RSSILVL:0

^CRSSI: 0

^HRSSILVL:0

^HDRRSSI: 0

### AT+CDIP?
+CME ERROR:40

### AT$QCMIP?
+CME ERROR:40
```

Notes:

* The `AT+CDIP?` line does not even echo the command; the parser was already
  in the error state when it arrived.
* Both AT ports (MDM and PCUI) showed the same behavior.
* The trigger is **[U]**. The last well-formed response was to
  `AT$QCSYSMODE?`; the next command failed. It is not established whether
  `AT$QCSYSMODE?`, `AT^DDSETEX?` (which returned plain `ERROR` just before),
  or an earlier command caused it.

Recovery **[O]**: QCDM `DIAG_CMD_CONTROL` reset frame `29 00 00`, followed by
USB re-enumeration. See `logs/live-2026-11-24/recovery_qcdm_reset.txt`.

---

## 4. Vendor-library strings are not live commands

`analysis/strings_hits.json` contains command-like strings extracted from the
Windows/Linux dashboard libraries. They show what the **vendor application**
can try; they do not prove this firmware implements the command.

| Source | String | Relevance |
|---|---|---|
| `driver/32bit/HWActivator`, `driver/64bit/HWActivator` | `AT^U2DIAG=0`, `AT^SETPID?`, `AT^SETPID=0` | USB composition/PID switching helper. Live `AT^U2DIAG?` was rejected; `AT^SETPID?` was not sent because it is a vendor identity path and a wrong write can change enumeration. |
| `libDeviceAppPlugin.so` | `AT+CGMM`, `AT^RSTRIGGER?`, `Diag`, `SimUnlock` | model/sim-lock UI paths |
| `libDeviceInfoExPlugin.so` | `AT^RSTRIGGER?`, `SysConfig.dat` | reset-trigger query, local config |
| `libAtCodec.so` | `^HCMGR`, `^HCMT`, `^CPBR`, `NO CARRIER` | CDMA SMS/phonebook codec |
| `libDataServicePlugin.so` | `^PPPCFG`, `^DIALMODE`, `^RRCSTATE`, `^WLANCFG`, `^WLANUPD` | PPP/data UI paths |
| `libGpsSrvPlugin.so` | `^WPDST`, `^WPDOM`, `^WPDFR`, `^WPDPL`, `^WPPRV`, `^WPTLM`, `^WPDIP`, `^WPDPT`, `^WPDSO`, `^WPQOS`, `^WPDSC`, `^WPDTL`, `^WPDGL`, `^WPMAP`, `^WPNAT`, `^WPDEA`, `^WPDGP`, `^POSITION`, `^WPDDD`, `^SOCKETCONT`, `^WPURL`, `^WPEND` | GPS/AGPS configuration |
| `libDeviceSrvPlugin.so` | 4,813 procedures and AT command strings (REA `ev_e795b4cd...`) | full device-service command surface, not all reachable on this firmware |

Implication **[I]**: the dashboard supports multiple Huawei products and
firmware branches. A string in the library is a capability of the application,
not a guarantee for the EC156. Test conservatively, one command per reset
window, and never use write/erase/boot variants without a recovery path.

---

## 5. Interpretation for reuse

1. **Identity and status** are fully scriptable with `ATI`, `AT+GMR`, `AT+GSN`,
   `AT+CSQ`, `AT^SYSINFO`, `AT^GETPORTMODE`, `AT^CARDLOCK?`.
2. **No GSM fallback:** this is a CDMA 1x/EV-DO product. `AT+CREG?`,
   `AT+COPS?`, GPRS/UMTS PDP commands are absent. Do not build a GSM-style
   flow around them.
3. **No UIM = no radio service.** The AT parser and QCDM work, but SMS/data
   need a valid R-UIM and CDMA provisioning.
4. **USB composition is fixed** as far as this unit's firmware is concerned:
   `MDM:0,NDIS:1,DIAG:2,PCUI:3,CDROM:4`. `AT^U2DIAG?` and `AT^SETPORT?` are
   rejected. The `HWActivator` strings suggest a vendor-only path; it is
   **[U]** and not recommended on the only unit.
5. **The AT parser can wedge.** Use short, known-good probes; reset with QCDM
   if `AT` itself stops returning `OK`.

---

## 6. Safe probing rules

* Start with `AT` and `ATI`. If either fails, reset before continuing.
* Prefer query forms (`?`) over assignment forms (`=`).
* Do not send `AT^BOOT`, `AT^RESET`, `AT^DOWNLOAD`, `AT^UPDATE`, `AT^FLASH`,
  `AT^U2DIAG=...`, `AT^SETPID=...`, `AT^SYSCFG=...`, `AT^CARDLOCK=...`, or
  any `$QC...` write on this unit. No recovery image exists.
* Allow 30–60 s after a reset; the modem may enumerate more than once.
* Re-discover ports with `python3 scripts/ec156_modem.py ports` instead of
  assuming `/dev/ttyUSB0/1/2`.

---

## 7. Evidence

| Claim | Evidence |
|---|---|
| Working commands and identity | `logs/live-2026-11-24/at_baseline_ttyUSB0.log` |
| Full rejected-command list and wedge | `logs/at_probe_ttyUSB16.log` |
| USB role map | `AT^GETPORTMODE` in both logs; `logs/live-2026-11-24/usb_inventory.txt` |
| Reset recovery | `logs/live-2026-11-24/recovery_qcdm_reset.txt` |
| Vendor strings | `analysis/strings_hits.json` |
| Firmware/update path | `analysis/firmware_and_rtos.md` |
| Live HTTP API output | `logs/live-2026-11-24/api_http_tcp_test.txt` |
