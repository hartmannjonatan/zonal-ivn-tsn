//
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// UdpEchoApp with a server processing time: every request is echoed after
// "processingTime" (volatile, drawn per request). Used to add the measured
// gateway processing time (Raspberry Pi 5, SCHED_FIFO, isolated core: 2.9 us
// mean, 4.0 us P99) to the request/response flows.
//
#ifndef __IVNPLCA_DELAYEDUDPECHOAPP_H
#define __IVNPLCA_DELAYEDUDPECHOAPP_H

#include "inet/applications/udpapp/UdpEchoApp.h"

namespace ivnplca {

using namespace inet;

class DelayedUdpEchoApp : public UdpEchoApp
{
  protected:
    struct Reply { L3Address address; int port; };

  protected:
    virtual void handleMessageWhenUp(cMessage *msg) override;
    virtual void socketDataArrived(UdpSocket *socket, Packet *packet) override;
};

} // namespace ivnplca

#endif
