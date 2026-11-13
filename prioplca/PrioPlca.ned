//
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

import inet.physicallayer.wired.ethernet.EthernetPlca;

//
// Experimental PLCA variants (standard, multiTo, priorityTo, anchored = TA-PLCA). See src/PrioPlca.h.
// Usage: **.eth[0].plca.typename = "PrioPlca" on EVERY node of the segment.
//
simple PrioPlca extends EthernetPlca
{
    parameters:
        @class(ivnplca::PrioPlca);
        string mode @enum("standard","multiTo","priorityTo","anchored") = default("standard");
        int priorityNodeID = default(-1);                  // owner of the priority TO (the gateway)
        double minTriggerToLength @unit(s) = default(0s);  // only insert a priority TO after data TOs at least this long
        int priorityToTimerLength @unit(b) = default(128b); // length of an unused priority TO; must exceed the IPG (96 bits)
        int priorityCommitGuard @unit(b) = default(16b);    // the priority node may not start a COMMIT in the last bits of the priority TO
        string slotOwners = default("");                   // multiTo: owner of each slot in the cycle, space separated
        double anchorPeriod @unit(s) = default(1ms);       // anchored: anchor grid period T_A
        string anchorOffsets = default("0");               // anchored: anchor instants within each period, in us, space separated
        string anchorClockModule = default("");            // anchored: coordinator clock (e.g. "^.^.clock"); empty = ideal clock (simulation time)
        string lateBeacon @enum("catchup","skip") = default("catchup"); // anchored: what to do when a cycle overruns its anchor
        bool followerIdleSleep = default(true);            // anchored: followers do not count idle TOs after the last one (event saving only)
        @signal[priorityToInserted](type=long);
        @signal[anchorHold](type=simtime_t);
        @signal[anchorSkipped](type=long);
        @signal[anchorLate](type=simtime_t);
        @statistic[anchorLate](title="TA-PLCA late cycles (overrun past the anchor)"; record=count,mean,max; unit=s);
        @statistic[anchorHold](title="TA-PLCA BEACON hold time"; record=count,sum,mean,max; unit=s);
        @statistic[anchorSkipped](title="TA-PLCA anchors skipped per cycle"; record=count,sum,max);
        @statistic[priorityToInserted](title="priority TOs inserted"; record=count,vector);
}
