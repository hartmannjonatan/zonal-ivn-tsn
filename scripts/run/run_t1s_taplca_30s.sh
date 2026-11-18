#!/usr/bin/env bash
# TA-PLCA minimum campaign: 30 s runs, seeds 1001-1003 (runs 0-2), 18 in parallel.
# Usage: [INI=entry.ini] run_t1s_taplca_30s.sh CFG [CFG ...]   (logs in $S, default /tmp/t1s_taplca_logs)
# Launch detached: setsid nohup scripts/run/run_t1s_taplca_30s.sh CFGS... > /dev/null 2>&1 &
source ~/omnet/omnetpp-6.4.0/setenv -q >/dev/null 2>&1
export INET_ROOT=~/omnet/inet
export INI=${INI:-zonal_t1s_taplca.ini}
S=${S:-/tmp/t1s_taplca_logs}; mkdir -p $S
RUNS=${RUNS:-"0 1 2"}
cd ~/zonal-ivn-tsn/simulations
for c in "$@"; do for r in $RUNS; do echo "$c $r"; done; done | \
 xargs -P ${P:-18} -n 2 sh -c '../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca -f ${INI:-zonal_t1s_taplca.ini} -u Cmdenv -c $0 -r $1 --cmdenv-express-mode=true --cmdenv-status-frequency=600s > '$S'/log_$0_$1.txt 2>&1; echo "done $0 $1 rc=$? $(date +%H:%M)"' >> $S/taplca.out
echo ALLDONE >> $S/taplca.out
