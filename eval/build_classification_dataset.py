"""
eval/build_classification_dataset.py
------------------------------------
Phase 3.4 — Program Classification Dataset Builder

Extracts program-level graph representations and classifies them based on
their repository/domain folder name (the root folder inside the corpus).

Writes:
  results/datasets/classification/train.json
  results/datasets/classification/val.json
  results/datasets/classification/test.json

Usage:
    python eval/build_classification_dataset.py --corpus-dir <path>
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver

VIEWS = ["ast", "cfg", "dfg", "overlay", "copybook", "division"]
MAX_FILE_BYTES = 50 * 1024  # 50 KB — skip outlier files to speed up processing

def extract_file_graphs(path: Path, copy_paths: list[str]) -> dict | None:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        driver = CombinedDriver(
            src_code=src,
            code_file=path,
            copy_paths=copy_paths,
            graphs=VIEWS,
        )
        graphs = {}
        for v in VIEWS:
            g = driver.views.get(v)
            if g:
                from networkx.readwrite import json_graph
                graphs[v] = json_graph.node_link_data(g)
        if not graphs:
            return None
        return graphs
    except Exception:
        return None

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Program Classification dataset.")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--out-dir", default="results/datasets/classification")
    parser.add_argument("--ext", default=".cbl,.cob")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    args = parser.parse_args(argv)

    corpus = Path(args.corpus_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exts = {e.strip().lower() for e in args.ext.split(",")}

    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    if args.limit:
        files = files[:args.limit]

    print(f"Extracting classification units from {len(files)} files …")
    all_units = []
    
    for i, f in enumerate(files, 1):
        if f.stat().st_size > MAX_FILE_BYTES:
            continue
            
        graphs = extract_file_graphs(f, args.copy_paths)
        if graphs:
            # Get the root repository folder name as the class label
            # e.g., corpus_dir/crud-payroll/src/main.cbl -> crud-payroll
            rel_path = f.relative_to(corpus)
            label = rel_path.parts[0] if len(rel_path.parts) > 0 else "unknown"
            
            all_units.append({
                "program": str(f),
                "label": label,
                "graphs": graphs
            })
            
        if i % 50 == 0:
            print(f"  {i}/{len(files)} — {len(all_units)} valid programs extracted", flush=True)

    print(f"Total units extracted: {len(all_units)}")
    if not all_units:
        print("No units extracted!")
        return 1
        
    rng = random.Random(args.seed)
    rng.shuffle(all_units)
    n = len(all_units)
    n_train = int(n * args.train_ratio)
    n_val = int(n * args.val_ratio)
    
    splits = {
        "train": all_units[:n_train],
        "val": all_units[n_train:n_train+n_val],
        "test": all_units[n_train+n_val:]
    }

    for split, units in splits.items():
        p = out_dir / f"{split}.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(units, fh, ensure_ascii=False, indent=2)
        print(f"  {split}: {len(units)} units -> {p}")
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
