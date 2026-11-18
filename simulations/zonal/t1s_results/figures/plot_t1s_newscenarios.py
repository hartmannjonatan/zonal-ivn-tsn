"""Figures for the dual-bus and powertrain T1S scenarios (reads ../dualbus.csv, ../powertrain.csv)."""
import os, pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.dirname(HERE)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]; DL = "#e34948"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": "#e4e3df", "grid.linewidth": .6, "axes.axisbelow": True,
                     "savefig.dpi": 200, "savefig.bbox": "tight"})
def save(fig, name):
    for ext in ("png", "pdf"): fig.savefig(os.path.join(HERE, f"{name}.{ext}"))
    plt.close(fig)

# Powertrain: one row per flow, p99 bar + max marker, nominal vs stress
if os.path.exists(f"{R}/powertrain.csv"):
    d = pd.read_csv(f"{R}/powertrain.csv"); d = d[d.kind != "catalog"]
    flows = list(dict.fromkeys(d.flow)); y = np.arange(len(flows))[::-1]; h = .38
    fig, ax = plt.subplots(figsize=(9, 5.2))
    for k, prof in enumerate(["NOMINAL", "STRESS"]):
        s = d[d.profile == prof].set_index("flow").loc[flows]
        yy = y + (.5 - k) * h
        ax.barh(yy, s.p99_us, h * .9, color=C[k], label=f"{prof.title()} — p99", zorder=2)
        ax.scatter(s.max_us, yy, marker="|", s=120, color="#0b0b0b", zorder=4, label="max" if k == 0 else None)
    s = d[d.profile == "NOMINAL"].set_index("flow").loc[flows]
    lab = [f"{f}  {desc.split(' (')[0]}" + ("  [RTT]" if kd == "reqresp" else "") + ("  ⇄" if p == "cross-bus" else "")
           for f, desc, kd, p in zip(flows, s.description, s.kind, s.path)]
    ax.set_yticks(y, lab, fontsize=8)
    ax.axvline(1000, color=DL, ls="--", lw=1.4); ax.text(990, y[-1] - .1, "1 ms — IEEE 802.1DG ref.\n(safety-relevant control)", color=DL, fontsize=8, ha="right", va="top")
    ax.set_xlim(0, 1050)
    ax.set_xlabel("Latency (µs) — one-way, or round-trip for [RTT]"); ax.legend(frameon=False, fontsize=8, loc="center right", bbox_to_anchor=(0.86, 0.5))
    ax.set_title("Powertrain on two 10BASE-T1S buses (PCP 7) — ⇄ = crosses Z1↔Z3; no losses, no period misses", loc="left", fontsize=10)
    save(fig, "fig6_powertrain_latency")

