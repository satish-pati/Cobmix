"""
eval/run_corpus.py
------------------
Phase 2.2 — Corpus-Scale Robustness Evaluation

Runs CombinedDriver (all six views) on every .cbl file in the corpus.
Records per-program success, node/edge counts, unresolved COPY stubs,
zero-edge graphs, crash info, and wall time.

Writes: results/raw/robustness.csv

Usage:
    python eval/run_corpus.py --corpus-dir <path> [--copy-path <dir>]
                               [--output results/raw/robustness.csv]
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver

VIEWS = ["ast", "cfg", "dfg", "overlay", "copybook", "division"]

FIELDNAMES = [
    "program_path", "views_requested", "success",
    "num_nodes", "num_edges",
    "unresolved_copy_count", "zero_edge_graph",
    "exception_type", "exception_msg",
    "wall_time_ms", "peak_rss_mb", "run_timestamp",
]


def _peak_rss_mb() -> float:
    try:
        import psutil, os
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / 1024 / 1024
    except Exception:
        return -1.0


def run_one(path: Path, copy_paths: list[str]) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    rss_before = _peak_rss_mb()
    t0 = time.perf_counter()

    row: dict = {
        "program_path":        str(path),
        "views_requested":     ",".join(VIEWS),
        "success":             False,
        "num_nodes":           0,
        "num_edges":           0,
        "unresolved_copy_count": 0,
        "zero_edge_graph":     False,
        "exception_type":      "",
        "exception_msg":       "",
        "wall_time_ms":        0.0,
        "peak_rss_mb":         0.0,
        "run_timestamp":       ts,
    }

    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        driver = CombinedDriver(
            src_code=src,
            code_file=path,
            copy_paths=copy_paths,
            graphs=VIEWS,
        )
        g = driver.graph
        unresolved = sum(
            1 for _, d in g.nodes(data=True) if d.get("unresolved") is True
        )
        row["success"]               = True
        row["num_nodes"]             = g.number_of_nodes()
        row["num_edges"]             = g.number_of_edges()
        row["unresolved_copy_count"] = unresolved
        row["zero_edge_graph"]       = g.number_of_edges() == 0
    except Exception as exc:
        row["exception_type"] = type(exc).__name__
        row["exception_msg"]  = str(exc)[:300]

    row["wall_time_ms"] = (time.perf_counter() - t0) * 1000
    row["peak_rss_mb"]  = max(0, _peak_rss_mb() - rss_before)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus-scale robustness evaluation for COBMix.")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--output", default="results/raw/robustness.csv")
    parser.add_argument("--ext", default=".cbl,.cob")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    corpus   = Path(args.corpus_dir)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"No COBOL files in {corpus}", file=sys.stderr)
        return 1

    print(f"Running robustness check on {len(files)} files …")
    t_global = time.perf_counter()

    rows = []
    for i, f in enumerate(files, 1):
        row = run_one(f, args.copy_paths)
        rows.append(row)
        status = "OK" if row["success"] else f"FAIL({row['exception_type']})"
        if i % 50 == 0 or not row["success"]:
            print(f"  [{i}/{len(files)}] {f.name} — {status}", flush=True)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    # --- Summary ---
    total    = len(rows)
    success  = sum(1 for r in rows if r["success"])
    crashes  = total - success
    zero_e   = sum(1 for r in rows if r.get("zero_edge_graph"))
    elapsed  = time.perf_counter() - t_global

    def pct(n): return f"{n}/{total} ({100*n/total:.1f}%)"

    print(f"\n=== Robustness Summary ({elapsed:.1f}s) ===")
    print(f"  Parse success     : {pct(success)}")
    print(f"  Crashes           : {pct(crashes)}")
    print(f"  Zero-edge graphs  : {pct(zero_e)}")
    print(f"\nWrote {out_path}")

    # Crash details
    crash_rows = [r for r in rows if not r["success"]]
    if crash_rows:
        print(f"\n  Top crash types:")
        from collections import Counter
        for exc_type, count in Counter(r["exception_type"] for r in crash_rows).most_common(5):
            print(f"    {exc_type}: {count}")

    _log(args, out_path, total, success, crashes, zero_e, elapsed)
    return 0


def _log(args, out_path, total, success, crashes, zero_e, elapsed):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — run_corpus.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** `{args.corpus_dir}`\n"
        f"- **Output files:** `{out_path}`\n"
        f"- **Key numbers:** {total} files; success={success}, crashes={crashes}, zero-edge={zero_e}; {elapsed:.1f}s\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
