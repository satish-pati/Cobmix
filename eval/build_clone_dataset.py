"""
eval/build_clone_dataset.py
---------------------------
Phase 3.3 — Clone Detection Dataset Builder

Builds a labelled pair set from the corpus.
Every positive pair is tagged with its origin:
  - "copybook"  : both units include the same COPY book
  - "logic"     : units share high CFG/DFG path similarity (no shared copybook)

Writes:
  results/datasets/clones/pairs.json
  results/datasets/clones/cobrex_version.txt  (version tag placeholder)

Pairs JSON format:
[
  {
    "program_a": "<path>", "paragraph_a": "<name>",
    "program_b": "<path>", "paragraph_b": "<name>",
    "label": 1,           # 1 = clone, 0 = non-clone
    "origin": "copybook"  # "copybook" | "logic" | null (for non-clones)
  },
  ...
]

Usage:
    python eval/build_clone_dataset.py --corpus-dir <path> [--copy-path <dir>]
                                        [--logic-threshold 0.8]
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver


def _get_copybooks(driver) -> set[str]:
    """Return set of copybook names included by this program."""
    g = driver.views.get("copybook")
    if not g:
        return set()
    return {str(v).removeprefix("copy:")
            for u, v, d in g.edges(data=True)
            if d.get("type") == "includes"}


def _cfg_path_bag(driver) -> set[str]:
    """Simple bag of (src_type, edge_type, dst_type) triples from CFG."""
    g = driver.views.get("cfg")
    if not g:
        return set()
    bag = set()
    for u, v, d in g.edges(data=True):
        ut = g.nodes[u].get("type", "?")
        vt = g.nodes[v].get("type", "?")
        et = d.get("type", "?")
        bag.add(f"{ut}-{et}-{vt}")
    return bag


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build COBOL clone detection dataset.")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--out-dir", default="results/datasets/clones")
    parser.add_argument("--ext", default=".cbl,.cob")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only first N files (0=all).")
    parser.add_argument("--logic-threshold", type=float, default=0.8,
                        help="Jaccard threshold for logic-clone detection.")
    parser.add_argument("--neg-ratio", type=float, default=2.0,
                        help="Ratio of negative to positive pairs.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    corpus  = Path(args.corpus_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"No COBOL files in {corpus}", file=sys.stderr)
        return 1

    print(f"Loading {len(files)} programs …")
    MAX_FILE_BYTES = 50 * 1024  # 50 KB — skip auto-generated / concatenated outliers
    programs = []  # list of {path, copybooks, cfg_bag}
    for i, f in enumerate(files, 1):
        if f.stat().st_size > MAX_FILE_BYTES:
            continue  # skip oversized files
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            driver = CombinedDriver(
                src_code=src, code_file=f, copy_paths=args.copy_paths,
                graphs=["cfg", "copybook"],
            )
            programs.append({
                "path":      str(f),
                "copybooks": _get_copybooks(driver),
                "cfg_bag":   _cfg_path_bag(driver),
            })
        except Exception:
            pass
        if i % 50 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    print(f"  Loaded {len(programs)} programs. Building pairs …")

    positive_pairs = []
    rng = random.Random(args.seed)

    # Pass 1: copybook-induced clones
    copy_to_progs: dict[str, list[int]] = {}
    for idx, p in enumerate(programs):
        for cb in p["copybooks"]:
            copy_to_progs.setdefault(cb, []).append(idx)

    for cb, idxs in copy_to_progs.items():
        if len(idxs) < 2:
            continue
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a, b = programs[idxs[i]], programs[idxs[j]]
                positive_pairs.append({
                    "program_a": a["path"], "paragraph_a": "__program__",
                    "program_b": b["path"], "paragraph_b": "__program__",
                    "label": 1, "origin": "copybook",
                    "shared_copybook": cb,
                })

    # Pass 2: logic clones (high CFG Jaccard, no shared copybook)
    for i in range(len(programs)):
        for j in range(i + 1, len(programs)):
            a, b = programs[i], programs[j]
            if a["copybooks"] & b["copybooks"]:
                continue  # already a copybook clone
            sim = _jaccard(a["cfg_bag"], b["cfg_bag"])
            if sim >= args.logic_threshold:
                positive_pairs.append({
                    "program_a": a["path"], "paragraph_a": "__program__",
                    "program_b": b["path"], "paragraph_b": "__program__",
                    "label": 1, "origin": "logic",
                    "cfg_jaccard": round(sim, 4),
                })

    # Negative pairs: random non-clone pairs
    n_neg = int(len(positive_pairs) * args.neg_ratio)
    all_indices = list(range(len(programs)))
    negative_pairs = []
    attempts = 0
    positive_set = {(p["program_a"], p["program_b"]) for p in positive_pairs}
    while len(negative_pairs) < n_neg and attempts < n_neg * 10:
        i, j = rng.sample(all_indices, 2)
        a, b = programs[i], programs[j]
        key = (a["path"], b["path"])
        if key not in positive_set and (b["path"], a["path"]) not in positive_set:
            negative_pairs.append({
                "program_a": a["path"], "paragraph_a": "__program__",
                "program_b": b["path"], "paragraph_b": "__program__",
                "label": 0, "origin": None,
            })
            positive_set.add(key)
        attempts += 1

    all_pairs = positive_pairs + negative_pairs
    rng.shuffle(all_pairs)

    out_path = out_dir / "pairs.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(all_pairs, fh, ensure_ascii=False, indent=2)

    n_cb    = sum(1 for p in positive_pairs if p.get("origin") == "copybook")
    n_logic = sum(1 for p in positive_pairs if p.get("origin") == "logic")
    print(f"\n=== Clone Dataset Summary ===")
    print(f"  Positive (copybook) : {n_cb}")
    print(f"  Positive (logic)    : {n_logic}")
    print(f"  Negative            : {len(negative_pairs)}")
    print(f"  Total pairs         : {len(all_pairs)}")
    print(f"\nWrote {out_path}")

    _log(args, out_path, n_cb, n_logic, len(negative_pairs))
    return 0


def _log(args, out_path, n_cb, n_logic, n_neg):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — build_clone_dataset.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** `{args.corpus_dir}`, logic_threshold={args.logic_threshold}\n"
        f"- **Output files:** `{out_path}`\n"
        f"- **Key numbers:** +copybook={n_cb}, +logic={n_logic}, negative={n_neg}\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
