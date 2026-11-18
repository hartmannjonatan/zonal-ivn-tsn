#!/usr/bin/env bash
# TA-PLCA v2 load sweep (generic event planner, LOAD*_EVC2): PT01/PT02 every 10/5/2/1 ms, gPTP, runs 0-9.
# Logs in $S (default /tmp/t1s_taplca_v2_load). Launch detached:
#   P=4 setsid nohup scripts/run/run_t1s_taplca_v2_load.sh > /dev/null 2>&1 &
source ~/omnet/omnetpp-6.4.0/setenv -q >/dev/null 2>&1
export INET_ROOT=~/omnet/inet
S=${S:-/tmp/t1s_taplca_v2_load}; mkdir -p $S
cd ~/zonal-ivn-tsn/simulations
for p in 10 5 2 1; do for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini TA_LOAD${p}_EVC2_30s $r"; done; done \
| xargs -P ${P:-18} -n 3 sh -c '../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca -f $0 -u Cmdenv -c $1 -r $2 --cmdenv-express-mode=true --cmdenv-status-frequency=600s > '$S'/log_$1_$2.txt 2>&1; echo "done $1 $2 rc=$? $(date +%H:%M)"' >> $S/campaign.out
echo ALLDONE >> $S/campaign.out
