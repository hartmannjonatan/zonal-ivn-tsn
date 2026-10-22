#!/usr/bin/env bash
set -eo pipefail
source /home/jonatan/omnetpp-env.sh
set -u
audit_dir="$(cd "$(dirname "$0")" && pwd)"
inet_root=/home/jonatan/omnetpp/samples/inet-4.7.0
cd "$audit_dir/plugin"
opp_makemake -f --make-so -o clockprecision -I"$inet_root/src" -L"$inet_root/src" -lINET
export CCACHE_DISABLE=1
make -j2
test -f "$audit_dir/plugin/libclockprecision.so"
