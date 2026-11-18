//
// Copyright (C) 2026 Jean Carlos Macedo
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

import inet.applications.udpapp.UdpEchoApp;

//
// UdpEchoApp that echoes each request after a server processing time.
//
simple DelayedUdpEchoApp extends UdpEchoApp
{
    parameters:
        @class(ivnplca::DelayedUdpEchoApp);
        volatile double processingTime @unit(s) = default(0s);
}
