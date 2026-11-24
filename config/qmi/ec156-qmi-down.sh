#!/bin/sh
# Tear down the EC156 QMI/NDIS data path.  Run as root.
set -eu
DEV="${EC156_QMI_DEV:-/dev/cdc-wdm0}"
IFACE="${EC156_QMI_IFACE:-wwp0s20u2i1}"

qmicli -d "$DEV" --wds-stop-network=1 || true
if command -v dhclient >/dev/null 2>&1; then
    dhclient -r "$IFACE" || true
fi
ip link set "$IFACE" down || true
