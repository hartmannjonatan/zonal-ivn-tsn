#!/usr/bin/env bash
# Resume the 2026-11-16 TA-PLCA queue (v2 campaign, v2 load sweep, heavier buses, baselines) after an
# interruption: every (ini, config, run) that finished (t1s_run_complete.py: .sca present and vectors reach the sim-time-limit) is skipped.
# A run killed mid-way still writes its .sca (finish() runs on SIGTERM), so .sca alone is not enough;
# move partial results out of the result dirs first (they would enter the report).
# Logs in $S (default ~/t1s_runs/resume, outside /tmp so they survive a reboot). Launch detached:
#   P=22 setsid nohup scripts/run/run_t1s_taplca_resume.sh > /dev/null 2>&1 &
source ~/omnet/omnetpp-6.4.0/setenv -q >/dev/null 2>&1
export INET_ROOT=~/omnet/inet
S=${S:-~/t1s_runs/resume}; mkdir -p $S
pgrep -x xargs > /dev/null && pgrep -f "src/zonal-ivn-tsn -n" > /dev/null && { echo "already running" >> $S/campaign.out; exit 0; }
cd ~/zonal-ivn-tsn/simulations
V=TA_NOMINAL_EVC_G35_R150
jobs() {
for c in ${V}_NOGATE_30s ${V}_D100_30s ${V}_SYNC31_30s ${V}_PROC20_30s ${V}_PROC50_30s; do for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini $c $r"; done; done
for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca_same.ini TA_PTS_NOMINAL_EVC_G35_R150_30s $r"; done
for e in m5 p5 m10 p10 m20 p20 m50 p50; do for r in 0 1 2 3 4; do echo "zonal_t1s_taplca.ini ${V}_TE${e}_30s $r"; done; done
for r in 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini ${V}_PROC403_30s $r"; echo "zonal_t1s_taplca.ini TA_NOMINAL_GPTP_PROC403_30s $r"; echo "zonal_t1s_taplca_same.ini TA_PTS_NOMINAL_GPTP_30s $r"; done
for p in 10 5 2 1; do for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini TA_LOAD${p}_EVC2_30s $r"; done; done
for v in W2 L1 W2L1; do for s in GPTP EVC2; do for r in 0 1 2; do echo "zonal_t1s_taplca.ini TA_HEAVY_${v}_${s}_30s $r"; done; done; done
for c in TA_NOMINAL_GPTP TA_NOMINAL_IDEAL TA_NOMINAL_RANDOM TA_LOAD5_GPTP TA_LOAD2_GPTP TA_STRESS_GPTP ${V}; do
  for r in 0 1 2 3 4 5 6 7 8 9; do echo "zonal_t1s_taplca.ini ${c}_30s $r"; done; done
}
jobs | while read ini c r; do
  python3 ../scripts/run/t1s_run_complete.py results/t1s/taplca/$c $c $r || echo "$ini $c $r"
done > $S/todo.txt
echo "todo $(wc -l < $S/todo.txt) $(date +%H:%M)" >> $S/campaign.out
xargs -P ${P:-22} -n 3 sh -c '../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca -f $0 -u Cmdenv -c $1 -r $2 --cmdenv-express-mode=true --cmdenv-status-frequency=600s > '$S'/log_$1_$2.txt 2>&1; echo "done $1 $2 rc=$? $(date +%H:%M)"' < $S/todo.txt >> $S/campaign.out
echo ALLDONE >> $S/campaign.out
