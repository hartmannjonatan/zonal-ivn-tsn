#!/usr/bin/env python3
"""Live, read-only status display for the P1 v2 official campaign."""
from __future__ import annotations

import argparse
import json
import gzip
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
LEDGER = RESULTS / "runs.jsonl"
CHECKPOINT = RESULTS / "checkpoint.json"
PROGRESS = RESULTS / "progress.json"
CALIBRATION = RESULTS / "calibration" / "C3_calibration.json"
FINAL = RESULTS / "campaign_results.json"
SEEDS_PER_CELL = 30
PERCENT_RE = re.compile(r"\b(\d{1,3})% completed\s+\(\d{1,3}% total\)")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_ledger():
    rows = []
    try:
        with LEDGER.open(encoding="utf-8") as f:
            for line in f:
                try:
                    if line.strip():
                        rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # A currently appended final line can be incomplete.
                    continue
    except OSError:
        pass
    return rows


def log_progress(path: Path):
    """Return the most recent simulator percentage and log tail status."""
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                content = f.read()
            tail = content[-256_000:]
        else:
            with path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 256_000))
                tail = f.read().decode("utf-8", errors="replace")
        matches = PERCENT_RE.findall(tail)
        # The regex has one capture group; indexing [0] here returned only the
        # first digit, so progress above 9% displayed incorrectly (e.g. 14→1).
        percent = min(100, int(matches[-1])) if matches else None
        ended = any(s in tail for s in ("Calling finish() at end of Run", "Simulation time limit reached", "End."))
        return percent, ended, path.stat().st_mtime
    except OSError:
        return None, False, 0


def campaign_executor_alive(checkpoint):
    pid = checkpoint.get("executor_pid") if checkpoint else None
    if not pid:
        return False
    try:
        pid = int(pid)
        os.kill(pid, 0)
        executable = Path(f"/proc/{pid}/exe").resolve().name
        argv = [arg for arg in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if arg]
        # A stale PID can be recycled by an unrelated shell whose command text
        # happens to contain `run_campaign.py`. Require a Python executable and
        # a distinct argv token naming the actual runner script.
        return (executable.startswith("python") and any(
            Path(arg.decode(errors="replace")).name == "run_campaign.py" for arg in argv[1:]))
    except (OSError, ValueError):
        return False


def find_execution_logs(stage: str):
    """Find per-run logs below a stage directory (e.g. calibration or final)."""
    base = RESULTS / stage
    if not base.exists():
        return []
    found = []
    paths = list(base.rglob("Validate_*.log")) + list(base.rglob("Validate_*.log.gz"))
    for path in paths:
        percent, ended, mtime = log_progress(path)
        # Logs with a completed simulator but no ledger entry are still being
        # validated/compressed; include them as active work until ledgered.
        found.append((path, percent, ended, mtime))
    return found


def active_logs(rows, checkpoint):
    """Identify in-flight tasks by missing ledger execution ID and run logs."""
    owner_alive = campaign_executor_alive(checkpoint)
    completed = {r.get("execution_id") for r in rows}
    active = []
    for stage in ("calibration", "final"):
        for path, percent, ended, mtime in find_execution_logs(stage):
            # Layout: results/<stage>/<treatment>/<load>/<alignment>/<seed>/<execution_id>/...
            execution_id = path.parent.name
            if execution_id in completed:
                continue
            # Old interrupted attempts can also lack a normal end marker.
            # Use the run-directory timestamp so an active postprocessor remains
            # visible even if it has not touched the OMNeT log recently.
            try:
                dir_recent = path.parent.stat().st_mtime > time.time() - 5 * 60
            except OSError:
                dir_recent = False
            log_recent = mtime > time.time() - 5 * 60
            if owner_alive and not ended and log_recent:
                active.append({"stage": stage, "id": execution_id, "path": path,
                               "percent": percent, "mtime": mtime, "postprocessing": False})
            elif owner_alive and ended and (log_recent or dir_recent):
                active.append({"stage": stage, "id": execution_id, "path": path,
                               "percent": 100, "mtime": mtime, "postprocessing": True})
    # A checkpoint may name a run before its log is created.
    executor_alive = owner_alive
    active_id = (checkpoint.get("active_execution_id")
                 if checkpoint and checkpoint.get("active_process") and executor_alive else None)
    if active_id and active_id not in completed and not any(x["id"] == active_id for x in active):
        stage = checkpoint.get("stage", "calibration")
        active.append({"stage": stage, "id": active_id, "path": None,
                       "percent": None, "mtime": checkpoint.get("timestamp", 0),
                       "postprocessing": False})
    return active


def fmt_percent(value):
    return f"{value:3d}%" if value is not None else "  --"


