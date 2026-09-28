"""
eval/ablation.py
----------------
Phase 3.5 — Per-View Ablation Analysis (RQ4)

Reads the raw metrics CSVs and computes the marginal contribution (delta F1)
of each COBOL-specific view relative to Full COBMix (C5).

Decision rule (from G4_stats_plan.md):
  A view earns its place if delta_F1 >= 2 * std(C5 repeated runs) on >= 1 task.

Writes: results/raw/ablation_deltas.csv
        results/tables/T7_ablation.csv

Usage:
    python eval/ablation.py
"""
from __future__ import annotations

import csv
import subprocess
import statistics
from datetime import datetime, timezone
from pathlib import Path

# Condition names that correspond to "Full COBMix minus one view"
# The train_eval.py script produces rows with condition= "C5_no_overlay" etc.
MINUS_MAP = {
    "overlay":  "C5_no_overlay",
    "copybook": "C5_no_copybook",
    "division": "C5_no_division",
}
FULL_CONDITION = "C5"
TASKS = ["naming", "clone", "classification"]
METRIC_COL = {
    "naming":         "f1_subword",
    "clone":          "f1",
    "classification": "accuracy",
    "bizrule":        "agreement_f1",
}

RAW_DIR    = Path("results/raw")
TABLE_DIR  = Path("results/tables")


def _load_metrics(task: str) -> list[dict]:
    path = RAW_DIR / f"{task}_metrics.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f1s(rows: list[dict], condition: str, task: str) -> list[float]:
    col = METRIC_COL[task]
    return [float(r[col]) for r in rows
            if r.get("condition") == condition and r.get("split") in ("test", "")]


def main() -> int:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # G4 threshold: earns place if delta >= 2*std of C5
    results = []

    for task in TASKS:
        rows = _load_metrics(task)
        if not rows:
            print(f"  [!] No data for task={task} — skipping.")
            continue

        c5_f1s = _f1s(rows, FULL_CONDITION, task)
        if len(c5_f1s) < 2:
            print(f"  [!] Not enough C5 runs for task={task}.")
            continue

        c5_mean  = statistics.mean(c5_f1s)
        c5_std   = statistics.stdev(c5_f1s)
        threshold = 2 * c5_std

        for view, cond_name in MINUS_MAP.items():
            minus_f1s = _f1s(rows, cond_name, task)
            if not minus_f1s:
                print(f"  [!] No data for condition={cond_name}, task={task}.")
                delta_mean, delta_std, earns = None, None, None
            else:
                minus_mean  = statistics.mean(minus_f1s)
                minus_std   = statistics.stdev(minus_f1s) if len(minus_f1s) > 1 else 0.0
                delta_mean  = round(c5_mean - minus_mean, 4)
                delta_std   = round(statistics.sqrt(c5_std**2 + minus_std**2), 4)
                earns       = delta_mean >= threshold

            results.append({
                "view_removed":  view,
                "task":          task,
                "c5_f1_mean":    round(c5_mean, 4),
                "c5_f1_std":     round(c5_std, 4),
                "minus_f1_mean": round(statistics.mean(minus_f1s), 4) if minus_f1s else "",
                "delta_f1_mean": delta_mean,
                "delta_f1_std":  delta_std,
                "threshold_2std":round(threshold, 4),
                "earns_place":   earns,
                "run_timestamp": datetime.now(timezone.utc).isoformat(),
            })

    # Write raw deltas
    raw_out = RAW_DIR / "ablation_deltas.csv"
    fieldnames = [
        "view_removed", "task", "c5_f1_mean", "c5_f1_std",
        "minus_f1_mean", "delta_f1_mean", "delta_f1_std",
        "threshold_2std", "earns_place", "run_timestamp",
    ]
    with open(raw_out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    # Write aggregated table T7
    table_out = TABLE_DIR / "T7_ablation.csv"
    with open(table_out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    # Pretty print
    print(f"\n=== Ablation Results (RQ4) ===")
    print(f"{'View':<12} {'Task':<10} {'delta_F1':>9} {'std':>6} {'>=2*std_C5':>12} {'Earns place':>12}")
    print("-" * 70)
    for r in results:
        delta = f"{r['delta_f1_mean']:.4f}" if r["delta_f1_mean"] is not None else "   N/A"
        std   = f"{r['delta_f1_std']:.4f}"  if r["delta_f1_std"]  is not None else "   N/A"
        earns = str(r["earns_place"])
        print(f"{r['view_removed']:<12} {r['task']:<10} {delta:>9} {std:>6} "
              f"{r['threshold_2std']:>12} {earns:>12}")

    # Summary verdict
    print(f"\n=== View Verdicts ===")
    for view in MINUS_MAP:
        tasks_earned = [r["task"] for r in results
                        if r["view_removed"] == view and r.get("earns_place")]
        if tasks_earned:
            print(f"  {view:12}: EARNS ITS PLACE on {tasks_earned}")
        else:
            print(f"  {view:12}: does NOT earn its place on any task")

    print(f"\nWrote {raw_out}")
    print(f"Wrote {table_out}")

    _log(raw_out, table_out, len(results))
    return 0


def _log(raw_out, table_out, n_rows):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — ablation.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** raw/{{naming,clone,bizrule}}_metrics.csv\n"
        f"- **Output files:** `{raw_out}`, `{table_out}`\n"
        f"- **Key numbers:** {n_rows} delta rows computed\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
