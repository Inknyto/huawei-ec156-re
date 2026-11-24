# EC156 QCDM / DIAG channel

**Device:** Huawei EC156, Qualcomm CDMA 1x/EV-DO, firmware
`11.106.25.00.000`.
**Port:** the DIAG interface, exposed by the kernel `option` driver as a
`/dev/ttyUSB*` node. In the post-reset mapping this was `/dev/ttyUSB1`; it is
**not stable**. Discover it with `scripts/ec156_modem.py ports` or by scanning
candidate ports with a QCDM version request.
**Client:** `scripts/qcdm.py` (dependency-free, Linux termios/select only).
**Reference:** ModemManager `libqcdm` sources under `artifacts/libqcdm/`.

Legend: **[O]** observed live, **[I]** inferred, **[U]** unknown.

---

## 1. Framing

QCDM uses HDLC-style delimiters and CRC-16/CCITT (poly `0x1021`, init `0xffff`,
final XOR `0xffff`), transmitted little-endian, matching libqcdm:

```text
<payload><CRC16 little-endian><0x7e>
```

* `0x7e` terminates a frame.
* `0x7d` escapes a literal `0x7d` or `0x7e` by XORing the next byte with
  `0x20` (PPP-style async transparency).
* The first payload byte is the command ID; response frames echo the same ID.

`scripts/qcdm.py` implements `crc16()`, `escape()`, `unescape()`, `frame()`
and a reader that validates the CRC before returning a frame.

Example: the reset request is the three payload bytes `29 00 00`
(`DIAG_CMD_CONTROL`, mode 0). The script adds the CRC and `0x7e`, and escapes
the body if needed.

**[O]** This implementation was validated against live responses: version,
ESN, status, DIAG version, snapshot and NV reads all decoded with valid CRCs.

---

## 2. Command inventory observed on this unit

| ID | Operation | Observed result | Notes |
|---|---|---|---|
| `0x00` | version / build info | 55-byte response | `SNAVAZ16`; compiled `Feb 15 2012 20:40:43`; released `Oct 01 2010 04:00:00`; extra SCM/MSM fields decoded by the script |
| `0x01` | ESN | `01 1b 12 52 80` | rendered big-endian as `<redacted-esn>` |
| `0x0C` | status | 48-byte response | raw `0ce100e1<redacted-esn-raw>03005922c700...`; `rf_mode=3` |
| `0x13` | (unrequested log/status frame) | seen once as a skipped frame `1338...` | not decoded; do not confuse with the `swver` request |
| `0x1C` | DIAG version | `1c 08 00` | DM version 8 |
| `0x26` | NV read | fixed 133-byte response | see §3 |
| `0x29` | control / reset | mode 0 resets the modem | see §4 |
| `0x38` | software version request | no useful response | a `0x13` frame appeared and was ignored; **[U]** whether `0x38` is supported |
| `0x63` | snapshot | 36-byte response | raw `63<redacted-esn-raw>5922c700a1035922c7a103...` |

The command IDs above are the ones exercised by `scripts/qcdm.py`. libqcdm
defines many more; this firmware's support for them is not established.

### Useful invocations

```sh
python3 scripts/qcdm.py /dev/ttyUSB1 version
python3 scripts/qcdm.py /dev/ttyUSB1 esn
python3 scripts/qcdm.py /dev/ttyUSB1 status
python3 scripts/qcdm.py /dev/ttyUSB1 diagver
python3 scripts/qcdm.py /dev/ttyUSB1 snapshot
python3 scripts/qcdm.py /dev/ttyUSB1 nv 10 178 442 562 1896 4964
python3 scripts/qcdm.py /dev/ttyUSB1 monitor 10
python3 scripts/qcdm.py /dev/ttyUSB1 reset --yes
```

`raw <hex>` sends arbitrary payload bytes and prints the first decoded
response. Use it only for read-only diagnostics unless you have a recovery
path.

---

## 3. NV reads

### 3.1 Request/response shape

The client builds a fixed-size `DMCmdNVReadWrite` request:

```text
cmd 0x26 | nv_item (u16 LE) | profile (u8) | zero padding ... | 0x00 0x00
```

The response is 133 bytes:

```text
cmd 0x26 | nv_item (u16 LE) | data[128] | status (u16 LE)
```

`scripts/qcdm.py nv` prints the first 32 data bytes and the status word.
Only **reads** were performed. No NV write path is implemented.

### 3.2 Observed values

