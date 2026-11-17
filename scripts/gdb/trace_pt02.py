# gdb helper (debug build compiled with -ggdb, see below): follow one PT02 request/response
# (ECM on the Z1 bus -> APP on the Z3 bus -> ECM) through the switches.
#
# Breakpoints (all non-stopping; they print and continue):
#   ingress  RelayInterfaceSelector::pushPacket   the switch relay decides the egress port(s)
#   enqueue  PacketQueue::pushPacket              the frame enters an egress queue (queue[i] = PCP i)
#   dequeue  PacketQueue::pullPacket              the scheduler hands it to the MAC (on a T1S port the
#                                                 MAC then holds it until the node's PLCA transmit opportunity)
#   to-plca  EthernetPlca::startFrameTransmission the MAC hands the frame to PLCA, which sends it in the
#                                                 node's next TO (curID = PLCA state at that moment)
#   rx       EthernetPlca::handleReceptionEnd     the frame has been received from the T1S wire
# At each hit: sim time, module path, frame length, PCP (from the queue index), how many frames
# were already in that queue and in the other queues of the same port, and a short backtrace.
#
# Build (OMNeT++ default CFLAGS_DEBUG uses -glldb, which gdb 17 cannot read with clang 21):
#   make MODE=debug CFLAGS_DEBUG="-O0 -Wall -ggdb -fstandalone-debug"   (INET, prioplca, src)
# Run from simulations/:
#   gdb -batch -x ../scripts/gdb/trace_pt02.py --args ../src/zonal-ivn-tsn_dbg \
#     -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca \
#     -f zonal_t1s_taplca.ini -u Cmdenv -c TA_NOMINAL_EVC_G35_R150_30s -r 0 --sim-time-limit=10.6ms
#     -f zonal_t1s_taplca.ini ... --sim-time-limit=1.0107s   (with the defaults below)
# Env: PKT = packet name (default PT02-100: released at 1.009985 s, the first period after the 1 s
#      warm-up; earlier packets see start-up transients), ARM = sim time in s at which the tracing
#      breakpoints are enabled (default 1.0099), BT = backtrace depth (default 8).
# Until ARM only one cheap breakpoint (ActivePacketSource::producePacket, a few hits per ms) is active.
import os
import re

import gdb

PKT = os.environ.get("PKT", "PT02-100")
ARM = float(os.environ.get("ARM", "1.0099"))
BT = int(os.environ.get("BT", "8"))
gdb.execute("set pagination off")
gdb.execute("set breakpoint pending on")
gdb.execute("set print pretty off")
gdb.execute("set confirm off")


def ev(expr):
    return gdb.parse_and_eval(expr)


def now_us():
    return float(ev("omnetpp::cSimulation::activeSimulation->currentSimtime.dbl()")) * 1e6


def path():
    return ev("this->getFullPath()")["_M_dataplus"]["_M_p"].string().replace("ZonalIVNT1SPowertrain.", "")


def is_ours(pkt_expr):
    try:
        name = ev(f"{pkt_expr}->getName()").string()
    except gdb.error:
        return False
    return name == PKT


def backtrace():
    frames, f = [], gdb.newest_frame()
    while f is not None and len(frames) < BT:
        n = f.name() or "??"
        frames.append(re.sub(r"\(.*", "", n))
        f = f.older()
    print("      bt: " + " <- ".join(frames))


def port_queues(p):
    """frames in queue[0..7] of the port whose queue[i] is at path p."""
    out = []
    try:
        parent = ev("this->getParentModule()")
        for i in range(8):
            sub = ev(f"((omnetpp::cModule*){int(parent)})->getSubmodule(\"queue\", {i})")
            if int(sub) == 0:
                break
            out.append(int(ev(f"((inet::queueing::PacketQueue*){int(sub)})->getNumPackets()")))
    except gdb.error:
        pass
    return out


class Ingress(gdb.Breakpoint):
    def stop(self):
        if is_ours("packet"):
            print(f"[{now_us():12.4f} us] ingress  {path()}  len={int(ev('packet->getByteLength()'))} B")
            backtrace()
        return False


class Enqueue(gdb.Breakpoint):
    def stop(self):
        if is_ours("packet"):
            p = path()
            m = re.search(r"queue\[(\d)\]$", p)
            print(f"[{now_us():12.4f} us] enqueue  {p}  len={int(ev('packet->getByteLength()'))} B"
                  f"  PCP/TC={m.group(1) if m else '-'}  port queues before={port_queues(p)}")
            backtrace()
        return False


class Dequeue(gdb.Breakpoint):
    def stop(self):
        try:
            if int(ev("this->getNumPackets()")) == 0:
                return False
            head = "this->getPacket(0)"
        except gdb.error:
            return False
        if is_ours(head):
            p = path()
            print(f"[{now_us():12.4f} us] dequeue  {p}  port queues (incl. this frame)={port_queues(p)}")
        return False


# Symbols only for the libraries we need: the Qtenv debug library (not used under Cmdenv) carries
# DWARF that gdb 17 cannot read, and reading it aborts gdb.
gdb.execute("set auto-solib-add off")
gdb.execute("catch load prioplca")
gdb.execute("run")
for lib in ("libINET", "liboppsim", "liboppcommon", "liboppenvir", "liboppcmdenv", "libprioplca"):
    gdb.execute(f"sharedlibrary {lib}")
gdb.execute("delete")
class PlcaTx(gdb.Breakpoint):
    def stop(self):
        if is_ours("packet"):
            print(f"[{now_us():12.4f} us] to-plca  {path()}  PLCA curID={int(ev('this->curID'))}"
                  f" local_nodeID={int(ev('this->local_nodeID'))}")
        return False


class PlcaRx(gdb.Breakpoint):
    def stop(self):
        if is_ours("packet"):
            print(f"[{now_us():12.4f} us] rx       {path()}")
        return False


TRACE = [PlcaTx("inet::physicallayer::EthernetPlca::startFrameTransmission"),
         PlcaRx("inet::physicallayer::EthernetPlca::handleReceptionEnd"),
         Ingress("inet::RelayInterfaceSelector::pushPacket"),
         Enqueue("inet::queueing::PacketQueue::pushPacket"),
         Dequeue("inet::queueing::PacketQueue::pullPacket")]
for b in TRACE:
    b.enabled = False


class Arm(gdb.Breakpoint):
    def stop(self):
        if now_us() >= ARM * 1e6:
            print(f"[{now_us():12.4f} us] armed (tracing {PKT})")
            for b in TRACE:
                b.enabled = True
            self.enabled = False
        return False


Arm("inet::queueing::ActivePacketSource::producePacket")
gdb.execute("continue")
