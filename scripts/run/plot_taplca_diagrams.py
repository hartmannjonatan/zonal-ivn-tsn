#!/usr/bin/env python3
"""Column-width diagrams for the TA-PLCA paper (10 pt sans-serif, drawn at final size, PDF + PNG).

dual_t1s_scenario_10pt : the dual 10BASE-T1S powertrain scenario (bus A on Z1, bus B on Z3),
                         coordinators marked as gPTP-anchored BEACON sources
taplca_rounds          : schematic of TA-PLCA rounds on the two segments (per-segment anchor
                         phase) and of the two directions of a cross-bus request/response
Output: simulations/zonal/t1s_results/figures/.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "simulations/zonal/t1s_results/figures"
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial"], "font.size": 10})
INK, MUTED, GRID = "#222222", "#666666", "#cfcfca"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
W = 3.45   # IEEE column width (in)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=300, bbox_inches="tight", pad_inches=0.02)
    print("written", OUT / f"{name}.pdf")


def node(ax, x, y, w, h, text, fc="#ffffff", ec=INK, bold=False, size=10):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                fc=fc, ec=ec, lw=0.8))
    ax.text(x, y, text, ha="center", va="center", fontsize=size, fontweight="bold" if bold else "normal", color=INK)


def scenario():
    fig, ax = plt.subplots(figsize=(W, 2.45))
    ax.set_xlim(-0.25, 10.25); ax.set_ylim(0, 7.1); ax.axis("off")
    node(ax, 5, 6.55, 2.2, 0.75, "HPC (GM)", fc="#ece8f7", bold=True)
    node(ax, 5, 5.25, 2.2, 0.75, "CSW", fc="#e3edf9", bold=True)
    ax.plot([5, 5], [6.17, 5.62], color=INK, lw=1.4)
    zx = {1: 1.7, 2: 5.0, 3: 8.3}
    for z, x in zx.items():
        node(ax, x, 3.85, 2.0, 0.75, f"Z{z}", fc="#e3edf9", bold=True)
        ax.plot([5, x], [4.87, 4.23], color=INK, lw=1.4)
    ax.text(5, 2.95, "catalog end\npoints", ha="center", va="center", fontsize=8, color=MUTED)
    ax.text(6.9, 5.25, "TSN backbone\ngPTP, 802.1Qbv", ha="left", va="center", fontsize=8, color=MUTED)
    # T1S buses
    for z, label, nodes in ((1, "bus A (engine)", ["WIN", "ECM", "ETC", "MAP", "λ"]),
                            (3, "bus B (transmission)", ["WIN", "TCU", "APP", "GSL", "OSS"])):
        x = zx[z]
        ax.add_patch(Rectangle((x - 0.22, 2.75), 0.44, 0.35, fc=YELLOW, ec=INK, lw=0.6))
        ax.text(x + 0.3, 2.93, "C", fontsize=8, va="center", color=INK)
        ax.plot([x, x], [3.47, 3.1], color=INK, lw=0.8)
        ybus = 2.2
        ax.plot([x - 1.55, x + 1.55], [ybus, ybus], color="#8a4fd0", lw=2.2)
        ax.plot([x, x], [2.75, ybus], color="#8a4fd0", lw=1.2)
        for i, n in enumerate(nodes):
            nx = x - 1.40 + i * 0.70
            ax.plot([nx, nx], [ybus, ybus - 0.45], color="#8a4fd0", lw=1)
            node(ax, nx, ybus - 0.8, 0.68, 0.55, n, size=5.5)
        ax.text(x, 0.75, label, ha="center", va="center", fontsize=9, color=INK)
    ax.text(5, 1.7, "10BASE-T1S\nPLCA\n10 Mb/s", ha="center", va="center", fontsize=8, color=MUTED)
    ax.text(5, 0.2, "C = PLCA coordinator (switch port): BEACON held to the gPTP anchor", ha="center",
            va="center", fontsize=7.5, color=INK)
    save(fig, "dual_t1s_scenario_10pt")
    plt.close(fig)


def rounds():
    """Event anchors: each far anchor follows the planned arrival of a cross-bus frame by a gap G;
    a fine 25 us grid elsewhere (thin ticks), kept away from the event anchors."""
    fig, ax = plt.subplots(figsize=(W, 1.9))
    G, R, FE_A, FE_B, T1 = 35, 150, 70.8, 74.0, 520
    yA, yB = 1.55, 0.45
    evA = [0, round(0 + FE_A + G + R + FE_B + G)]          # Q sent, R delivered
    evB = [round(FE_A + G), round(FE_A + G + R)]           # Q delivered, R sent
    for name, y, ev in (("bus A", yA, evA), ("bus B", yB, evB)):
        ax.plot([0, T1], [y, y], color=GRID, lw=0.8)
        ax.text(-15, y, name, ha="right", va="center", fontsize=9)
        for t in range(-25, T1, 25):
            if t >= 0 and all(not (e - G - 30 < t <= e) and not (e < t < e + 100) for e in ev):
                ax.plot([t, t], [y - 0.12, y + 0.12], color=MUTED, lw=0.5)
        for e in ev:
            ax.plot([e, e], [y - 0.34, y + 0.34], color=INK, lw=1.2)
            ax.add_patch(Rectangle((e, y - 0.12), 4, 0.24, fc=INK, ec=INK))
    def frame(t, y, w, col, txt):
        ax.add_patch(Rectangle((t, y - 0.17), w, 0.34, fc=col, ec="white", lw=0.5))
        ax.text(t + w / 2, y, txt, ha="center", va="center", fontsize=7, color="white", fontweight="bold")
    frame(evA[0] + 8.4, yA, 62, BLUE, "Q")
    frame(evB[0] + 2, yB, 62, BLUE, "Q")
    frame(evB[1] + 11.6, yB, 62, ORANGE, "R")
    frame(evA[1] + 2, yA, 62, ORANGE, "R")
    ax.annotate("", xy=(evB[0], yB + 0.2), xytext=(evA[0] + 70.4, yA - 0.17),
                arrowprops=dict(arrowstyle="->", lw=0.9, color=BLUE))
    ax.annotate("", xy=(evA[1], yA - 0.2), xytext=(evB[1] + 73.6, yB + 0.17),
                arrowprops=dict(arrowstyle="->", lw=0.9, color=ORANGE))
    ax.annotate("", xy=(evB[0], yB - 0.42), xytext=(evA[0] + 70.8, yB - 0.42), arrowprops=dict(arrowstyle="<->", lw=0.7))
    ax.text((evB[0] + 70.8) / 2, yB - 0.48, "G", fontsize=8, ha="center", va="top")
    ax.text(T1, 2.35, "Q request, R response\n▮ event anchor (BEACON), | 25 µs grid", fontsize=7, ha="right", va="top", color=INK)
    ax.set_xlim(-110, T1); ax.set_ylim(-0.3, 2.35)
    ax.set_yticks([]); ax.set_xticks([0, 100, 200, 300, 400, 500])
    ax.set_xlabel("time (µs)", fontsize=9); ax.tick_params(labelsize=8)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    save(fig, "taplca_rounds")
    plt.close(fig)


if __name__ == "__main__":
    scenario()
    rounds()
