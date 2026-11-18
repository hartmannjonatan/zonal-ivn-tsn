#!/usr/bin/env bash
# TA-PLCA v2 long campaign (event anchors G35/R150): robustness, no gate, time error, same switch.
# 18 runs in parallel; logs in $S (default /tmp/t1s_taplca_v2). Launch detached:
#   setsid nohup scripts/run/run_t1s_taplca_v2_campaign.sh > /dev/null 2>&1 &
source ~/omnet/omnetpp-6.4.0/setenv -q >/dev/null 2>&1
export INET_ROOT=~/omnet/inet
S=${S:-/tmp/t1s_taplca_v2}; mkdir -p $S
cd ~/zonal-ivn-tsn/simulations
V=TA_NOMINAL_EVC_G35_R150
{
for c in ${V}_NOGATE_30s ${V}_D100_30s ${V}_SYNC31_30s ${V}_PROC20_30s ${V}_PROC50_30s; do for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini $c $r"; done; done
for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca_same.ini TA_PTS_NOMINAL_EVC_G35_R150_30s $r"; done
for e in m5 p5 m10 p10 m20 p20 m50 p50; do for r in 0 1 2 3 4; do echo "zonal_t1s_taplca.ini ${V}_TE${e}_30s $r"; done; done
for r in 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini ${V}_PROC403_30s $r"; echo "zonal_t1s_taplca.ini TA_NOMINAL_GPTP_PROC403_30s $r"; echo "zonal_t1s_taplca_same.ini TA_PTS_NOMINAL_GPTP_30s $r"; done
} | xargs -P ${P:-18} -n 3 sh -c '../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca -f $0 -u Cmdenv -c $1 -r $2 --cmdenv-express-mode=true --cmdenv-status-frequency=600s > '$S'/log_$1_$2.txt 2>&1; echo "done $1 $2 rc=$? $(date +%H:%M)"' >> $S/campaign.out
echo ALLDONE >> $S/campaign.out
