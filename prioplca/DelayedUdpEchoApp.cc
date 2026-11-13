//
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
#include "DelayedUdpEchoApp.h"

#include "inet/networklayer/common/L3AddressTag_m.h"
#include "inet/transportlayer/common/L4PortTag_m.h"
#include "inet/common/Simsignals.h"

namespace ivnplca {

Define_Module(DelayedUdpEchoApp);

void DelayedUdpEchoApp::handleMessageWhenUp(cMessage *msg)
{
    if (msg->isSelfMessage()) {
        auto pk = check_and_cast<Packet *>(msg);
        auto reply = static_cast<Reply *>(pk->getContextPointer());
        pk->setContextPointer(nullptr);
        numEchoed++;
        emit(inet::packetSentSignal, pk);
        socket.sendTo(pk, reply->address, reply->port);
        delete reply;
    }
    else
        UdpEchoApp::handleMessageWhenUp(msg);
}

void DelayedUdpEchoApp::socketDataArrived(UdpSocket *socket, Packet *pk)
{
    auto reply = new Reply{pk->getTag<L3AddressInd>()->getSrcAddress(), pk->getTag<L4PortInd>()->getSrcPort()};
    pk->clearTags();
    pk->trim();
    simtime_t d = par("processingTime");
    if (d < SIMTIME_ZERO)
        d = SIMTIME_ZERO;
    pk->setContextPointer(reply);
    scheduleAfter(d, pk);
}

} // namespace ivnplca
