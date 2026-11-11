import html
cells = []; n = [1]
def nid():
    n[0] += 1; return f"c{n[0]}"
def box(x, y, w, h, label, style):
    i = nid(); cells.append(f'<mxCell id="{i}" value="{html.escape(label)}" style="{style}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'); return i
def edge(s, t, style, label=""):
    i = nid(); cells.append(f'<mxCell id="{i}" value="{html.escape(label)}" style="{style}" edge="1" parent="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry"/></mxCell>'); return i
def line(x1, y1, x2, y2, style):
    i = nid(); cells.append(f'<mxCell id="{i}" value="" style="{style}" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/><mxPoint x="{x2}" y="{y2}" as="targetPoint"/></mxGeometry></mxCell>')

SW = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#2563eb;fontStyle=1;fontSize=12;"
HPC = "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#7c3aed;fontStyle=1;fontSize=12;"
EP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#9ca3af;fontSize=10;fontColor=#374151;"
T1N = "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;fontStyle=1;"
WIN = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;"
ZONE = "rounded=1;whiteSpace=wrap;html=1;fillColor=none;dashed=1;strokeColor=#94a3b8;verticalAlign=bottom;align=left;spacingLeft=8;spacingBottom=6;fontSize=12;fontStyle=1;fontColor=#475569;"
NOTE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#cbd5e1;align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;fontSize=10;"
GB = "endArrow=none;html=1;strokeWidth=3;strokeColor=#1e3a8a;"
P2P = "endArrow=none;html=1;strokeWidth=1;strokeColor=#9ca3af;"
T1S = "endArrow=none;html=1;strokeWidth=4;strokeColor=#a855f7;"
DROP = "endArrow=none;html=1;strokeWidth=2;strokeColor=#a855f7;"
FLOW = "endArrow=classic;startArrow=classic;html=1;strokeWidth=2;strokeColor=#dc2626;dashed=1;fontSize=10;fontColor=#dc2626;curved=1;"

box(20, 10, 1400, 30, "Dual 10BASE-T1S buses in the ZB-3T zonal network — powertrain scenario (current simulation)", "text;html=1;fontSize=16;fontStyle=1;align=left;")
hpc = box(620, 60, 200, 50, "HPC (vehicle computer)<br><font style='font-size:10px'>gPTP grandmaster</font>", HPC)
csw = box(620, 160, 200, 50, "CSW (central switch)<br><font style='font-size:10px'>gPTP bridge</font>", SW)
edge(hpc, csw, GB, "1 Gb/s")
zx = {1: 40, 2: 520, 3: 980}
zsw = {}
for z, x in zx.items():
    w = 420 if z != 2 else 420
    box(x - 10, 250, w, 520, f"Zone Z{z}" + ("  (unchanged, 100 Mb/s links)" if z == 2 else ""), ZONE)
    zsw[z] = box(x + 110, 285, 180, 50, f"Z{z}.ZSW (zonal switch)<br><font style='font-size:10px'>gPTP slave</font>", SW)
    edge(csw, zsw[z], GB, "1 Gb/s")
# point-to-point endpoints (catalog, unchanged)
p2p = {1: ["LiDAR1", "CAM1", "BRAKE1", "AUDIO1", "DISPLAY1", "BE1"],
       2: ["RADAR1", "CAM2", "BRAKE2", "WINDOW2", "AUDIO2", "DISPLAY2", "BE2"],
       3: ["RADAR2", "CAM3", "CAM4", "BRAKE3", "AUDIO3", "BE3"]}
for z, names in p2p.items():
    x0 = zx[z]
    grp = box(x0, 365, 300, 90 if z != 2 else 125, "", "rounded=1;whiteSpace=wrap;html=1;fillColor=#fafafa;strokeColor=#d1d5db;")
    box(x0 + 8, 368, 290, 16, "Catalog endpoints, 100 Mb/s point-to-point", "text;html=1;fontSize=9;fontColor=#6b7280;align=left;")
    for k, nm in enumerate(names):
        col, row = k % 3, k // 3
        box(x0 + 8 + col * 96, 388 + row * 33, 90, 26, nm, EP)
    edge(zsw[z], grp, P2P + "strokeWidth=2;exitX=0.25;exitY=1;entryX=0.25;entryY=0;")
# T1S buses
bus = {1: ("ECM", "ETC", "MAP", "LAMBDA"), 3: ("TCU", "APP", "GEAR", "OSS")}
desc = {"ECM": "ECM (injection ECU)", "ETC": "ETC (throttle)", "MAP": "MAP sensor", "LAMBDA": "Lambda sensor",
        "TCU": "TCU (transmission)", "APP": "APP (pedal)", "GEAR": "Gear selector", "OSS": "Output speed"}
