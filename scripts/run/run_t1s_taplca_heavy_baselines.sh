#!/usr/bin/env bash
# Heavier T1S buses (TA_HEAVY_*: window 2x and/or PT08-PT10 every 1 ms; gPTP schedule vs TA-PLCA v2, runs 0-2)
# then the baselines (runs 0-9). With WAIT=<campaign.out>, starts once that file has ALLDONE.
# Logs in $S (default /tmp/t1s_taplca_heavy). Launch detached:
#   WAIT=/tmp/t1s_taplca_v2/campaign.out P=18 setsid nohup scripts/run/run_t1s_taplca_heavy_baselines.sh > /dev/null 2>&1 &
source ~/omnet/omnetpp-6.4.0/setenv -q >/dev/null 2>&1
export INET_ROOT=~/omnet/inet
S=${S:-/tmp/t1s_taplca_heavy}; mkdir -p $S
if [ -n "$WAIT" ]; then until grep -q ALLDONE "$WAIT" 2>/dev/null; do sleep 60; done; fi
cd ~/zonal-ivn-tsn/simulations
{
for v in W2 L1 W2L1; do for s in GPTP EVC2; do for r in 0 1 2; do echo "zonal_t1s_taplca.ini TA_HEAVY_${v}_${s}_30s $r"; done; done; done
for c in TA_NOMINAL_GPTP TA_NOMINAL_IDEAL TA_NOMINAL_RANDOM TA_LOAD5_GPTP TA_LOAD2_GPTP TA_STRESS_GPTP TA_NOMINAL_EVC_G35_R150; do
  for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini ${c}_30s $r"; done; done
} | xargs -P ${P:-18} -n 3 sh -c '../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca -f $0 -u Cmdenv -c $1 -r $2 --cmdenv-express-mode=true --cmdenv-status-frequency=600s > '$S'/log_$1_$2.txt 2>&1; echo "done $1 $2 rc=$? $(date +%H:%M)"' >> $S/campaign.out
echo ALLDONE >> $S/campaign.out
