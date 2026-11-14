#!/usr/bin/env python3
"""Paper figures (TA-PLCA = plan 2, phi 40 us, anchored rounds only in the critical ms; at 2 and 1 ms every ms
is critical, so the plain plan-2 configs are used there)

Paper figures for TA-PLCA (10 pt sans-serif, PDF + PNG) from results/t1s/taplca/.

fig15_taplca_variation : delay variation (max - min) of the four cross-bus PCP 7 flows,
                         NOMINAL 10 seeds x 30 s, random / ideal-clock / gPTP schedule / TA-PLCA plan 2
fig16_taplca_rtt_ecdf  : ECDF of the PT01 and PT02 round-trip times (processing included), same configs
fig17_taplca_load      : load sweep (PT01/PT02 period 10/5/2/1 ms): max-min variation and window loss,
                         gPTP schedule vs TA-PLCA plan 2 (written only when the load-sweep results exist)

Output: simulations/zonal/t1s_results/figures/.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t1s_taplca_report import SIM, read_vec, read_sca, window_lost  # noqa: E402

RES = SIM / "results/t1s/taplca"
OUT = SIM / "zonal/t1s_results/figures"
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial"], "font.size": 10,
                     "axes.titlesize": 10, "axes.labelsize": 10, "legend.fontsize": 9, "xtick.labelsize": 9,
                     "ytick.labelsize": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#8a8a85", "axes.labelcolor": "#333", "xtick.color": "#555", "ytick.color": "#555"})
# validated categorical palette (slots 1-4), fixed order; hatches as secondary encoding
CFGS = [("TA_NOMINAL_RANDOM_30s", "unscheduled", "#2a78d6", ""),
        ("TA_NOMINAL_IDEAL_30s", "schedule, ideal clocks", "#eb6834", "//"),
        ("TA_NOMINAL_GPTP_30s", "schedule, gPTP", "#1baf7a", ".."),
        ("TA_NOMINAL_TAPLCA250_P2_PHI40_FINE_30s", "TA-PLCA (gPTP)", "#eda100", "xx")]
FLOWS = [("PT01", "PT01 RTT"), ("PT02", "PT02 RTT"), ("PT03", "PT03 one-way"), ("PT04", "PT04 one-way")]


def load(cfg):
    lat = {}
    for sca in sorted((RES / cfg).glob("*.sca")):
        for k, v in read_vec(sca.with_suffix(".vec")).items():
            lat.setdefault(k, []).extend(v)
    return lat


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    print("written", OUT / f"{name}.pdf")


def main():
    data = {c: load(c) for c, *_ in CFGS}
    # fig15: variation per flow, log scale
    fig, ax = plt.subplots(figsize=(7.0, 2.8))
    w = 0.2
    for i, (cfg, label, col, hatch) in enumerate(CFGS):
        xs, ys = [], []
        for j, (f, _) in enumerate(FLOWS):
            v = data[cfg].get(f, [])
            xs.append(j + (i - 1.5) * w)
            ys.append(max(v) - min(v) if v else 0)
        bars = ax.bar(xs, ys, w * 0.9, color=col, hatch=hatch, edgecolor="white", linewidth=0.5, label=label)
        for x, y in zip(xs, ys):
            ax.text(x, y * 1.15, f"{y:.2f}" if y < 1 else f"{y:.0f}", ha="center", va="bottom", fontsize=7, color="#333")
    ax.set_yscale("log")
    ax.set_ylim(0.03, 3000)
    ax.set_xticks(range(len(FLOWS)), [l for _, l in FLOWS])
    ax.set_ylabel("delay variation, max − min (µs)")
    ax.grid(axis="y", color="#e4e4e0", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.18), frameon=False)
    save(fig, "fig15_taplca_variation")
    plt.close(fig)

    # fig16: RTT ECDF
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    for ax, (f, title) in zip(axs, FLOWS[:2]):
        for cfg, label, col, _ in CFGS:
            v = sorted(data[cfg].get(f, []))
            if not v:
                continue
            n = len(v)
            ax.step(v, [(k + 1) / n for k in range(n)], where="post", color=col, linewidth=1.8, label=label)
        ax.axvline(1000, color="#8a8a85", linewidth=0.8, linestyle="--")
        ax.text(995, 0.5, "1 ms", ha="right", va="center", rotation=90, fontsize=8, color="#555")
        ax.set_title(title + " (processing included)")
        ax.set_xlabel("round-trip time (µs)")
        ax.set_xlim(250, 1050)
        ax.grid(color="#e4e4e0", linewidth=0.6)
    axs[0].set_ylabel("ECDF")
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.08), frameon=False)
    save(fig, "fig16_taplca_rtt_ecdf")
    plt.close(fig)

    # fig17: load sweep
    loads = [(10, "TA_NOMINAL_GPTP_30s", "TA_NOMINAL_TAPLCA250_P2_PHI40_FINE_30s"),
             (5, "TA_LOAD5_GPTP_30s", "TA_LOAD5_TAPLCA250_P2_PHI40_FINE_30s"),
             (2, "TA_LOAD2_GPTP_30s", "TA_LOAD2_TAPLCA250_P2_PHI40_30s"),
             (1, "TA_STRESS_GPTP_30s", "TA_STRESS_TAPLCA250_P2_PHI40_30s")]
    if not all((RES / c).exists() and list((RES / c).glob("*.sca")) for _, a, b in loads for c in (a, b)):
        print("load sweep incomplete: fig17 skipped")
        return
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.6))
    for cfgidx, (label, col, mk) in enumerate((("schedule, gPTP", "#1baf7a", "o"), ("TA-PLCA (gPTP)", "#eda100", "s"))):
        xs, pdv, loss = [], [], []
        for per, a, b in loads:
            cfg = (a, b)[cfgidx]
            lat = load(cfg)
            v = lat.get("PT01", []) + []
            xs.append(per)
            pdv.append(max(max(lat[f]) - min(lat[f]) for f in ("PT01", "PT02", "PT03", "PT04")))
            lost = sent = 0
            for sca in (RES / cfg).glob("*.sca"):
                _, _, text = read_sca(sca)
                lost += window_lost(text, RES / cfg) or 0
            runs = len(list((RES / cfg).glob("*.sca")))
            loss.append(100 * lost / (runs * 30 * 10000))   # two window flows x 5000 frames/s x 30 s
        axs[0].plot(xs, pdv, marker=mk, color=col, linewidth=2, markersize=6, label=label)
        axs[1].plot(xs, loss, marker=mk, color=col, linewidth=2, markersize=6, label=label)
    for ax in axs:
        ax.set_xscale("log")
        ax.set_xticks([10, 5, 2, 1], ["10", "5", "2", "1"])
        ax.invert_xaxis()
        ax.set_xlabel("PT01/PT02 period (ms) → more load")
        ax.grid(color="#e4e4e0", linewidth=0.6)
    axs[0].set_yscale("log")
    axs[0].set_ylabel("worst variation of the 4\ncross-bus flows (µs)")
    axs[1].set_ylabel("window (TC3) frames lost (%)")
    axs[0].legend(frameon=False, fontsize=8)
    fig.subplots_adjust(wspace=0.4)
    save(fig, "fig17_taplca_load")
    plt.close(fig)


if __name__ == "__main__":
    main()