node = {}
for z, names in bus.items():
    x0 = zx[z]; by = 560
    gate = box(x0 + 5, 470, 390, 40, f"ZSW T1S port = PLCA coordinator (ID 0)<br>TAS gate: TC3 (window) closed 0–400 µs of every ms", "rounded=1;whiteSpace=wrap;html=1;fillColor=#ede9fe;strokeColor=#7c3aed;fontSize=10;")
    line(x0 + 270, 335, x0 + 270, 345, DROP); line(x0 + 270, 345, x0 + 350, 345, DROP); line(x0 + 350, 345, x0 + 350, 470, DROP)
    line(x0, by, x0 + 400, by, T1S)
    box(x0 + 250, by - 22, 150, 18, f"10BASE-T1S bus {'A' if z == 1 else 'B'} · 10 Mb/s · PLCA", "text;html=1;fontSize=10;fontColor=#7e22ce;fontStyle=1;align=right;")
    line(x0 + 200, 510, x0 + 200, by, DROP)
    items = [("WINDOW" + str(z), 1)] + [(nm, i + 2) for i, nm in enumerate(names)]
    for k, (nm, pid) in enumerate(items):
        x = x0 + k * 80
        line(x + 37, by, x + 37, by + 30, DROP)
        b = box(x, by + 30, 75, 46, f"{desc.get(nm, nm)}<br><font style='font-size:9px'>PLCA ID {pid}</font>", WIN if nm.startswith("WINDOW") else T1N)
        node[nm] = b
# cross-bus flows: explicit lanes under the nodes
def poly(pts, style):
    i = nid()
    mid = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in pts[1:-1])
    cells.append(f'<mxCell id="{i}" value="" style="{style}" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                 f'<mxPoint x="{pts[0][0]}" y="{pts[0][1]}" as="sourcePoint"/><mxPoint x="{pts[-1][0]}" y="{pts[-1][1]}" as="targetPoint"/>'
                 f'<Array as="points">{mid}</Array></mxGeometry></mxCell>')
F = "endArrow=classic;startArrow=classic;html=1;strokeWidth=2;strokeColor=#dc2626;dashed=1;edgeStyle=none;"
ecm_x, tcu_x, app_x = zx[1] + 80 + 37, zx[3] + 2 * 80 + 37 - 80, zx[3] + 2 * 80 + 37
poly([(ecm_x - 15, 636), (ecm_x - 15, 680), (tcu_x, 680), (tcu_x, 636)], F)
poly([(ecm_x + 15, 636), (ecm_x + 15, 715), (app_x, 715), (app_x, 636)], F)
box(ecm_x + 60, 662 - 14, 520, 16, "PT01 TSC1 torque request TCU→ECM + response (10 ms; 1 ms stress)", "text;html=1;fontSize=10;fontColor=#dc2626;align=left;")
box(ecm_x + 60, 697 - 14, 520, 16, "PT02 pedal position read ECM→APP + response (10 ms; 1 ms stress)", "text;html=1;fontSize=10;fontColor=#dc2626;align=left;")
box(500, 735, 460, 40, "Cross-bus path: T1S bus A → Z1.ZSW → CSW → Z3.ZSW → T1S bus B<br>+ PT03 EEC1 ECM→TCU, PT04 ETC1 TCU→ECM (10 ms) · all VLAN 40 / PCP 7", "rounded=1;whiteSpace=wrap;html=1;fillColor=#fef2f2;strokeColor=#dc2626;fontSize=10;fontColor=#991b1b;")
legend = box(20, 800, 1390, 100,
    "<b>Legend & settings</b><br>"
    "Dark blue = 1 Gb/s backbone · grey = original 100 Mb/s point-to-point catalog links · purple = 10BASE-T1S multidrop (PLCA, max_bc 0, to_timer 32 bit)<br>"
    "Yellow = new T1S nodes (all traffic PCP 7 = highest catalog class, shared with brake F08–F10) · red = WINDOW1/3 (catalog flow F15/F17, PCP 3) · dashed red = cross-bus request/response<br>"
    "Scheduling: sensor/ECU releases at fixed offsets inside each 1 ms (cross-bus flows first) · clocks drift U(−50, 50) ppm, gPTP Sync 125 ms, Pdelay 1 s · T1S nodes use their zonal switch clock<br>"
    "Same-bus loops: ECM↔ETC 1 ms, MAP→ECM 1 ms, LAMBDA→ECM 10 ms, GEAR/OSS→TCU 10 ms · EV variant: bus A = VCU, INVF, DCDC, TMS; bus B = BMS, INVR, OBC, USS", NOTE)
xml = ('<mxfile host="drawio"><diagram id="t1s" name="Dual T1S buses"><mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" page="1" pageWidth="1440" pageHeight="930">'
       '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + '</root></mxGraphModel></diagram></mxfile>')
open("/home/jean/zonal-ivn-tsn/docs/figures/dual_t1s_scenario.drawio", "w").write(xml)
print("ok", len(cells))
