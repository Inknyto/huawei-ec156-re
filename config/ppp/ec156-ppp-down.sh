#!/bin/sh
# Tear down the EC156 PPP link.
set -eu
pkill -f 'pppd call ec156' || true