| NV item | Status | Data (first bytes) | Interpretation |
|---|---|---|---|
| 0 | 0 | `1b 12 52 80` | ESN (same as `AT+GSN`) |
| 4 | 0 | `3a` | unknown |
| 5 | 0 | `02` | unknown |
| 6 | 0 | `09` | unknown |
| 7 | 0 | `80 0f` | unknown |
| 8 | 0 | `77` | unknown |
| 9 | 0 | `ff ff` | unknown |
| 10 | 0 | `00 13` | mode preference `0x13` = 1X + HDR (CDMA 1x + EV-DO) **[I]** |
| 178 | 0 | `00 30 30 30 ...` | MDN field, effectively empty/zero **[I]** |
| 442 | 0 | `00 ff` | unknown |
| 562 | 0 | `01` | unknown |
| 1896 | 5 | all zero | status 5 = inactive/not provisioned **[I]** |
| 4964 | 5 | all zero | status 5 = inactive/not provisioned **[I]** |

Status 0 means the read succeeded. Status 5 is the NV item's own status word,
not a transport failure; the meaning is vendor-specific, but "inactive/not
provisioned" is consistent with the empty MDN and no network registration.

### 3.3 Why NV 10 matters

NV 10 `00 13` is consistent with a CDMA-only mode preference and with the
absence of GSM/UMTS AT commands. It does **not** prove the RF front end is
capable of anything beyond 1x/EV-DO; the product and firmware already define
that.

---

## 4. Reset and recovery

`DIAG_CMD_CONTROL` (`0x29`) with mode 0 (`00 00`) rebooted the modem **[O]**.
The USB device disappeared, appeared briefly as `12d1:1505` (mass-storage
style boot mode), then returned as `12d1:140c` with new tty names. This
recovered an AT parser that returned `+CME ERROR:40` for every command.

```sh
python3 scripts/qcdm.py /dev/ttyUSB1 reset --yes
# or, equivalently, send the raw payload:
python3 scripts/qcdm.py /dev/ttyUSB1 raw 290000
```

Kernel evidence and the post-reset port mapping are in
`logs/live-2026-11-24/recovery_qcdm_reset.txt`.

Important observations:

* One reset can produce **several** re-enumerations. In the recorded session
  the modem went through devices 85 → 86 (`1505`) → 87 → 88 → 89 (`140c`)
  before stabilizing. Wait 30–60 s and re-scan; do not reset in a loop.
* `29 00 00` is a soft reboot, not a flash. It did not change the firmware
  version, ESN or identity.
* Mode 2 (`29 00 02`) was tried earlier and did not visibly reset; mode 0 is
  the observed recovery mode. **[O]**

### Do not send

* `DIAG_CMD_DLOAD` / download-mode entry: no recovery image exists.
* NV writes, PRL writes, EFS writes, or "spc" bypass attempts.
* `AT^BOOT`, `AT^DOWNLOAD`, `AT^UPDATE`, `AT^FLASH` from the AT side.

A failed baseband write on the only unit has no tested recovery path.

---

## 5. Telemetry use

QCDM is useful for a host-side monitor even when the radio is unprovisioned:

* ESN and build identity independent of the AT parser.
* RF/status snapshot (`0x0C`, `0x63`).
* Read-only NV audit (mode preference, provisioning status).
* A recovery channel when the AT parser is wedged.

It is **not** a data path and does not replace QMI/PPP for networking.
`monitor 10` dumps frames for ten seconds; this is read-only and safe.

Security: the DIAG port gives low-level access. Restrict it to the host's
`uucp`/`dialout` group and do not expose it over the network. See
`config/99-huawei-ec156.rules`.

---

## 6. Unknowns

* **[U]** Full command coverage beyond the exercised IDs.
* **[U]** Exact semantics of most NV items; only 0/10/178/1896/4964 have a
  plausible interpretation.
* **[U]** Whether the `0x38` software-version command is supported; the
  `0x13` frame seen during that request is undecoded.
* **[U]** Download-mode protocol, signing, and recovery image. Not attempted.

---

## 7. Evidence

| Claim | Evidence |
|---|---|
| Version/ESN/status/DIAG/NV responses | `logs/live-2026-11-24/qcdm_baseline_ttyUSB1.log` |
| Reset and re-enumeration | `logs/live-2026-11-24/recovery_qcdm_reset.txt` |
| Framing/CRC implementation | `scripts/qcdm.py`; `artifacts/libqcdm/qcdm.c`, `commands.c` |
| AT-side wedge | `logs/at_probe_ttyUSB16.log` |
| USB identity change `1505` → `140c` | kernel journal excerpt in the reset log |
