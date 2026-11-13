//
// Copyright (C) 2023 OpenSim Ltd. (EthernetPlca, from which this module is derived)
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// PrioPlca: experimental variants of PLCA (IEEE 802.3cg, Clause 148) built on
// top of the INET EthernetPlca model. Simulation only; used to compare
// differentiated medium-access mechanisms on 10BASE-T1S.
//
// Modes ("mode" parameter; every node on the segment must use the same one):
//   standard   : PLCA as specified (behaves exactly like EthernetPlca).
//   multiTo    : the cycle is the slot list in "slotOwners" (e.g. "0 1 2 1 3 1 4"),
//                so a node may own more than one TO per cycle (static extra TOs).
//   priorityTo : after every TO that carried data, an extra TO owned by
//                "priorityNodeID" is inserted before moving on to the next node.
//                If the priority node has nothing to send, the extra TO only
//                costs priorityToTimerLength. Combined with fragmented background
//                traffic it approximates frame preemption at fragment boundaries.
//                The priority TO must outlast the IPG (96 bits): a frame that
//                reached the priority node's MAC while another node was
//                transmitting is only released after the IPG, and the default
//                to_timer (32 bits) would expire before that.
//   anchored   : Time-Anchored PLCA (TA-PLCA). Only the coordinator differs from
//                standard PLCA: at the end of a cycle it holds the BEACON until the
//                next anchor instant k * anchorPeriod + o (o in anchorOffsets) of its
//                clock (the gPTP-synchronized zonal switch clock in anchorClockModule,
//                or simulation time = ideal clock when empty). If a cycle ends after
//                its anchor: lateBeacon = "catchup" sends the BEACON at once and
//                rejoins the grid at the next anchor (work-conserving under
//                overload); "skip" waits for the next anchor (every cycle on the grid).
//                Followers run standard PLCA; with followerIdleSleep they do not
//                re-arm to_timer past the last TO of the cycle (they own no TO there,
//                so this only removes idle events; the bus behaviour is identical).
//
#ifndef __IVNPLCA_PRIOPLCA_H
#define __IVNPLCA_PRIOPLCA_H

#include <vector>

#include "inet/clock/contract/IClock.h"
#include "inet/physicallayer/wired/ethernet/EthernetPlca.h"

namespace ivnplca {

using namespace inet;
using namespace inet::physicallayer;

class PrioPlca : public EthernetPlca
{
  public:
    static simsignal_t priorityToInsertedSignal;
    static simsignal_t anchorHoldSignal;
    static simsignal_t anchorSkippedSignal;
    static simsignal_t anchorLateSignal;

    virtual ~PrioPlca();

  protected:
    enum Mode { STANDARD, MULTI_TO, PRIORITY_TO, ANCHORED };
    Mode plcaMode = STANDARD;
    int priorityNodeID = -1;
    simtime_t minTriggerToLength;
    b priorityToTimerLength = b(-1);
    b priorityCommitGuard = b(-1);
    std::vector<int> slotOwners;

    bool inPriorityTo = false;
    bool currentToHadData = false;
    simtime_t lastToLength;

    // anchored (TA-PLCA)
    simtime_t anchorPeriod;
    std::vector<simtime_t> anchorOffsets;  // sorted, each in [0, anchorPeriod)
    IClock *anchorClock = nullptr;
    bool followerIdleSleep = true;
    bool lateBeaconSkip = false;
    cMessage *anchorTimer = nullptr;
    bool anchorArmed = false;
    int64_t lastAnchorIndex = -1;
    simtime_t holdTotal;
    long anchorCycles = 0;
    long lateCycles = 0;

  protected:
    virtual void initialize(int stage) override;
    virtual void handleWithControlFSM() override;
    virtual void finish() override;

    bool canCommitInPriorityTo() const;
    int currentOwner() const;
    bool ownsCurrentTo() const { return currentOwner() == local_nodeID; }
    void advanceTransmitOpportunity();
    void initializeAnchorClock();
    simtime_t anchorAt(int64_t idx) const;
    int64_t firstAnchorAtOrAfter(simtime_t t) const;
    void armAnchor();
    bool anchorReady() const;
    bool followerSleeping() const;
};

} // namespace ivnplca

#endif
