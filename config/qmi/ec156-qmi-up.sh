#!/bin/sh
# QMI/NDIS data path for the Huawei EC156.  Run as root.
#
# The EC156's qmi_wwan interface is 2-2:1.1 (usually wwp0s20u2i1).  QMI is
# exposed through /dev/cdc-wdm0, which is root-only by default.  Install
# config/99-huawei-ec156.rules or run this script through sudo.
#
# CDMA networks often need no APN.  If the network requires one, set
# EC156_APN.  This script is intentionally verbose and read-only until the
# final WDS start, so its output can be captured as evidence.
set -eu

DEV="${EC156_QMI_DEV:-/dev/cdc-wdm0}"
IFACE="${EC156_QMI_IFACE:-wwp0s20u2i1}"
APN="${EC156_APN:-}"

echo "== identity =="
qmicli -d "$DEV" --dms-get-manufacturer || true
qmicli -d "$DEV" --dms-get-ids || true
qmicli -d "$DEV" --dms-get-capabilities || true

echo "== serving system =="
qmicli -d "$DEV" --nas-get-serving-system || true
qmicli -d "$DEV" --nas-get-signal-info || true

echo "== link =="
ip link set "$IFACE" up

if [ -n "$APN" ]; then
    echo "== WDS start (APN=$APN) =="
    qmicli -d "$DEV" --wds-start-network="apn=$APN,ip-type=4" --client-no-release-cid
else
    echo "== WDS start (no APN) =="
    qmicli -d "$DEV" --wds-start-network="ip-type=4" --client-no-release-cid
fi

echo "== DHCP =="
if command -v dhclient >/dev/null 2>&1; then
    dhclient -v "$IFACE"
elif command -v udhcpc >/dev/null 2>&1; then
    udhcpc -i "$IFACE"
else
    echo "No DHCP client found; configure $IFACE manually." >&2
fi

ip addr show "$IFACE"
ip route
