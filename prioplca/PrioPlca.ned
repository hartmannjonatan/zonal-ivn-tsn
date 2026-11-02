//
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

import inet.physicallayer.wired.ethernet.EthernetPlca;

//
// Experimental PLCA variants (standard, multiTo, priorityTo). See src/PrioPlca.h.
// Usage: **.eth[0].plca.typename = "PrioPlca" on EVERY node of the segment.
//
simple PrioPlca extends EthernetPlca
{
    parameters:
        @class(ivnplca::PrioPlca);
        string mode @enum("standard","multiTo","priorityTo") = default("standard");
        int priorityNodeID = default(-1);                  // owner of the priority TO (the gateway)
        double minTriggerToLength @unit(s) = default(0s);  // only insert a priority TO after data TOs at least this long
        int priorityToTimerLength @unit(b) = default(128b); // length of an unused priority TO; must exceed the IPG (96 bits)
        int priorityCommitGuard @unit(b) = default(16b);    // the priority node may not start a COMMIT in the last bits of the priority TO
        string slotOwners = default("");                   // multiTo: owner of each slot in the cycle, space separated
        @signal[priorityToInserted](type=long);
        @statistic[priorityToInserted](title="priority TOs inserted"; record=count,vector);
}
