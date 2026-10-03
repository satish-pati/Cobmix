"""
eval/benchmark_throughput.py
-----------------------------
Phase 2.4 — Extraction Throughput Benchmark (RQ5)

Runs each of 7 view combinations (each single view + full COBMix) over
the corpus N times with different seeds. Records wall-clock time and
peak RSS memory per program per run.

Writes: results/raw/throughput.csv

Usage:
    python eval/benchmark_throughput.py --corpus-dir <path> [--runs 5]
                                         [--output results/raw/throughput.csv]
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver

# View combinations to benchmark
CONDITIONS = [
    ["ast"],
    ["cfg"],
    ["dfg"],
    ["overlay"],
    ["copybook"],
    ["division"],
    ["ast", "cfg", "dfg", "overlay", "copybook", "division"],  # Full COBMix
]

FIELDNAMES = [
    "run_id", "seed", "views_active", "program_path",
    "wall_time_ms", "peak_rss_mb",
    "num_nodes", "num_edges",
    "run_timestamp", "machine_tag",
]


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        return -1.0


def _machine_tag() -> str:
    import platform
    return f"{platform.node()}-{platform.python_version()}"


def run_condition(files: list[Path], copy_paths: list[str],
                  views: list[str], run_id: int, seed: int) -> list[dict]:
    rows = []
    ts = datetime.now(timezone.utc).isoformat()
    tag = _machine_tag()
    views_str = ",".join(views)

    for path in files:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            rss_before = _rss_mb()
            t0 = time.perf_counter()
            driver = CombinedDriver(
                src_code=src,
                code_file=path,
                copy_paths=copy_paths,
                graphs=views,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            rss_delta = max(0, _rss_mb() - rss_before)
            g = driver.graph
            rows.append({
                "run_id":       run_id,
                "seed":         seed,
                "views_active": views_str,
                "program_path": str(path),
                "wall_time_ms": round(elapsed_ms, 2),
                "peak_rss_mb":  round(rss_delta, 2),
                "num_nodes":    g.number_of_nodes(),
                "num_edges":    g.number_of_edges(),
                "run_timestamp":ts,
                "machine_tag":  tag,
            })
        except Exception:
            rows.append({
                "run_id": run_id, "seed": seed,
                "views_active": views_str,
                "program_path": str(path),
                "wall_time_ms": -1, "peak_rss_mb": -1,
                "num_nodes": 0, "num_edges": 0,
                "run_timestamp": ts, "machine_tag": tag,
            })
        gc.collect()
    return rows


def _write_machine_spec():
    import platform
    spec_path = Path("results/paper/machine_spec.txt")
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    if spec_path.exists():
        return  # immutable once written

    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024**3)
    except Exception:
        ram_gb = -1

    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"

    try:
        import torch
        torch_ver = torch.__version__
        cuda_ver  = torch.version.cuda or "none"
    except Exception:
        torch_ver = "not installed"
        cuda_ver  = "n/a"

    lines = [
        f"CPU     : {platform.processor()} ({os.cpu_count()} logical cores)",
        f"RAM     : {ram_gb:.1f} GB",
        f"OS      : {platform.system()} {platform.release()} {platform.version()}",
        f"Python  : {platform.python_version()}",
        f"PyTorch : {torch_ver}",
        f"CUDA    : {cuda_ver}",
        f"COBMix  : {git_sha}",
        f"Date    : {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    ]
    spec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Machine spec written to {spec_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Throughput benchmark for COBMix view combinations.")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--runs", type=int, default=5, help="Number of repeated runs per condition.")
    parser.add_argument("--output", default="results/raw/throughput.csv")
    parser.add_argument("--ext", default=".cbl,.cob")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--condition", default="all",
                        help="Which condition index (0-6) or 'all'. Default all.")
    args = parser.parse_args(argv)

    corpus = Path(args.corpus_dir)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"No COBOL files in {corpus}", file=sys.stderr)
        return 1

    conditions = CONDITIONS if args.condition == "all" else [CONDITIONS[int(args.condition)]]
    seeds = [42, 123, 456, 789, 1337, 2024, 3141, 9999, 12345, 54321][:args.runs]

    _write_machine_spec()

    print(f"Benchmarking {len(conditions)} conditions × {len(seeds)} runs × {len(files)} files …")
    t_global = time.perf_counter()

    all_rows = []
    for views in conditions:
        views_str = ",".join(views)
        for run_idx, seed in enumerate(seeds, 1):
            print(f"  [{views_str}] run {run_idx}/{len(seeds)} …", flush=True)
            rows = run_condition(files, args.copy_paths, views, run_idx, seed)
            all_rows.extend(rows)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    elapsed = time.perf_counter() - t_global

    # Summary: median time per condition
    import statistics
    from collections import defaultdict
    by_cond: dict[str, list[float]] = defaultdict(list)
    for r in all_rows:
        if r["wall_time_ms"] >= 0:
            by_cond[r["views_active"]].append(r["wall_time_ms"])

    print(f"\n=== Throughput Summary ({elapsed:.1f}s total) ===")
    for views_str, times in by_cond.items():
        print(f"  [{views_str[:50]:<50}]  "
              f"median={statistics.median(times):.1f}ms  "
              f"IQR={statistics.quantiles(times, n=4)[2]-statistics.quantiles(times, n=4)[0]:.1f}ms")

    print(f"\nWrote {out_path}")
    _log(args, out_path, len(all_rows), elapsed)
    return 0


def _log(args, out_path, total_rows, elapsed):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — benchmark_throughput.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** `{args.corpus_dir}`, {args.runs} runs\n"
        f"- **Output files:** `{out_path}`\n"
        f"- **Key numbers:** {total_rows} rows, {elapsed:.1f}s\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
