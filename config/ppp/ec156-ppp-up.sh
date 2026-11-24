#!/bin/sh
# Bring up the EC156 CDMA PPP link.  Run as root.
set -eu
exec /usr/sbin/pppd call ec156
