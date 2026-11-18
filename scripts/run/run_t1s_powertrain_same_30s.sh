#!/usr/bin/env bash
source ~/omnet/omnetpp-6.4.0/setenv -q >/dev/null 2>&1
export INET_ROOT=~/omnet/inet
S=${S:-/tmp/t1s_same_logs}; mkdir -p $S
cd ~/zonal-ivn-tsn/simulations
for c in T1S_PTS_NOMINAL_30s T1S_PTS_STRESS_30s T1S_PTS_NOMINAL_SYNCTAS4_GPTP_30s T1S_PTS_STRESS_SYNCTAS4_GPTP_30s; do for r in 0 1 2 3 4 5 6 7 8 9; do echo "$c $r"; done; done | \
 xargs -P 18 -n 2 sh -c '../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca -f zonal_t1s_powertrain_same.ini -u Cmdenv -c $0 -r $1 --cmdenv-express-mode=true --cmdenv-status-frequency=600s > '$S'/slog_$0_$1.txt 2>&1; echo "done $0 $1 rc=$? $(date +%H:%M)"' >> $S/same.out
echo ALLDONE >> $S/same.out
