# EC156 firmware and custom-RTOS feasibility

**Question:** can this EC156 be reflashed with custom firmware or a custom
RTOS?
**Short answer:** **no, not with the artifacts and access available here.**
The unit is repurposable at the AT/QCDM/QMI layer, but there is no firmware
image, download tool, signing material or recovery path in the supplied tree.
This document records what exists, what was analysed, and what would be
required before any write attempt.

Legend: **[O]** observed in files or live, **[I]** inference, **[U]** unknown.

---

## 1. What the vendor CD actually contains

The mounted CD is an **e-express / MobilePartner installer**, not a firmware
update package:

| File | SHA-256 | Role |
|---|---|---|
| `Linux/MobilePartner.bin` | `cfd8292f3b3bf9be4a6151653845548c0465283904d9b06d6899fd56e320a80e` | 7-Zip dashboard archive |
| `Linux/data.bin` | `f6ff7b164aa90a1db1be3035738b6f6094b9ea65db25a3c728015fcc1f0f0603` | 7-Zip driver/PPP/plugin archive |
| `Linux/install` | `ebd6a6251bd608f16bf2b96a711475f261d078a40c623561b08f5bee493fc345` | installer, version `21.005.22.00.606` |
| `Linux/DataCard_Verify` | `5527f6c07f03f24eb0ce66cc4d20628727f43f5631185bcf2c1f1d08f03fce55` | version comparator, **not** a flasher |
| `data_extracted/UpdateDog/LiveUpd` | `f2289c95e4d6b0138be9b7c59a74a52e120a7b1f7aef5a2d3c2f28f1f8ee2593` | generic online updater |
| `data_extracted/UpdateDog/UpdateInfo.dat` | `4059d33050caca6d5649ad467c7617d037edd914b0b56c3eb1840062462083e2` | component list/server config |
| `data_extracted/UpdateDog/LiveUpdate.dat` | `a1a97b06e925018bb667830152c0c1406424b8d17939fa80753dd72c907be5f2` | update settings/URLs |
| `data_extracted/UpdateDog/ouc` | `cfd460353cb887169c43d0f3faf3001cf2e27db66a5804007ea46422f3649c94` | Online Update Client |
| `data_extracted/UpdateDog/install` | `37ce74fb18d123b1ccf45257c46f849fb9301e834198ddbb9f3ce792b31fe467` | updater installer |

Full list: `analysis/hashes.txt`.

**[O]** No `.mbn`, `.fw`, `.pac`, QPST/QFIL package, `firmware/` directory,
bootloader image, JTAG dump or flash programmer exists in the supplied tree.

---

## 2. What the updater does

`UpdateInfo.dat` defines three components:

```xml
<component><name>UTPS</name><processname>MobilePartner.bin</processname>...
<component><name>TCPU</name>...
<component><name>UTPS Flash</name>...
```

`LiveUpdate.dat` defines the server and request fields:

```xml
<server>
  <ip>update-africa.huaweidevice.com</ip>
  <port>80</port>
  <virtualdirectory>africa</virtualdirectory>
  <ssl>0</ssl>
</server>
...
<Encrypt>IMSI-IMEI</Encrypt>
<SubmitField>IMEI</SubmitField>
<QueryUrl>/UrlCommand/CheckNewVersion.aspx</QueryUrl>
<SubmitUrl>/UrlCommand/UpdateDone.aspx</SubmitUrl>
<TestUrl>/UrlCommand/test.aspx</TestUrl>
```

**[O]** `UTPS Flash` is only a **component name** in the metadata. No local
flash executable or flash payload accompanies it.

**[I]** `UpdateDog`/`LiveUpd` is a generic HTTP component downloader: it asks
the server for a newer component list, downloads the vendor packages and runs
the vendor's installer. It is not a public baseband flashing protocol.

### Live update-server check (2026-11-24)

Full transcript: `logs/live-2026-11-24/update_server_check.txt`.

```text
DNS: update-africa.huaweidevice.com -> 159.138.85.241
GET /africa/UrlCommand/CheckNewVersion.aspx  -> HTTP 200
  <?xml version="1.0" encoding="UTF-8"?><root><status>-1</status></root>

GET /africa/UrlCommand/test.aspx             -> HTTP 200
  <root><rand>0</rand><time>2026-11-24T08:20:13+0800</time></root>

GET /africa/UrlCommand/UpdateDone.aspx       -> HTTP 405 Method Not Allowed
  {"message":"Method Not Allowed"}
```

Interpretation **[O/I]**:

* The service is alive and reachable.
* A generic, unsigned request is rejected with `status -1`; the real client
  must send the expected encrypted IMSI/IMEI-bearing fields and a supported
  product/version.
* The server does not hand out a firmware image to an arbitrary GET.
* Even a successful response would provide **vendor components**, not a
  documented baseband image or a signing bypass.

---

## 3. Static analysis of the local binaries

### 3.1 `DataCard_Verify`

REA/Hopper analysis:

| Evidence | Content |
|---|---|
| `ev_0a8a60672fe2063449c98d34b94e2e98d4977dc9c1d4d84c42d7455c0dede514` | binary overview |
| `ev_6657a0b7c77e5c4f33abb2677ffba5a5d0f20651c48be5fe5790b0af4f46f9bd` | main function |
| `ev_812725717289ea2812956c11d22f0203a1af6489dd3ea77c673c5a1328a704a9` | main pseudocode |

Finding **[O]**: `DataCard_Verify` is a three-argument **version comparator**.
It parses the fourth dot-separated version segment and accepts a
`|`-separated equal-version list. It decides whether an update package should
replace a component. It contains no flash write, USB download or erase path.
Treating it as a flasher would be a category error.