# Dual bus: max/p99 of cross-bus readings vs nodes per bus
if os.path.exists(f"{R}/dualbus.csv"):
    d = pd.read_csv(f"{R}/dualbus.csv")
    fig, axs = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for a, (per, t) in zip(axs, [(1000, "Readings every 1 ms"), (200, "Readings every 200 µs")]):
        s = d[d.period_us == per].sort_values("segment_nodes")
        if s.empty: continue
        x = s.segment_nodes
        for k, (key, lab) in enumerate([("r13", "Z1 → Z3"), ("r31", "Z3 → Z1")]):
            a.plot(x, s[f"{key}_max_us"], "-o", color=C[k], lw=2, label=f"{lab} max")
            a.plot(x, s[f"{key}_p99_us"], "--o", color=C[k], lw=1.4, ms=4, alpha=.8, label=f"{lab} p99")
        a.axhline(1000, color=DL, ls="--", lw=1.4); a.text(x.min() + .6, 1150, "1 ms — 802.1DG ref." + (" = period" if per == 1000 else ""), color=DL, fontsize=8, ha="left")
        if per != 1000:
            a.axhline(per, color="#52514e", ls=":", lw=1.2); a.text(x.min() + .6, per * 1.12, f"period {per} µs", color="#52514e", fontsize=8, ha="left")
        for xi, wl in zip(x, s.F15_lost + s.F17_lost):
            if wl: a.annotate(f"window lost\n{int(wl)}", (xi, s[s.segment_nodes == xi].r13_max_us.iloc[0]), textcoords="offset points", xytext=(0, -10), ha="center", va="top", fontsize=7, color="#52514e")
        a.set_title(t, loc="left", fontsize=10); a.set_yscale("log")
        a.set_xlabel("Nodes per T1S segment"); a.set_xticks(sorted(x.unique()))
    axs[0].set_ylabel("Cross-bus reading latency (µs)"); axs[0].set_ylim(50, 5e6); axs[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Sensor on one T1S bus read by the ECU on the other (PCP 7), 3 seeds × 2 s", x=.06, y=1.03, ha="left")
    save(fig, "fig7_dualbus_cross_reading")

# Jitter between the buses
if os.path.exists(f"{R}/jitter_powertrain.csv") and os.path.exists(f"{R}/jitter_dualbus.csv"):
    j = pd.read_csv(f"{R}/jitter_powertrain.csv"); j = j[j.path == "cross-bus"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.3, 1]})
    a = axs[0]; flows = list(dict.fromkeys(j.flow)); x = np.arange(len(flows)); w = .2
    for k, prof in enumerate(["NOMINAL", "STRESS"]):
        s_ = j[j.profile == prof].set_index("flow").loc[flows]
        a.bar(x + (2 * k - 1.5) * w, s_.pdv_us, w * .92, color=C[k], label=f"{prof.title()} — delay variation (max−min)", zorder=2)
        a.bar(x + (2 * k - .5) * w, s_.interarrival_jitter_us, w * .92, color=C[k], alpha=.45, hatch="//", edgecolor="white", label=f"{prof.title()} — inter-arrival jitter", zorder=2)
    s_ = j[j.profile == "NOMINAL"].set_index("flow").loc[flows]
    a.set_xticks(x, [f"{f}\n{d.split(' ')[0]} {'RTT' if m == 'round-trip' else ''}" for f, d, m in zip(flows, s_.description, s_.metric)], fontsize=8)
    a.set_ylabel("Jitter (µs)"); a.legend(frameon=False, fontsize=7, loc="upper left"); a.set_ylim(0, 650)
    a.set_title("Powertrain cross-bus flows (Z1 ↔ Z3)", loc="left", fontsize=10)
    a = axs[1]; dbj = pd.read_csv(f"{R}/jitter_dualbus.csv"); dbj = dbj[dbj.period_us == 1000]
    for k, dr in enumerate(["Z1->Z3", "Z3->Z1"]):
        s_ = dbj[dbj.direction == dr].sort_values("segment_nodes")
        a.plot(s_.segment_nodes, s_.pdv_us, "-o", color=C[k], lw=2, label=f"{dr.replace('->', ' → ')} delay variation")
        a.plot(s_.segment_nodes, s_.interarrival_jitter_us, "--o", color=C[k], lw=1.4, ms=4, label=f"{dr.replace('->', ' → ')} inter-arrival")
    a.set_xticks([4, 6, 8]); a.set_xlabel("Nodes per T1S segment"); a.set_ylim(0, 650)
    a.set_title("Generic cross-bus reading, every 1 ms", loc="left", fontsize=10); a.legend(frameon=False, fontsize=7, loc="upper left")
    fig.suptitle("Jitter between the two 10BASE-T1S buses (PCP 7, 3 seeds × 2 s)", x=.06, y=1.02, ha="left")
    save(fig, "fig8_cross_bus_jitter")
print("ok")

