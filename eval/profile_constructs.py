"""
eval/profile_constructs.py
--------------------------
Phase 1.2 — Construct Frequency Profiling

Iterates every .cbl file in a corpus directory, counts COBOL-specific constructs,
and writes results/raw/corpus_stats.csv.

Usage:
    python eval/profile_constructs.py --corpus-dir <path> [--output results/raw/corpus_stats.csv]
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Heuristic construct detectors (no full parse needed for frequency counting)
# ---------------------------------------------------------------------------

_RE_REDEFINES = re.compile(r'\bREDEFINES\b', re.IGNORECASE)
_RE_RENAMES   = re.compile(r'^\s{6,}\d+\s+\w[\w-]*\s+RENAMES\b', re.IGNORECASE | re.MULTILINE)
_RE_OCCURS    = re.compile(r'\bOCCURS\b', re.IGNORECASE)
_RE_COPY      = re.compile(r'^\s{6,}COPY\s+([\w-]+)', re.IGNORECASE | re.MULTILINE)
_RE_PERF_THRU = re.compile(r'\bPERFORM\b.*\bTHRU\b', re.IGNORECASE)
_RE_SELECT    = re.compile(r'^\s{6,}SELECT\b', re.IGNORECASE | re.MULTILINE)
_RE_LEVEL     = re.compile(r'^\s{6,}(\d{1,2})\s+\w', re.MULTILINE)


def _max_level_depth(src: str) -> int:
    """Approximate maximum data level number found in source."""
    levels = {int(m.group(1)) for m in _RE_LEVEL.finditer(src)
              if int(m.group(1)) not in (66, 77, 88)}
    if not levels:
        return 0
    # Levels 01, 02 … 49; depth is how many distinct non-special levels > 01 exist
    return max(levels)


def profile_file(path: Path) -> dict:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"program_path": str(path), "error": str(exc)}

    lines = src.splitlines()
    loc = len(lines)

    copy_names = _RE_COPY.findall(src)
    redefines_count = len(_RE_REDEFINES.findall(src))
    renames_count   = len(_RE_RENAMES.findall(src))
    occurs_count    = len(_RE_OCCURS.findall(src))
    perf_thru_count = len(_RE_PERF_THRU.findall(src))
    has_file_ctrl   = bool(_RE_SELECT.search(src))
    max_level       = _max_level_depth(src)

    return {
        "program_path":      str(path),
        "total_loc":         loc,
        "has_redefines":     redefines_count > 0,
        "redefines_count":   redefines_count,
        "has_renames":       renames_count > 0,
        "renames_count":     renames_count,
        "has_occurs":        occurs_count > 0,
        "occurs_count":      occurs_count,
        "max_level_depth":   max_level,
        "num_copy_stmts":    len(copy_names),
        "unique_copy_names": len(set(copy_names)),
        "has_perform_thru":  perf_thru_count > 0,
        "perform_thru_count":perf_thru_count,
        "has_file_control":  has_file_ctrl,
        "error":             "",
    }


FIELDNAMES = [
    "program_path", "total_loc",
    "has_redefines", "redefines_count",
    "has_renames", "renames_count",
    "has_occurs", "occurs_count",
    "max_level_depth",
    "num_copy_stmts", "unique_copy_names",
    "has_perform_thru", "perform_thru_count",
    "has_file_control",
    "error",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile COBOL construct frequencies in a corpus.")
    parser.add_argument("--corpus-dir", required=True, help="Root directory of the COBOL corpus.")
    parser.add_argument("--output", default="results/raw/corpus_stats.csv")
    parser.add_argument("--ext", default=".cbl,.cob", help="Comma-separated file extensions to scan.")
    args = parser.parse_args(argv)

    corpus = Path(args.corpus_dir)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if not files:
        print(f"No COBOL files found in {corpus}", file=sys.stderr)
        return 1

    print(f"Profiling {len(files)} files …")
    t0 = time.perf_counter()

    rows = []
    for i, f in enumerate(files, 1):
        rows.append(profile_file(f))
        if i % 100 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    elapsed = time.perf_counter() - t0
    total   = len(rows)
    errors  = sum(1 for r in rows if r.get("error"))

    # --- summary ---
    def pct(n): return f"{n}/{total} ({100*n/total:.1f}%)"
    has = lambda k: sum(1 for r in rows if r.get(k) and not r.get("error"))

    print(f"\n=== Construct Frequency Summary ({total} programs, {elapsed:.1f}s) ===")
    print(f"  REDEFINES     : {pct(has('has_redefines'))}")
    print(f"  RENAMES       : {pct(has('has_renames'))}")
    print(f"  OCCURS        : {pct(has('has_occurs'))}")
    print(f"  PERFORM THRU  : {pct(has('has_perform_thru'))}")
    print(f"  File control  : {pct(has('has_file_control'))}")
    print(f"  Errors        : {errors}")
    print(f"\nWrote {out_path}")

    # Append to run log
    _log(args, out_path, total, errors, elapsed)
    return 0


def _log(args, out_path: Path, total: int, errors: int, elapsed: float):
    log = Path("results/results_log.md")
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"

    entry = (
        f"\n## Run: {ts} — profile_constructs.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** `{args.corpus_dir}`\n"
        f"- **Output files:** `{out_path}`\n"
        f"- **Key numbers:** {total} programs, {errors} errors, {elapsed:.1f}s\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
