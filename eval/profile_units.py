"""
eval/profile_units.py
---------------------
Phase 1.3 — Unit Size & Path Count Profile

For each COBOL program, counts paragraphs and estimates path counts per view.
Writes results/raw/unit_sizes.csv.
The output informs the G1 gate decision: paragraph vs. program level representation.

Usage:
    python eval/profile_units.py --corpus-dir <path> [--copy-path <dir>]
                                  [--output results/raw/unit_sizes.csv]
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver


FIELDNAMES = [
    "program_path", "paragraph_name",
    "loc", "num_stmts",
    "num_nodes_ast", "num_edges_ast",
    "num_nodes_cfg", "num_edges_cfg",
    "num_nodes_dfg", "num_edges_dfg",
    "num_nodes_overlay", "num_edges_overlay",
    "num_nodes_copybook", "num_edges_copybook",
    "num_nodes_division", "num_edges_division",
    "est_paths_ast", "est_paths_cfg", "est_paths_dfg",
    "error",
]

# Rough path count estimate: for a graph with N nodes and E edges,
# sample paths ≈ min(N * (N-1), E * max_path_len)
MAX_PATH_LEN = 8


def _est_paths(g) -> int:
    n = g.number_of_nodes()
    e = g.number_of_edges()
    return min(n * max(n - 1, 1), e * MAX_PATH_LEN)


def profile_program(path: Path, copy_paths: list[str]) -> list[dict]:
    src = path.read_text(encoding="utf-8", errors="replace")
    rows = []

    try:
        driver = CombinedDriver(
            src_code=src,
            code_file=path,
            copy_paths=copy_paths,
            graphs=["ast", "cfg", "dfg", "overlay", "copybook", "division"],
        )
    except Exception as exc:
        return [{"program_path": str(path), "paragraph_name": "__program__",
                 "error": str(exc)}]

    views = driver.views
    cfg = views.get("cfg")

    # Identify paragraph nodes from CFG
    paragraphs = []
    if cfg:
        paragraphs = [n for n, d in cfg.nodes(data=True)
                      if d.get("type") in ("paragraph_header", "section_header")
                      or str(n).startswith("para:")]

    if not paragraphs:
        paragraphs = ["__program__"]

    loc_total = len(src.splitlines())

    for para in paragraphs:
        para_name = str(para).removeprefix("para:")
        # Paragraph LOC: approximate by counting stmt nodes in CFG reachable from para
        stmt_nodes = []
        if cfg and para in cfg:
            stmt_nodes = [v for _, v, d in cfg.out_edges(para, data=True)
                          if str(v).startswith("stmt:")]

        row = {
            "program_path":    str(path),
            "paragraph_name":  para_name,
            "loc":             loc_total if para == "__program__" else len(stmt_nodes) * 2,
            "num_stmts":       len(stmt_nodes),
            "error":           "",
        }
        for vname in ["ast", "cfg", "dfg", "overlay", "copybook", "division"]:
            g = views.get(vname)
            if g:
                row[f"num_nodes_{vname}"] = g.number_of_nodes()
                row[f"num_edges_{vname}"] = g.number_of_edges()
            else:
                row[f"num_nodes_{vname}"] = 0
                row[f"num_edges_{vname}"] = 0

        row["est_paths_ast"] = _est_paths(views["ast"]) if views.get("ast") else 0
        row["est_paths_cfg"] = _est_paths(views["cfg"]) if views.get("cfg") else 0
        row["est_paths_dfg"] = _est_paths(views["dfg"]) if views.get("dfg") else 0
        rows.append(row)

    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile unit sizes and path counts.")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--output", default="results/raw/unit_sizes.csv")
    parser.add_argument("--ext", default=".cbl,.cob")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N files (0=all).")
    args = parser.parse_args(argv)

    corpus = Path(args.corpus_dir)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"No COBOL files found in {corpus}", file=sys.stderr)
        return 1

    print(f"Profiling units in {len(files)} files …")
    t0 = time.perf_counter()

    all_rows = []
    errors = 0
    for i, f in enumerate(files, 1):
        rows = profile_program(f, args.copy_paths)
        all_rows.extend(rows)
        if any(r.get("error") for r in rows):
            errors += 1
        if i % 50 == 0:
            print(f"  {i}/{len(files)} — {len(all_rows)} units so far", flush=True)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})

    elapsed = time.perf_counter() - t0
    total_units = len(all_rows)

    # Summary stats
    valid = [r for r in all_rows if not r.get("error")]
    if valid:
        import statistics
        stmts = [int(r.get("num_stmts", 0)) for r in valid]
        paths_cfg = [int(r.get("est_paths_cfg", 0)) for r in valid]
        print(f"\n=== Unit Profile Summary ({total_units} units, {elapsed:.1f}s) ===")
        print(f"  Median stmts/para    : {statistics.median(stmts):.1f}")
        print(f"  Median CFG paths/para: {statistics.median(paths_cfg):.1f}")
        print(f"  Errors               : {errors}")
        if statistics.median(paths_cfg) < 5:
            print("\n  [!] Median CFG path count < 5 at paragraph level.")
            print("     Consider program-level units. Update G1_unit_decision.md.")
        else:
            print("\n  [OK] Paragraph level appears viable (median paths >= 5).")

    print(f"\nWrote {out_path}")
    _log(args, out_path, total_units, errors, elapsed)
    return 0


def _log(args, out_path: Path, total: int, errors: int, elapsed: float):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — profile_units.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** `{args.corpus_dir}`\n"
        f"- **Output files:** `{out_path}`\n"
        f"- **Key numbers:** {total} units, {errors} errors, {elapsed:.1f}s\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
