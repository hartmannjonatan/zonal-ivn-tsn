"""Pure helpers for the preregistered individual-step C3 calibration search."""
import hashlib
import json


def profile_signature(profile):
    """Stable SHA-256 identity for a full (egress, TC) -> bps reservation vector."""
    payload = {f"{egress}/TC{tc}": int(rate)
               for (egress, tc), rate in sorted(profile.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ordered_candidates(failing_flows, flow_map, route, nominal_keys, queue_waits, blocked=()):
    """Rank one-egress targets by the registered wait/route ordering, without target bans."""
    candidates = []
    blocked = set(blocked)
    for flow_id in failing_flows:
        flow = flow_map[flow_id]
        tc = int(flow["traffic_class"])
        if tc not in (4, 6):
            continue
        route_egresses = []
        for destination in flow["destinations"].split(";"):
            for egress in route(flow["source"], destination):
                key = (egress, tc)
                if key in nominal_keys and key not in blocked and key not in route_egresses:
                    route_egresses.append(key)
        for rank, key in enumerate(route_egresses):
            max_s, mean_s = queue_waits.get(key, (0.0, 0.0))
            candidates.append((-float(max_s or 0), -float(mean_s or 0), rank,
                               key[0], key[1], flow_id))
    return sorted(candidates)


def propose_increment(chosen, candidates, capacities, seen_signatures,
                      increment_fraction=0.10, cap_fraction=0.75):
    """Return first novel admissible full-step proposal and a trace of rejections.

    The egress/class may appear again: every proposal changes the complete vector
    and is allowed if it is novel and remains under the aggregate port cap.
    """
    seen = set(seen_signatures)
    rejections = []
    for rank_tuple in candidates:
        _, _, route_rank, egress, tc, flow_id = rank_tuple
        trial = dict(chosen)
        step_bps = round(increment_fraction * capacities[egress])
        trial[(egress, tc)] = int(trial[(egress, tc)]) + step_bps
        signature = profile_signature(trial)
        if signature in seen:
            rejections.append({"reason": "duplicate_profile", "target": f"{egress}/TC{tc}",
                               "flow_id": flow_id, "route_rank": route_rank,
                               "step_bps": step_bps, "profile_signature": signature})
            continue
        total = sum(value for (port, _), value in trial.items() if port == egress)
        cap_bps = cap_fraction * capacities[egress]
        if total > cap_bps:
            rejections.append({"reason": "75pct_cap", "target": f"{egress}/TC{tc}",
                               "flow_id": flow_id, "route_rank": route_rank,
                               "step_bps": step_bps, "proposed_port_total_bps": total,
                               "cap_bps": cap_bps, "profile_signature": signature})
            continue
        return {"profile": trial, "target": (egress, tc), "flow_id": flow_id,
                "route_rank": route_rank, "step_bps": step_bps,
                "profile_signature": signature, "rejections": rejections}
    return {"profile": None, "target": None, "rejections": rejections,
            "stop_reason": "no_new_admissible_profile"}


def reduction_target(chosen, nominal, queue_waits, rejected_targets=()):
    """Deterministic one-egress 2%-line-rate reduction target, bounded by nominal."""
    rejected = set(rejected_targets)
    candidates = []
    for key, value in chosen.items():
        if value <= nominal[key] or key in rejected:
            continue
        excess = value - nominal[key]
        max_s, mean_s = queue_waits.get(key, (0.0, 0.0))
        candidates.append((-excess, -float(max_s or 0), -float(mean_s or 0), key))
    candidates.sort()
    return candidates[0][3] if candidates else None
