#ifndef ZONAL_CATALOG_COLOR_PACKET_H
#define ZONAL_CATALOG_COLOR_PACKET_H

#include "inet/common/packet/Packet.h"

/** Packet whose Qtenv animation color reflects its PCP (or lack of PCP). */
class CatalogColorPacket : public inet::Packet
{
    int visualPcp = -1;

  public:
    explicit CatalogColorPacket(const char *name) : inet::Packet(name) {}
    CatalogColorPacket(const CatalogColorPacket&) = default;

    void setVisualPcp(int pcp) { visualPcp = pcp >= 0 && pcp <= 7 ? pcp : -1; }
    CatalogColorPacket *dup() const override { return new CatalogColorPacket(*this); }

    const char *getDisplayString() const override
    {
        static const char *displayStrings[] = {
            "b=8,8,oval,#E69F00", "b=8,8,oval,#56B4E9", "b=8,8,oval,#009E73",
            "b=8,8,oval,#F0E442", "b=8,8,oval,#0072B2", "b=8,8,oval,#D55E00",
            "b=8,8,oval,#CC79A7", "b=8,8,oval,#000000", "b=8,8,oval,#666666"
        };
        return displayStrings[visualPcp >= 0 ? visualPcp : 8];
    }
};

#endif
