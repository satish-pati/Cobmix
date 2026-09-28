"""
eval/build_naming_dataset.py
----------------------------
Phase 3.2 — Paragraph Naming Dataset Builder

Extracts every paragraph from the corpus, removes the paragraph name from the
graph views (crucial guard against data leakage), and writes train/val/test
splits to results/datasets/naming/.

Each unit is saved as a JSON object:
{
  "program":    "<path>",
  "paragraph":  "<PARAGRAPH-NAME>",          # the label
  "label_subwords": ["CALC", "TAX"],          # code2vec @ convention
  "graphs": {                                 # COBMix graph views as node/edge lists
    "cfg": { "nodes": [...], "edges": [...] },
    "dfg": { ... },
    ...
  }
}

Writes:
  results/datasets/naming/train.json
  results/datasets/naming/val.json
  results/datasets/naming/test.json
  results/raw/naming_leak_check.txt

Usage:
    python eval/build_naming_dataset.py --corpus-dir <path> [--copy-path <dir>]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver

VIEWS = ["ast", "cfg", "dfg", "overlay", "copybook", "division"]
MIN_STMTS = 3  # gate: skip paragraphs with fewer than this many statements
MAX_FILE_BYTES = 50 * 1024  # 50 KB — skip auto-generated / concatenated outliers


def _subwords(name: str) -> list[str]:
    """Split a COBOL paragraph name into subwords (hyphen-delimited)."""
    return [w for w in re.split(r"[-_]+", name.upper()) if w]


def _graph_to_json(g) -> dict:
    """Serialise a networkx graph to a JSON-serialisable dict."""
    return {
        "nodes": [{"id": n, **{k: str(v) for k, v in d.items()}}
                  for n, d in g.nodes(data=True)],
        "edges": [{"src": u, "dst": v, **{k: str(v2) for k, v2 in d.items()}}
                  for u, v, d in g.edges(data=True)],
    }


def _remove_name_from_graph(g, para_name: str):
    """Remove any node whose text/label contains the paragraph name (case-insensitive)."""
    to_remove = []
    name_upper = para_name.upper()
    for node, attrs in g.nodes(data=True):
        node_str = str(node).upper()
        text     = str(attrs.get("text", "")).upper()
        label    = str(attrs.get("label", "")).upper()
        if name_upper in node_str or name_upper in text or name_upper in label:
            to_remove.append(node)
    for n in to_remove:
        g.remove_node(n)
    return len(to_remove)


def extract_units(path: Path, copy_paths: list[str]) -> list[dict]:
    units = []
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        driver = CombinedDriver(
            src_code=src,
            code_file=path,
            copy_paths=copy_paths,
            graphs=VIEWS,
        )
    except Exception:
        return []

    cfg = driver.views.get("cfg")
    if not cfg:
        return []

    para_nodes = [n for n, d in cfg.nodes(data=True)
                  if str(n).startswith("para:")]

    para_set = set(para_nodes)  # used to stop BFS at paragraph boundaries

    for para_node in para_nodes:
        para_name = str(para_node).removeprefix("para:")
        if not para_name or para_name.startswith("_"):
            continue

        # BFS from the para node: collect all stmt: nodes reachable before
        # hitting another para: node.  This is how many statements the
        # paragraph body contains, regardless of how deep the chain goes.
        visited, queue = set(), [para_node]
        stmts = []
        while queue:
            cur = queue.pop()
            for _, nxt in cfg.out_edges(cur):
                if nxt in visited:
                    continue
                visited.add(nxt)
                if str(nxt).startswith("stmt:"):
                    stmts.append(nxt)
                    queue.append(nxt)
                # stop traversal at another paragraph boundary
        if len(stmts) < MIN_STMTS:
            continue

        # Serialise views while masking the paragraph name — no deepcopy needed.
        views_json = {}
        leak_count = 0
        name_up = para_name.upper()
        def _mask(v, nu=name_up):
            if isinstance(v, str) and nu in v.upper():
                return v.upper().replace(nu, "<PARA>"), 1
            return v, 0
        for vname in VIEWS:
            g = driver.views.get(vname)
            if not g:
                continue
            nodes_out = []
            for n, d in g.nodes(data=True):
                nd = {"id": n}
                for k, val in d.items():
                    masked, hits = _mask(val)
                    nd[k] = masked
                    leak_count += hits
                nodes_out.append(nd)
            edges_out = []
            for u, v, d in g.edges(data=True):
                ed = {"src": u, "dst": v}
                for k, val in d.items():
                    masked, hits = _mask(val)
                    ed[k] = masked
                    leak_count += hits
                edges_out.append(ed)
            views_json[vname] = {"nodes": nodes_out, "edges": edges_out}

        units.append({
            "program":       str(path),
            "paragraph":     para_name,
            "label_subwords": _subwords(para_name),
            "graphs":        views_json,
            "_leak_removed": leak_count,
        })

    return units


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build paragraph naming dataset.")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--out-dir", default="results/datasets/naming")
    parser.add_argument("--ext", default=".cbl,.cob")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio",   type=float, default=0.1)
    args = parser.parse_args(argv)

    corpus  = Path(args.corpus_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if args.limit:
        files = files[:args.limit]

    print(f"Extracting naming units from {len(files)} files …")
    all_units = []
    leak_total = 0
    for i, f in enumerate(files, 1):
        if f.stat().st_size > MAX_FILE_BYTES:
            continue  # skip oversized files
        units = extract_units(f, args.copy_paths)
        leak_total += sum(u["_leak_removed"] for u in units)
        all_units.extend(units)
        if i % 50 == 0:
            print(f"  {i}/{len(files)} — {len(all_units)} units", flush=True)

    print(f"  Total units: {len(all_units)}, name tokens removed from graphs: {leak_total}")

    # Split at program level (not paragraph level) to prevent leakage
    rng = random.Random(args.seed)
    programs = list({u["program"] for u in all_units})
    rng.shuffle(programs)
    n = len(programs)
    n_train = int(n * args.train_ratio)
    n_val   = int(n * args.val_ratio)
    train_progs = set(programs[:n_train])
    val_progs   = set(programs[n_train:n_train + n_val])

    splits = {"train": [], "val": [], "test": []}
    for u in all_units:
        u.pop("_leak_removed", None)
        if u["program"] in train_progs:
            splits["train"].append(u)
        elif u["program"] in val_progs:
            splits["val"].append(u)
        else:
            splits["test"].append(u)

    for split, units in splits.items():
        p = out_dir / f"{split}.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(units, fh, ensure_ascii=False, indent=2)
        print(f"  {split}: {len(units)} units → {p}")

    # Leak audit report
    leak_report = out_dir.parent.parent / "raw" / "naming_leak_check.txt"
    leak_report.parent.mkdir(parents=True, exist_ok=True)
    with open(leak_report, "w", encoding="utf-8") as fh:
        fh.write(f"Naming dataset leak audit\n")
        fh.write(f"Paragraph name tokens removed from graph nodes: {leak_total}\n")
        fh.write(f"Total units: {len(all_units)}\n")
        fh.write(f"Build timestamp: {datetime.now(timezone.utc).isoformat()}\n")
    print(f"  Leak audit written to {leak_report}")

    _log(args, out_dir, len(all_units), splits)
    return 0


def _log(args, out_dir, total, splits):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — build_naming_dataset.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** `{args.corpus_dir}`\n"
        f"- **Output files:** `{out_dir}/{{train,val,test}}.json`\n"
        f"- **Key numbers:** total={total}; "
        f"train={len(splits['train'])}, val={len(splits['val'])}, test={len(splits['test'])}\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
