# EC156 configuration files

These are templates.  They are intentionally kept outside system paths so the
repository stays self-contained.  Install only the pieces you need.

## 1. Permissions (recommended)

```sh
sudo install -m 0644 config/99-huawei-ec156.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

This gives the `uucp` group access to `ttyUSB*` and `cdc-wdm0`, removing the
need for `sudo qmicli` on this unit.  Replug the modem afterwards.

## 2. HTTP/TCP AT bridge

No installation is required; run it directly:

```sh
python3 scripts/modem_http.py --serial auto --http-port 8080 --tcp-port 9000
```

For a service, edit the paths in `config/ec156-modem-api.service`, install it
under `/etc/systemd/system/`, then:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ec156-modem-api
```

## 3. SMS daemon (requires a provisioned UIM/SIM)

```sh
sudo install -m 0640 config/gammu-smsdrc /etc/gammu-smsdrc
sudo install -m 0755 config/sms_received.sh /usr/local/bin/ec156-sms-received
sudo mkdir -p /var/log/gammu /var/spool/gammu/{inbox,outbox,sent,error} /var/lib/ec156-sms
sudo systemctl enable --now ec156-smsd.service
```

Observed limitation: this unit has no R-UIM inserted and `AT+CMGS` returned
`COMMAND NOT SUPPORT`; test SMS only after installing a valid R-UIM and
confirming `AT+CPIN?` returns `READY`.

## 4. PPP data (CDMA `#777`)

Copy the PPP files into place:

```sh
sudo install -m 0644 config/ppp/peers/ec156 /etc/ppp/peers/ec156
sudo install -m 0644 config/ppp/chatscripts/ec156-connect /etc/chatscripts/
sudo install -m 0644 config/ppp/chatscripts/ec156-disconnect /etc/chatscripts/
sudo config/ppp/ec156-ppp-up.sh
```

No PPP link is possible on this unit while `AT+CPIN?` reports no R-UIM and
`AT+CSQ` is 99,99.

## 5. QMI/NDIS data

```sh
sudo config/qmi/ec156-qmi-up.sh
```

Requires root or the udev rule above.  The EC156 QMI interface is
`wwp0s20u2i1`; set `EC156_APN` if the network requires an APN.
