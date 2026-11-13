//
// Copyright (C) 2023 OpenSim Ltd. (EthernetPlca, from which this module is derived)
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// See PrioPlca.h. handleWithControlFSM() is a copy of the control state machine
// of INET's EthernetPlca (148.4.4.6 of IEEE Std 802.3cg-2019); every changed line
// is marked "PrioPlca". When moving to another INET version, diff it against
// src/inet/physicallayer/wired/ethernet/EthernetPlca.cc.
//
#include "PrioPlca.h"

#include <algorithm>
#include <sstream>

namespace ivnplca {

Define_Module(PrioPlca);

simsignal_t PrioPlca::priorityToInsertedSignal = cComponent::registerSignal("priorityToInserted");
simsignal_t PrioPlca::anchorHoldSignal = cComponent::registerSignal("anchorHold");
simsignal_t PrioPlca::anchorSkippedSignal = cComponent::registerSignal("anchorSkipped");
simsignal_t PrioPlca::anchorLateSignal = cComponent::registerSignal("anchorLate");

PrioPlca::~PrioPlca()
{
    cancelAndDelete(anchorTimer);
}

void PrioPlca::initialize(int stage)
{
    EthernetPlca::initialize(stage);
    if (stage == INITSTAGE_LOCAL) {
        std::string m = par("mode").stdstringValue();
        if (m == "standard")
            plcaMode = STANDARD;
        else if (m == "multiTo")
            plcaMode = MULTI_TO;
        else if (m == "priorityTo")
            plcaMode = PRIORITY_TO;
        else if (m == "anchored")
            plcaMode = ANCHORED;
        else
            throw cRuntimeError("Unknown mode '%s'", m.c_str());
        priorityNodeID = par("priorityNodeID");
        minTriggerToLength = par("minTriggerToLength");
        priorityToTimerLength = b(par("priorityToTimerLength"));
        priorityCommitGuard = b(par("priorityCommitGuard"));
        if (priorityCommitGuard >= priorityToTimerLength)
            throw cRuntimeError("priorityCommitGuard must be shorter than priorityToTimerLength");
        std::istringstream is(par("slotOwners").stdstringValue());
        int owner;
        while (is >> owner)
            slotOwners.push_back(owner);
        if (plcaMode == MULTI_TO) {
            if ((int)slotOwners.size() != plca_node_count)
                throw cRuntimeError("slotOwners has %d entries but plca_node_count = %d", (int)slotOwners.size(), plca_node_count);
            if (slotOwners[0] != 0)
                throw cRuntimeError("slot 0 must belong to the coordinator (node 0)");
        }
        if (plcaMode == PRIORITY_TO && (priorityNodeID <= 0 || priorityNodeID >= plca_node_count))
            throw cRuntimeError("priorityTo needs 0 < priorityNodeID < plca_node_count");
        if (plcaMode == ANCHORED) {
            anchorPeriod = par("anchorPeriod");
            if (anchorPeriod <= SIMTIME_ZERO)
                throw cRuntimeError("anchorPeriod must be positive");
            std::istringstream os(par("anchorOffsets").stdstringValue());
            double us;
            while (os >> us) {
                simtime_t o = SimTime(us * 1e-6);
                if (o < SIMTIME_ZERO || o >= anchorPeriod)
                    throw cRuntimeError("anchor offset %g us outside [0, anchorPeriod)", us);
                anchorOffsets.push_back(o);
            }
            if (anchorOffsets.empty())
                anchorOffsets.push_back(SIMTIME_ZERO);
            std::sort(anchorOffsets.begin(), anchorOffsets.end());
            followerIdleSleep = par("followerIdleSleep");
            std::string late = par("lateBeacon").stdstringValue();
            if (late != "skip" && late != "catchup")
                throw cRuntimeError("lateBeacon must be skip or catchup");
            lateBeaconSkip = late == "skip";
            anchorTimer = new cMessage("anchorTimer", 9999);
            initializeAnchorClock();
        }
        WATCH(anchorArmed);
        WATCH(inPriorityTo);
        WATCH(currentToHadData);
    }
    else if (stage == INITSTAGE_PHYSICAL_LAYER && plcaMode == ANCHORED && local_nodeID == 0 && !anchorArmed) {
        // EthernetPlca starts the control FSM directly in CS_RESYNC (no entry action),
        // so the first anchor is armed here; the first BEACON goes out on the grid.
        armAnchor();
    }
}

void PrioPlca::initializeAnchorClock()
{
    const char *path = par("anchorClockModule");
    if (*path) {
        anchorClock = dynamic_cast<IClock *>(getModuleByPath(path));
        if (anchorClock == nullptr)
            throw cRuntimeError("anchorClockModule '%s' is not an IClock", path);
    }
}

simtime_t PrioPlca::anchorAt(int64_t idx) const
{
    int64_t n = anchorOffsets.size();
    int64_t k = idx >= 0 ? idx / n : -((-idx + n - 1) / n);
    return anchorPeriod * k + anchorOffsets[idx - k * n];
}

int64_t PrioPlca::firstAnchorAtOrAfter(simtime_t t) const
{
    int64_t n = anchorOffsets.size();
    int64_t k = t.raw() / anchorPeriod.raw();
    for (int64_t idx = k * n; ; idx++)
        if (anchorAt(idx) >= t)
            return idx;
}

void PrioPlca::armAnchor()
{
    // The cycle that just ended belonged to anchor lastAnchorIndex; the next one
    // belongs to the following anchor. "skip": wait for the first anchor at or
    // after now. "catchup": if that following anchor has already passed (the
    // cycle overran), send the BEACON at once and assign the cycle to the latest
    // anchor that has passed, so the grid is rejoined at the next one.
    simtime_t now = anchorClock ? anchorClock->getClockTime().asSimTime() : simTime();
    int64_t first = firstAnchorAtOrAfter(now);
    simtime_t at;
    if (lastAnchorIndex < 0 || lateBeaconSkip || lastAnchorIndex + 1 >= first) {
        if (lastAnchorIndex >= 0)
            emit(anchorSkippedSignal, (long)(first - lastAnchorIndex - 1));
        lastAnchorIndex = first;
        simtime_t anchor = anchorAt(first);
        at = anchorClock ? anchorClock->computeSimTimeFromClockTime(ClockTime::from(anchor)) : anchor;
        if (at < simTime())
            at = simTime();
    }
    else {
        emit(anchorLateSignal, now - anchorAt(lastAnchorIndex + 1));
        if (simTime() >= getSimulation()->getWarmupPeriod())
            lateCycles++;
        lastAnchorIndex = first - 1;
        at = simTime();
    }
    emit(anchorHoldSignal, at - simTime());
    if (simTime() >= getSimulation()->getWarmupPeriod()) {
        holdTotal += at - simTime();
        anchorCycles++;
    }
    anchorArmed = true;
    rescheduleAt(at, anchorTimer);
}

void PrioPlca::finish()
{
    EthernetPlca::finish();
    if (plcaMode == ANCHORED && local_nodeID == 0) {
        simtime_t measured = simTime() - getSimulation()->getWarmupPeriod();
        recordScalar("taplcaHoldTotal", holdTotal.dbl(), "s");
        recordScalar("taplcaMeasuredTime", measured.dbl(), "s");
        recordScalar("taplcaHoldShare", measured > 0 ? holdTotal.dbl() / measured.dbl() : 0);
        recordScalar("taplcaCycles", anchorCycles);
        recordScalar("taplcaLateCycles", lateCycles);
    }
}

bool PrioPlca::anchorReady() const
{
    return plcaMode != ANCHORED || (anchorArmed && !anchorTimer->isScheduled());
}

bool PrioPlca::followerSleeping() const
{
    return plcaMode == ANCHORED && followerIdleSleep && local_nodeID != 0 && curID >= plca_node_count;
}

bool PrioPlca::canCommitInPriorityTo() const
{
    // A COMMIT issued right at the end of the priority TO reaches the other
    // nodes after their to_timer has expired (propagation delay), when they
    // have already moved on to the next TO, and causes a collision. The guard
    // keeps late commits out of that window.
    if (!inPriorityTo)
        return true;
    return simTime() - toStartTime <= (priorityToTimerLength - priorityCommitGuard).get<b>() / mode.bitrate;
}

int PrioPlca::currentOwner() const
{
    if (inPriorityTo)
        return priorityNodeID;
    if (plcaMode == MULTI_TO)
        return curID >= 0 && curID < (int)slotOwners.size() ? slotOwners[curID] : -1;
    return curID;
}

void PrioPlca::advanceTransmitOpportunity()
{
    // Every node applies the same rule to what it observed on the bus (did this
    // TO carry data, and how long did it last?), so all nodes stay in sync.
    bool insert = plcaMode == PRIORITY_TO && !inPriorityTo && currentToHadData
            && currentOwner() != priorityNodeID && curID < plca_node_count
            && lastToLength >= minTriggerToLength;
    currentToHadData = false;
    if (insert) {
        inPriorityTo = true;
        if (local_nodeID == 0)
            emit(priorityToInsertedSignal, curID);
    }
    else {
        inPriorityTo = false;
        curID = curID + 1;
    }
    emit(curIDSignal, curID);
}

void PrioPlca::handleWithControlFSM()
{
    // 148.4.4.6 State diagram of IEEE Std 802.3cg-2019
    { FSMA_Switch(controlFsm) {
        FSMA_State(CS_DISABLE) {
            FSMA_Enter(
                if (tx_cmd != CMD_NONE) {
                    FSMA_Delay_Action(phy->endSignalTransmission(ESDNONE));
                    tx_cmd = CMD_NONE;
                    emit(txCmdSignal, tx_cmd);
                }
                committed = false;
                curID = 0;
                emit(curIDSignal, curID);
                inPriorityTo = false; // PrioPlca
                currentToHadData = false; // PrioPlca
            );
            FSMA_Transition(T1,
                            local_nodeID != 0,
                            CS_RESYNC,
            );
            FSMA_Transition(T2,
                            local_nodeID == 0,
                            CS_RECOVER,
            );
        }
        FSMA_State(CS_RESYNC) {
            FSMA_Enter(
                if (plcaMode == ANCHORED && local_nodeID == 0) // PrioPlca: TA-PLCA holds the BEACON until the next anchor
                    armAnchor();
            );
            FSMA_Transition(T1,
                            local_nodeID != 0 && CRS,
                            CS_EARLY_RECEIVE,
            );
            FSMA_Transition(T2,
                            PMCD && !CRS && local_nodeID == 0 && anchorReady(), // PrioPlca: TA-PLCA anchor reached
                            CS_SEND_BEACON,
            );
        }
        FSMA_State(CS_RECOVER) {
            FSMA_Enter(
            );
            FSMA_Transition(T1,
                            true,
                            CS_WAIT_TO,
            );
        }
        FSMA_State(CS_SEND_BEACON) {
            FSMA_Enter(
                anchorArmed = false; // PrioPlca
                scheduleAfter(beacon_timer_length.get<b>() / mode.bitrate, beacon_timer);
                tx_cmd = CMD_BEACON;
                emit(txCmdSignal, tx_cmd);
                FSMA_Delay_Action(phy->startSignalTransmission(BEACON));
            );
            FSMA_Transition(T1,
                            !beacon_timer->isScheduled(),
                            CS_SYNCING,
            );
        }
        FSMA_State(CS_SYNCING) {
            FSMA_Enter(
                // curID = 0; NOTE: this is removed so that the curID gets zero exactly at the first TO start in both the contoller and other nodes
                // emit(curIDSignal, curID);
                if (tx_cmd != CMD_NONE) {
                    FSMA_Delay_Action(phy->endSignalTransmission(ESDNONE));
                    tx_cmd = CMD_NONE;
                    emit(txCmdSignal, tx_cmd);
                }
                if (local_nodeID == 0)
                    // the syncing timer separates the BEACON and the following COMMIT/DATA signals with a small amount of time
                    // this is done for non-controller nodes to have a CRS OFF/ON spike in the SYNCING state to allow them to go into WAIT_TO
                    scheduleAfter(1E-9, syncing_timer);
            );
            FSMA_Transition(T1,
                            !CRS && !syncing_timer->isScheduled(),
                            CS_WAIT_TO,
                curID = 0;
                emit(curIDSignal, curID);
                inPriorityTo = false; // PrioPlca
                currentToHadData = false; // PrioPlca
                if (cycleStartTime != -1) {
                    emit(numPacketsPerCycleSignal, numPacketsPerCycle);
                    emit(cycleLengthSignal, simTime() - cycleStartTime);
                }
                numPacketsPerCycle = 0;
                cycleStartTime = simTime();
            );
        }
        FSMA_State(CS_WAIT_TO) {
            FSMA_Enter(
                if (!followerSleeping()) // PrioPlca: TA-PLCA followers past the last TO just wait for the BEACON
                    scheduleAfter((inPriorityTo ? priorityToTimerLength : to_timer_length).get<b>() / mode.bitrate, to_timer); // PrioPlca: the priority TO outlasts the IPG
                numPacketsPerTo = 0;
                toStartTime = simTime();
            );
            FSMA_Transition(T1,
                            CRS,
                            CS_EARLY_RECEIVE,
            );
            FSMA_Transition(T2,
                            ownsCurrentTo() && packetPending && !CRS && canCommitInPriorityTo(), // PrioPlca: in the priority TO, only before the guard window
                            CS_COMMIT,
            );
            FSMA_Transition(T3,
                            !to_timer->isScheduled() && !ownsCurrentTo() && !CRS && !followerSleeping(), // PrioPlca
                            CS_NEXT_TX_OPPORTUNITY,
            );
            FSMA_Transition(T4,
                            ownsCurrentTo() && !CRS && (inPriorityTo ? !to_timer->isScheduled() : !packetPending), // PrioPlca: in the priority TO, wait for a frame until the timer expires
                            CS_YIELD,
            );
        }
        FSMA_State(CS_EARLY_RECEIVE) {
            FSMA_Enter(
                cancelEvent(to_timer);
                rescheduleAfter(beacon_det_timer_length.get<b>() / mode.bitrate, beacon_det_timer);
            );
            // TODO this transition takes normal nodes to the first transmit opportunity too early because BEACON is detected at RECEPTION_START
            FSMA_Transition(T1, // D
                            local_nodeID != 0 && !receiving && (rx_cmd == CMD_BEACON || (!CRS && beacon_det_timer->isScheduled())),
                            CS_SYNCING,
            );
            FSMA_Transition(T2, // B
                            !CRS && local_nodeID != 0 && rx_cmd != CMD_BEACON && !beacon_det_timer->isScheduled(),
                            CS_RESYNC,
            );
            FSMA_Transition(T3, // C
                            !CRS && local_nodeID == 0,
                            CS_RECOVER,
            );
            FSMA_Transition(T4,
                            receiving && CRS,
                            CS_RECEIVE,
            );
        }
        FSMA_State(CS_COMMIT) {
            FSMA_Enter(
                tx_cmd = CMD_COMMIT;
                emit(txCmdSignal, tx_cmd);
                FSMA_Delay_Action(phy->startSignalTransmission(COMMIT));
                committed = true;
                cancelEvent(to_timer);
                bc = 0;
                emit(transmitOpportunityUsedSignal, 1);
                FSMA_Delay_Action(handleWithDataFSM(COMMIT_TO, nullptr));
            );
            FSMA_Transition(T1,
                            TX_EN,
                            CS_TRANSMIT,
            );
            FSMA_Transition(T2,
                            !TX_EN && !packetPending,
                            CS_ABORT,
            );
        }
        FSMA_State(CS_YIELD) {
            FSMA_Enter(
                emit(transmitOpportunityUsedSignal, 0);
            );
            FSMA_Transition(T1,
                            CRS && to_timer->isScheduled(),
                            CS_EARLY_RECEIVE,
            );
            FSMA_Transition(T2,
                            !to_timer->isScheduled(),
                            CS_NEXT_TX_OPPORTUNITY,
            );
        }
        FSMA_State(CS_RECEIVE) {
            FSMA_Enter(
                currentToHadData = true; // PrioPlca
            );
            FSMA_Transition(T1,
                            !CRS,
                            CS_NEXT_TX_OPPORTUNITY,
            );
        }
        FSMA_State(CS_TRANSMIT) {
            FSMA_Enter(
                currentToHadData = true; // PrioPlca
                if (tx_cmd != CMD_NONE) {
                    FSMA_Delay_Action(phy->endSignalTransmission(ESDNONE));
                    tx_cmd = CMD_NONE;
                    emit(txCmdSignal, tx_cmd);
                }
                if (bc >= max_bc)
                    committed = false;
            );
            FSMA_Transition(T1,
                            !TX_EN && !CRS && bc >= max_bc,
                            CS_NEXT_TX_OPPORTUNITY,
            );
            FSMA_Transition(T2,
                            !TX_EN && bc < max_bc,
                            CS_BURST,
            );
        }
        FSMA_State(CS_BURST) {
            FSMA_Enter(
                bc = bc + 1;
                tx_cmd = CMD_COMMIT;
                emit(txCmdSignal, tx_cmd);
                FSMA_Delay_Action(phy->startSignalTransmission(COMMIT));
                scheduleAfter(burst_timer_length.get<b>() / mode.bitrate, burst_timer);
            );
            FSMA_Transition(T1,
                            TX_EN,
                            CS_TRANSMIT,
                cancelEvent(burst_timer);
            );
            FSMA_Transition(T2,
                            !TX_EN && !burst_timer->isScheduled(),
                            CS_ABORT,
            );
        }
        FSMA_State(CS_ABORT) {
            FSMA_Enter(
                if (tx_cmd != CMD_NONE) {
                    FSMA_Delay_Action(phy->endSignalTransmission(ESD));
                    tx_cmd = CMD_NONE;
                    emit(txCmdSignal, tx_cmd);
                }
            );
            FSMA_Transition(T1,
                            !CRS,
                            CS_NEXT_TX_OPPORTUNITY,
            );
        }
        FSMA_State(CS_NEXT_TX_OPPORTUNITY) {
            FSMA_Enter(
                lastToLength = toStartTime != -1 ? simTime() - toStartTime : SIMTIME_ZERO; // PrioPlca
                if (toStartTime != -1) {
                    emit(numPacketsPerToSignal, numPacketsPerTo);
                    emit(toLengthSignal, simTime() - toStartTime);
                    if (ownsCurrentTo()) {
                        emit(numPacketsPerOwnToSignal, numPacketsPerTo);
                        emit(ownToLengthSignal, simTime() - toStartTime);
                    }
                    numPacketsPerTo = -1;
                    toStartTime = -1;
                }
                advanceTransmitOpportunity(); // PrioPlca: replaces curID = curID + 1
                committed = false;
            );
            FSMA_Transition(T1, // B
                            (local_nodeID == 0 && curID >= plca_node_count),
                            CS_RESYNC,
            );
            FSMA_Transition(T2,
                            true,
                            CS_WAIT_TO,
            );
        }
    } }
    controlFsm.executeDelayedActions();
}

} // namespace ivnplca