def render_once():
    rows = read_ledger()
    checkpoint = read_json(CHECKPOINT, {}) or {}
    progress = read_json(PROGRESS, {}) or {}
    calibration = read_json(CALIBRATION, {}) or {}
    final = read_json(FINAL, {}) or {}
    executor_alive = campaign_executor_alive(checkpoint)
    active = active_logs(rows, checkpoint)
    now = time.strftime("%Y-%m-%d %H:%M:%S %Z")

    cal_rows = [r for r in rows if r.get("stage") == "calibration"]
    candidates = [r for r in cal_rows if str(r.get("execution_id", "")).startswith("candidate_")]
    reductions = [r for r in cal_rows if str(r.get("execution_id", "")).startswith("reduction_")]
    fixed = [r for r in cal_rows if "_fixed_seed" in str(r.get("execution_id", ""))]
    nominal_checks = [r for r in cal_rows if str(r.get("execution_id", "")).startswith("C2_nominal_seed")]

    hist_failed = [r.get("execution_id") for r in candidates
                   if r.get("viable") is False and int(str(r.get("execution_id")).split("_")[-1]) <= 3]
    corrected_failed = [r.get("execution_id") for r in candidates
                        if r.get("viable") is False and int(str(r.get("execution_id")).split("_")[-1]) >= 5]
    interrupted = list(progress.get("interrupted_attempts", []))
    interrupted += [r.get("execution_id") for r in candidates if r.get("viable") is None]
    active_cal = [x for x in active if x["stage"] == "calibration"]
    running_candidate = next((x for x in active_cal if x["id"].startswith("candidate_")), None)
    active_reduction = next((x for x in active_cal if x["id"].startswith("reduction_")), None)
    checkpoint_id = checkpoint.get("active_execution_id")
    if (running_candidate is None and checkpoint_id and checkpoint_id.startswith("candidate_")
            and checkpoint_id not in {r.get("execution_id") for r in rows}):
        running_candidate = next((x for x in active_cal if x["id"] == checkpoint_id), None)
        if running_candidate is None:
            running_candidate = {"id": checkpoint_id,
                                 "percent": progress.get(f"{checkpoint_id}_progress_percent_last_log"),
                                 "postprocessing": False}

    # Full campaign denominator by treatment. C3 only enters the denominator
    # if the calibrated/frozen profile was accepted; L3 is never simulated.
    accepted = calibration.get("status") == "frozen_and_accepted"
    if not CALIBRATION.exists():
        accepted = bool(progress.get("calibration_profile_accepted", False))
    final_rows = [r for r in rows if r.get("stage") == "final"]
    by_cell = defaultdict(list)
    for r in final_rows:
        by_cell[(r.get("campaign_treatment"), r.get("load_name"), r.get("aggregation_name"))].append(r)
    active_final = [x for x in active if x["stage"] == "final"]
    active_by_cell = defaultdict(list)
    for x in active_final:
        parts = x["path"].parts if x["path"] else ()
        # The canonical directory layout has treatment/load/Ax/seed/id.
        if len(parts) >= 5:
            try:
                base_index = parts.index("final")
                treatment, load, align = parts[base_index + 1:base_index + 4]
                active_by_cell[(treatment, load, align)].append(x)
            except (ValueError, IndexError):
                pass

    lines = []
    lines.append("CAMPANHA OFICIAL P1 v2 — acompanhamento ao vivo (somente leitura)")
    lines.append(f"Atualizado: {now}     Atualização automática: a cada intervalo configurado")
    checkpoint_pid = checkpoint.get("executor_pid")
    if checkpoint.get("active_process") and checkpoint_pid:
        executor_alive = campaign_executor_alive(checkpoint)
        if not executor_alive:
            lines.append(f"Executor indicado no checkpoint (PID {checkpoint_pid}) não está ativo; estado anterior pode ser de uma interrupção.")
    lines.append("=" * 94)
    lines.append("CALIBRAÇÃO C3 — L2/A1, seed 41")
    lines.append(f"  Candidatos históricos reprovados/incompatíveis: {', '.join(hist_failed) or 'nenhum registrado'}")
    lines.append(f"  Busca corrigida reprovada: {', '.join(corrected_failed) or 'nenhum registrado'}")
    lines.append(f"  Tentativas técnicas sem gate: {', '.join(interrupted) or 'nenhuma no ledger'}")
    viable_candidate_ids = [r.get("execution_id") for r in candidates if r.get("viable") is True]
    lines.append(f"  Candidatos que passaram a viabilidade na seed 41: {', '.join(viable_candidate_ids) or 'nenhum'}")
    if running_candidate:
        extra = " (simulação terminou; validação/ledger pendente)" if running_candidate.get("postprocessing") else ""
        lines.append(f"  Candidato em andamento: {running_candidate['id']} — {fmt_percent(running_candidate.get('percent'))}{extra}")
    elif active_reduction:
        lines.append("  Candidato em andamento: nenhum; executor está na etapa de reduções")
    else:
        lines.append("  Em andamento: nenhum candidato identificado")
    counted_candidate_ids = {str(r.get("execution_id")) for r in candidates}
    counted_candidate_ids.update(
        match.group(0) for item in interrupted
        if (match := re.search(r"candidate_\d+", str(item)))
    )
    # candidate_04 consumed an allocated proposal slot but has no ledger gate;
    # its preserved partial-result directory is the durable evidence for it.
    if (RESULTS / "calibration" / "C3" / "L2" / "A1" / "seed41" / "candidate_04").exists():
        counted_candidate_ids.add("candidate_04")
    if running_candidate and running_candidate.get("id", "").startswith("candidate_"):
        counted_candidate_ids.add(running_candidate["id"])
    budget_used = len(counted_candidate_ids)
    lines.append(f"  Orçamento de busca: {budget_used}/24 posições contabilizadas; máximo restante: {max(0, 24-budget_used)}")
    if calibration:
        lines.append(f"  Resultado da calibração: {calibration.get('status', 'não informado')}; perfil final: {calibration.get('final_profile_id') or 'nenhum congelado'}")
    else:
        lines.append("  Reduções: " + (", ".join(f"{r.get('execution_id')}={'PASS' if r.get('viable') else 'FAIL'}" for r in reductions) or "aguardando candidato viável"))
        if active_reduction:
            lines.append(f"  Redução ativa: {active_reduction['id']} — {fmt_percent(active_reduction.get('percent'))}")
        lines.append("  Verificação sem retuning: " + (", ".join(f"{r.get('execution_id')}={'PASS' if r.get('viable') else 'FAIL'}" for r in fixed) or "aguardando reduções"))
        if nominal_checks:
            lines.append("  Controles C2 nominais adicionais: " + ", ".join(r.get("execution_id", "?") for r in nominal_checks))

    lines.append("")
    lines.append("CAMPANHA FINAL — percentual por célula (30 seeds por célula)")
    lines.append(f"  Condição C3: {'perfil aceito' if accepted else 'aguarda calibração/verificação'}")
    lines.append("  Cada valor é (seeds concluídas + fração das execuções ativas) / 30.")
    treatments = ("C0", "C1", "C2", "C3")
    loads = ("L0", "L1", "L2", "L3")
    for treatment in treatments:
        lines.append(f"  {treatment}")
        lines.append("       A0                         A1")
        for load in loads:
            cells = []
            for align in ("A0", "A1"):
                key = (treatment, load, align)
                if treatment == "C3" and load == "L3":
                    cells.append("inadmissível P1")
                    continue
                if treatment == "C3" and not accepted:
                    cells.append("aguarda perfil")
                    continue
                done = len({r.get("seed") for r in by_cell[key]})
                runs = active_by_cell[key]
                partial = sum((x.get("percent") or 0) / 100 for x in runs)
                pct = min(100.0, (done + partial) / SEEDS_PER_CELL * 100)
                state = f"{pct:5.1f}% ({done:02d}/30"
                if runs:
                    state += f" + {len(runs)} ativo"
                state += ")"
                cells.append(state)
            lines.append(f"    {load}:  {cells[0]:<23}  {cells[1]}")
    final_complete = final.get("complete")
    completed_final = len(final_rows)
    if final:
        lines.append(f"  Total registrado: {completed_final}/{final.get('expected_runs', '?')} execuções; complete={final_complete}")
    else:
        expected = 720 + (180 if accepted else 0)
        lines.append(f"  Total registrado: {completed_final}/{expected if accepted else '720 (+ C3 se aceito)'}; resumo final ainda não gerado")

    lines.append("")
    checkpoint_execution = checkpoint.get("active_execution_id") if executor_alive else None
    last_execution = checkpoint.get("latest_execution_id", checkpoint.get("active_execution_id", "—"))
    executor_state = (f"ativo: {checkpoint.get('stage', '—')} / {checkpoint_execution or 'inicializando'}"
                      if executor_alive else f"inativo; último checkpoint: {last_execution}")
    lines.append(f"Estado do executor: {executor_state}")
    lines.append(f"Espaço livre: {checkpoint.get('free_gb', progress.get('free_disk_gib', '—'))} GB (aprox.)")
    lines.append("Ctrl+C encerra somente este painel; não interrompe a campanha.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=2.0, help="segundos entre atualizações (padrão: 2)")
    parser.add_argument("--once", action="store_true", help="exibe uma vez e sai")
    parser.add_argument("--no-clear", action="store_true", help="não apaga/reutiliza a tela")
    args = parser.parse_args()
    try:
        while True:
            view = render_once()
            if not args.no_clear and sys.stdout.isatty():
                sys.stdout.write("\033[2J\033[H")
            elif not args.once and not args.no_clear:
                # A pipe/log should remain readable; terminals get a single repaint.
                args.once = True
            sys.stdout.write(view + "\n")
            sys.stdout.flush()
            if args.once:
                break
            time.sleep(max(0.5, args.interval))
    except KeyboardInterrupt:
        if sys.stdout.isatty():
            sys.stdout.write("\nPainel encerrado; a campanha continua executando.\n")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