# Coordinator relief: standard vs burst vs multiTo
if os.path.exists(f"{R}/relief.csv"):
    d = pd.read_csv(f"{R}/relief.csv")
    cases = [("generic 1000 µs, 8 nodes", "Generic, 1 ms, 8 nodes"), ("powertrain nominal", "Powertrain nominal"), ("powertrain stress", "Powertrain stress")]
    vars_ = ["standard", "burst max_bc=3", "multiTo coordinator"]
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
    for a, (c, t) in zip(axs, cases):
        s_ = d[d.case == c]
        flows = list(dict.fromkeys(s_.flow)); x = np.arange(len(flows)); w = .26
        for k, v in enumerate(vars_):
            q = s_[s_.variant == v].set_index("flow").reindex(flows)
            if q.max_us.isna().all():
                continue
            a.bar(x + (k - 1) * w, q.max_us, w * .9, color=C[k], label=v, zorder=2)
            a.scatter(x + (k - 1) * w, q.pdv_us, marker="_", s=150, color="#0b0b0b", zorder=4, label="delay variation" if k == 0 else None)
        wl = s_.groupby("variant").window_lost.max().reindex(vars_)
        a.set_title(t + ("\nwindow lost: " + " / ".join("—" if pd.isna(z) else str(int(z)) for z in wl) if c.startswith("generic") else ""), loc="left", fontsize=10)
        a.set_xticks(x, [f.replace("->", "→").replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
        a.axhline(1000, color=DL, ls="--", lw=1.2)
    axs[0].set_ylabel("Max latency (µs); — = delay variation"); axs[0].text(-.4, 1020, "1 ms 802.1DG ref.", color=DL, fontsize=8)
    axs[1].legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle("Coordinator relief on the T1S buses — cross-bus flows (multiTo crashed on the generic case)", x=.06, y=1.04, ha="left")
    save(fig, "fig9_coordinator_relief")

# Step 2: scheduled traffic — delay variation (jitter) standard vs synchronized vs synchronized + TAS 400 µs
if os.path.exists(f"{R}/relief.csv"):
    d = pd.read_csv(f"{R}/relief.csv")
    cases = [("generic 1000 µs, 6 nodes", "Generic, 1 ms, 6 nodes"), ("generic 1000 µs, 8 nodes", "Generic, 1 ms, 8 nodes"),
             ("powertrain nominal", "Powertrain nominal"), ("powertrain stress", "Powertrain stress")]
    vars_ = [("standard", "standard (random phase)"), ("synchronized", "synchronized releases"),
             ("synchronized + TAS 400 µs", "synchronized + TAS gate (400 µs)")]
    fig, axs = plt.subplots(1, 4, figsize=(15, 4.4), sharey=True, gridspec_kw={"width_ratios": [1, 1, 1.6, 1.6]})
    for a, (c, t) in zip(axs, cases):
        s_ = d[d.case == c]
        flows = list(dict.fromkeys(s_.flow)); x = np.arange(len(flows)); w = .26
        for k, (v, lab) in enumerate(vars_):
            q = s_[s_.variant == v].set_index("flow").reindex(flows)
            a.bar(x + (k - 1) * w, q.pdv_us, w * .9, color=C[k], label=lab, zorder=2)
            a.scatter(x + (k - 1) * w, q.max_us, marker="_", s=150, color="#0b0b0b", zorder=4, label="max latency" if k == 0 else None)
        wl = s_.groupby("variant").window_lost.max().reindex([v for v, _ in vars_])
        a.set_title(f"{t}\nwindow lost: " + " / ".join(str(int(z)) for z in wl), loc="left", fontsize=9)
        a.set_xticks(x, [f.replace("->", "→").replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
    axs[0].set_ylabel("Delay variation, max − min (µs)\n— = max latency (µs)")
    h_, l_ = axs[2].get_legend_handles_labels(); fig.legend(h_, l_, frameon=False, fontsize=9, ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.1))
    fig.suptitle("Step 2 — scheduled traffic on the two T1S buses: cross-bus jitter (ideal clocks stand in for gPTP; 3 seeds × 2 s)", x=.06, y=1.05, ha="left")
    save(fig, "fig10_scheduled_jitter")

# Final 30 s × 10 seeds: baseline vs synchronized + TAS 400 µs (cross-bus flows)
if os.path.exists(f"{R}/dualbus_final_30s.csv"):
    d = pd.read_csv(f"{R}/dualbus_final_30s.csv")
    d = d[(d.get("path").isna()) | (d.get("path") == "cross-bus")] if "path" in d else d
    cases = [("generic 1000 µs, 6 nodes", "Generic, 1 ms, 6 nodes"), ("powertrain nominal", "Powertrain nominal"), ("powertrain stress", "Powertrain stress")]
    vars_ = [("standard", "random phases (baseline)"), ("synchronized + TAS 400 µs", "synchronized + TAS gate (400 µs)")]
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.4), sharey=True, gridspec_kw={"width_ratios": [1, 1.6, 1.6]})
    for a, (c, t) in zip(axs, cases):
        s_ = d[d.case == c]; flows = list(dict.fromkeys(s_.flow)); x = np.arange(len(flows)); w = .36
        for k, (v, lab) in enumerate(vars_):
            q = s_[s_.variant == v].set_index("flow").reindex(flows)
            a.bar(x + (k - .5) * w, q.pdv_us, w * .9, color=C[[0, 2][k]], label=f"{lab} — delay variation", zorder=2)
            a.scatter(x + (k - .5) * w, q.max_us, marker="_", s=180, color="#0b0b0b", zorder=4, label="max latency" if k == 0 else None)
            for xi, (m, o) in enumerate(zip(q.max_us, q.over_ref)):
                if o: a.annotate(f"{int(o)} > 1 ms", (xi + (k - .5) * w, m), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7, color=DL)
        a.axhline(1000, color=DL, ls="--", lw=1.2)
        a.set_title(t, loc="left", fontsize=10)
        a.set_xticks(x, [f.split(" (")[0].replace("->", "→").replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
    axs[0].set_ylabel("Delay variation, max − min (µs)\n— = max latency (µs)"); axs[0].text(-.45, 1020, "1 ms 802.1DG ref.", color=DL, fontsize=8)
    h_, l_ = axs[1].get_legend_handles_labels(); fig.legend(h_, l_, frameon=False, fontsize=9, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.08))
    fig.suptitle("Cross-bus flows on two 10BASE-T1S buses — final statistics, 10 seeds × 30 s (no losses in any case)", x=.06, y=1.03, ha="left")
    save(fig, "fig11_final_30s")

# Real clocks: ideal vs gPTP vs free-running (30 s × 10 seeds), cross-bus flows
if os.path.exists(f"{R}/dualbus_final_30s.csv"):
    d = pd.read_csv(f"{R}/dualbus_final_30s.csv")
    if "sync + TAS, gPTP clocks" in set(d.variant):
        d = d[(d["path"].isna()) | (d["path"] == "cross-bus")]
        cases = [("generic 1000 µs, 6 nodes", "Generic, 1 ms, 6 nodes"), ("powertrain nominal", "Powertrain nominal"), ("powertrain stress", "Powertrain stress")]
        vars_ = [("standard", "random phases"), ("synchronized + TAS 400 µs", "sync + TAS, ideal clocks"),
                 ("sync + TAS, gPTP clocks", "sync + TAS, gPTP"), ("sync + TAS, free-running clocks", "sync + TAS, no gPTP")]
        fig, axs = plt.subplots(1, 3, figsize=(14, 4.4), sharey=True, gridspec_kw={"width_ratios": [1, 1.6, 1.6]})
        for a, (c, t) in zip(axs, cases):
            s_ = d[d.case == c]; flows = list(dict.fromkeys(s_.flow)); x = np.arange(len(flows)); w = .2
            for k, (v, lab) in enumerate(vars_):
                q = s_[s_.variant == v].set_index("flow").reindex(flows)
                a.bar(x + (k - 1.5) * w, q.std_us, w * .9, color=C[k], label=lab, zorder=2)
            wl = s_.groupby("variant").window_lost.max().reindex([v for v, _ in vars_])
            a.set_title(t + ("" if wl.fillna(0).sum() == 0 else "\nwindow lost: " + " / ".join(str(int(z)) for z in wl.fillna(0))), loc="left", fontsize=9)
            a.set_xticks(x, [f.split(" (")[0].replace("->", "→").replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
        axs[0].set_ylabel("Latency standard deviation (µs)")
        h_, l_ = axs[1].get_legend_handles_labels(); fig.legend(h_, l_, frameon=False, fontsize=9, ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.08))
        fig.suptitle("Cross-bus jitter with real clocks (drift U(−50, 50) ppm), 10 seeds × 30 s", x=.06, y=1.03, ha="left")
        save(fig, "fig12_real_clocks")

# gPTP sensitivity + EV 30 s
if os.path.exists(f"{R}/dualbus_final_30s.csv"):
    d = pd.read_csv(f"{R}/dualbus_final_30s.csv")
    if "sync + TAS, gPTP, Sync 31.25 ms" in set(d.variant):
        d = d[d["path"] == "cross-bus"]
        fig, axs = plt.subplots(1, 3, figsize=(15, 4.4), gridspec_kw={"width_ratios": [1.3, 1.3, 1.5]})
        sv = [("sync + TAS, gPTP, drift ±10 ppm", "drift ±10 ppm"), ("sync + TAS, gPTP clocks", "drift ±50 ppm (Sync 125 ms)"),
              ("sync + TAS, gPTP, drift ±100 ppm", "drift ±100 ppm"), ("sync + TAS, gPTP, Sync 31.25 ms", "Sync 31.25 ms")]
        for a, case in zip(axs[:2], ["powertrain nominal", "powertrain stress"]):
            s_ = d[d.case == case]; flows = list(dict.fromkeys(s_.flow)); x = np.arange(len(flows)); w = .2
            for k, (v, lab) in enumerate(sv):
                q = s_[s_.variant == v].set_index("flow").reindex(flows)
                a.bar(x + (k - 1.5) * w, q.std_us, w * .9, color=C[k], label=lab, zorder=2)
            a.set_xticks(x, [f.replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
            a.set_title(f"gPTP sensitivity — {case.replace('powertrain', 'Powertrain')}", loc="left", fontsize=9); a.set_ylim(0, 80)
        axs[0].set_ylabel("Latency std (µs)"); axs[0].legend(frameon=False, fontsize=7, loc="upper right")
        a = axs[2]; s_ = d[d.case == "ev nominal"]; flows = list(dict.fromkeys(s_.flow)); x = np.arange(len(flows)); w = .36
        for k, (v, lab) in enumerate([("standard", "random phases"), ("sync + TAS, gPTP clocks", "sync + TAS + gPTP")]):
            q = s_[s_.variant == v].set_index("flow").reindex(flows)
            a.bar(x + (k - .5) * w, q.pdv_us, w * .9, color=C[[0, 2][k]], label=f"{lab} — delay variation", zorder=2)
            a.scatter(x + (k - .5) * w, q.max_us, marker="_", s=150, color="#0b0b0b", zorder=4, label="max latency" if k == 0 else None)
        a.axhline(1000, color=DL, ls="--", lw=1.2); a.set_ylim(0, 1450)
        a.set_xticks(x, [f.replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
        a.set_title("EV nominal, cross-bus (EV01 torque, EV11 redundant copy)", loc="left", fontsize=9); a.set_ylabel("µs")
        a.legend(frameon=False, fontsize=7, loc="upper left")
        fig.suptitle("gPTP sensitivity and electric-vehicle scenario — 10 seeds × 30 s, no losses", x=.06, y=1.03, ha="left")
        fig.tight_layout()
        save(fig, "fig13_gptp_sensitivity_ev")

# Same switch (both buses on Z1) vs two switches (Z1 + Z3), cross-bus powertrain flows, 30 s × 10 seeds
if os.path.exists(f"{R}/dualbus_final_30s.csv"):
    d = pd.read_csv(f"{R}/dualbus_final_30s.csv")
    if "powertrain same switch nominal" in set(d.case):
        d = d[d["path"] == "cross-bus"]
        fig, axs = plt.subplots(2, 2, figsize=(11, 6.6), sharey=True, sharex=True)
        topo = [("powertrain", "two switches (bus A on Z1, bus B on Z3)", "#9b9a96"), ("powertrain same switch", "same switch (both buses on Z1)", C[0])]
        for i, (v, vlab) in enumerate([("standard", "Random phases"), ("sync + TAS, gPTP clocks", "Sync + TAS 400 µs + gPTP")]):
            for j, prof in enumerate(["nominal", "stress"]):
                a = axs[i, j]; w = .38
                flows = list(dict.fromkeys(d[(d.case == f"powertrain {prof}") & (d.variant == v)].flow)); x = np.arange(len(flows))
                for k, (pre, lab, col) in enumerate(topo):
                    q = d[(d.case == f"{pre} {prof}") & (d.variant == v)].set_index("flow").reindex(flows)
                    xs = x + (k - .5) * w
                    a.bar(xs, q.max_us, w * .92, color=col, label=f"{lab} — max", zorder=2)
                    a.scatter(xs, q.mean_us, marker="_", s=160, color="#0b0b0b", zorder=4, label="mean" if k == 0 else None)
                    for xi, m in zip(xs, q.max_us): a.annotate(f"{m:.0f}", (xi, m), xytext=(0, 2), textcoords="offset points", ha="center", fontsize=7)
                a.axhline(1000, color=DL, ls="--", lw=1.2)
                a.set_title(f"{vlab} — {prof}", loc="left", fontsize=10)
                a.set_xticks(x, [f.replace(" (cross-bus)", "").replace(" one-way", "").replace(" RTT", "\nRTT") for f in flows], fontsize=8)
            axs[i, 0].set_ylabel("Latency (µs)")
        axs[0, 0].text(-.45, 1020, "1 ms 802.1DG ref.", color=DL, fontsize=8); axs[0, 0].set_ylim(0, 1300)
        h_, l_ = axs[0, 0].get_legend_handles_labels(); fig.legend(h_, l_, frameon=False, fontsize=9, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.04))
        fig.suptitle("Cross-bus powertrain flows: both T1S buses on one zonal switch vs on two, 10 seeds × 30 s (no losses)", x=.06, y=1.0, ha="left")
        fig.tight_layout(rect=(0, .04, 1, .97))
        save(fig, "fig14_same_switch")