Raw results: `analysis/rea_datacard_analyze.json`,
`analysis/rea_datacard_main.json`,
`analysis/rea_datacard_main_decompile.json`.
Ghidra confirmation: `artifacts/ghidra/datacard_verify_all.txt`
(`main` at `0x08048704` performs only version parsing and comparison).

### 3.2 `libDeviceSrvPlugin.so`

REA/Hopper evidence
`ev_e795b4cd0aa1279ef1e31b97bb3ebbcc02e13ad6037e42d0398e3473a2a7190a`
(`analysis/rea_device_srv_analyze.json`) enumerates **4,813 procedures** and a
large command-string surface. It is the dashboard's device-service layer:
identity, SIM/card lock, firmware version, PRL, SMS, phonebook, GPS and data
configuration.

Finding **[O]**: the library knows many Huawei AT/vendor commands, but it
contains **no baseband image, no downloader protocol implementation, and no
signing key**. Its presence explains why command strings such as `AT^BOOT`
appear in the vendor tree without being usable on this firmware.
Ghidra confirmation: `artifacts/ghidra/device_srv_filtered.txt`
(`SetBootCmd`, `GetFirmwareVersion`, `UpdatePRL` are host-side helpers only).

### 3.3 Other strings

`analysis/strings_hits.json` shows:

* `HWActivator` tries `AT^U2DIAG=0`, `AT^SETPID?`, `AT^SETPID=0` for USB
  composition/PID switching.
* `libAtCodec.so` contains CDMA SMS/phonebook commands (`^HCMGR`, `^HCMT`,
  `^CPBR`).
* `libGpsSrvPlugin.so` contains a large AGPS command set (`^WPD*`, `^WPURL`,
  `^SOCKETCONT`, `^POSITION`).
* `libDeviceInfoExPlugin.so` references `AT^RSTRIGGER?` and `SysConfig.dat`.

These are application capabilities, not proof of live firmware support. Live
queries for the composition commands (`AT^U2DIAG?`, `AT^SETPORT?`) were
rejected.

---

## 4. Why custom firmware is not feasible here

A baseband replacement would require **all** of the following:

1. **A compatible image** for `CE1EC156M` / firmware branch
   `11.106.25.00.000`, or a known-compatible EC156 image. None is present.
2. **Download-mode knowledge**: Qualcomm Sahara/Firehose or a Huawei-specific
   download mode, USB IDs, framing, handshake and authentication.
3. **Authorization**: a vendor-signed image, or a verified signing bypass.
   No key, certificate or bypass is present.
4. **A recovery path**: a second unit, test point, bootloader backup, or
   vendor service tool. None is available; the only unit is working.
5. **A BSP/RTOS port**: bootloader, clock/power, USB, RF calibration, NV/EFS
   layout and modem firmware interfaces. No source, headers or documentation.

The product is a closed Qualcomm CDMA modem. No serial console, JTAG header,
open bootloader or BSP was found. The case was not opened, so a test point is
**[U]**, not established.

### A custom RTOS specifically

Even if a custom RTOS booted on the application processor (if any), it would
not by itself provide CDMA/EV-DO service: the RF calibration, protocol stack
and NV/EFS data live in the vendor baseband firmware. Replacing the RTOS
without the baseband stack would turn the modem into a non-radio USB device.
That is not a useful outcome for the stated goal.

---

## 5. Decision matrix

| Path | Evidence available | Risk | Verdict |
|---|---|---|---|
| Use AT/QCDM/QMI as-is | full live access | low | **recommended** |
| Vendor component update via dashboard | updater + live server | low/medium | possible on a disposable host, but no firmware image promised |
| USB composition/PID change (`AT^U2DIAG`, `AT^SETPID`) | vendor strings only; live queries rejected | medium/high (enumeration change) | **not attempted**; second unit only |
| Read-only flash dump / identify download mode | no image, no tool | medium | acceptable research on a **second** unit |
| Write custom firmware/RTOS | none of the prerequisites | very high (brick) | **do not attempt** |

---

## 6. If firmware research is pursued later

Do it on a **second identical unit**, and in this order:

1. Photograph and inspect the PCB for test points, unpopulated headers and
   flash part numbers. Record everything.
2. Capture a full flash dump with a hardware programmer/clip **before**
   powering the modem in download mode. Verify the dump by reading twice and
   comparing hashes.
3. Identify the boot/download mode with a USB sniffer while the vendor
   updater runs, using a disposable host and a controlled network.
4. Map the partition table, bootloader, baseband image and NV/EFS regions from
   the dump. Keep the original dump immutable.
5. Only then consider a signed-image path or a recovery procedure. Never
   assume `AT^BOOT`/`DIAG_CMD_DLOAD` is reversible.

No step above was performed on the working unit, and none is recommended
without a recovery path.

---

## 7. Evidence

| Claim | Evidence |
|---|---|
| CD contents and hashes | `analysis/hashes.txt`; `logs/live-2026-11-24/usb_inventory.txt` |
| No firmware image | supplied tree inventory; hashes file |
| Updater metadata | `copied_from_cdrom/data_extracted/UpdateDog/UpdateInfo.dat`, `LiveUpdate.dat` |
| Live server responses | `logs/live-2026-11-24/update_server_check.txt` |
| `DataCard_Verify` is a comparator | REA `ev_0a8a6067...`, `ev_6657a0b7...`, `ev_81272571...`; Ghidra `artifacts/ghidra/datacard_verify_all.txt` |
| Device-service surface | REA `ev_e795b4cd...`; Ghidra `artifacts/ghidra/device_srv_filtered.txt` |
| Vendor command strings | `analysis/strings_hits.json` |
| Live rejection of composition queries | `logs/at_probe_ttyUSB16.log` |
| Firmware identity | `ATI`, `AT+GMR`, QCDM version (`SNAVAZ16`) |
