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
//
#ifndef __IVNPLCA_PRIOPLCA_H
#define __IVNPLCA_PRIOPLCA_H

#include <vector>

#include "inet/physicallayer/wired/ethernet/EthernetPlca.h"

namespace ivnplca {

using namespace inet;
using namespace inet::physicallayer;

class PrioPlca : public EthernetPlca
{
  public:
    static simsignal_t priorityToInsertedSignal;

  protected:
    enum Mode { STANDARD, MULTI_TO, PRIORITY_TO };
    Mode plcaMode = STANDARD;
    int priorityNodeID = -1;
    simtime_t minTriggerToLength;
    b priorityToTimerLength = b(-1);
    b priorityCommitGuard = b(-1);
    std::vector<int> slotOwners;

    bool inPriorityTo = false;
    bool currentToHadData = false;
    simtime_t lastToLength;

  protected:
    virtual void initialize(int stage) override;
    virtual void handleWithControlFSM() override;

    bool canCommitInPriorityTo() const;
    int currentOwner() const;
    bool ownsCurrentTo() const { return currentOwner() == local_nodeID; }
    void advanceTransmitOpportunity();
};

} // namespace ivnplca

#endif
