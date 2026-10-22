#!/usr/bin/env bash
set -eo pipefail
source /home/jonatan/omnetpp-env.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
INET_ROOT="${INET_ROOT:-/home/jonatan/omnetpp/samples/inet-4.7.0}"
cd "$HERE/precision/plugin"
opp_makemake -f --make-so -o clockprecision -I"$INET_ROOT/src" -L"$INET_ROOT/src" -lINET
export CCACHE_DISABLE=1
make -j2
