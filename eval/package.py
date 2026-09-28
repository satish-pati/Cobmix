"""
eval/package.py
---------------
Phase 5 — Replication Package Assembler

Copies all evaluation artefacts into a structured replication_package/
directory and zips it for submission.

Layout:
  replication_package/
    README.md
    extractor/      <- cobmix src/, pyproject.toml, tests/
    eval/           <- all eval/ scripts
    results/        <- the full results/ tree
    datasets/       <- results/datasets/ (train/val/test splits etc.)
    model/          <- model config + training script placeholder

Usage:
    python eval/package.py [--out-dir replication_package] [--zip]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def copy_tree(src: Path, dst: Path, ignore_patterns=("__pycache__", "*.pyc", ".git")):
    if not src.exists():
        print(f"  [!] Source not found, skipping: {src}")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*ignore_patterns))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble COBMix replication package.")
    parser.add_argument("--out-dir", default="replication_package")
    parser.add_argument("--zip", action="store_true", help="Also create a .zip archive.")
    parser.add_argument("--no-datasets", action="store_true",
                        help="Exclude large dataset files (train/val/test JSON).")
    args = parser.parse_args(argv)

    out = ROOT / args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    print(f"Assembling replication package at {out} …")

    # extractor/
    copy_tree(ROOT / "src",          out / "extractor" / "src")
    copy_tree(ROOT / "tests",        out / "extractor" / "tests")
    for f in ["pyproject.toml", "README.md", ".gitignore"]:
        src = ROOT / f
        if src.exists():
            shutil.copy2(src, out / "extractor" / f)

    # eval/
    copy_tree(ROOT / "eval",         out / "eval")

    # results/ (excluding datasets if --no-datasets)
    results_src = ROOT / "results"
    if results_src.exists():
        for sub in results_src.iterdir():
            if sub.name == "datasets" and args.no_datasets:
                print("  Skipping datasets/ (--no-datasets)")
                continue
            copy_tree(sub, out / "results" / sub.name)

    # model/ — placeholder
    model_dir = out / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "README.md").write_text(
        "# Model\n\nPlace model config YAML and training script here.\n"
        "The model is not included in the replication package to keep file size manageable.\n"
        "Training scripts are in eval/train_eval.py.\n",
        encoding="utf-8"
    )

    # Top-level README
    _write_package_readme(out)

    print(f"Package assembled: {out}")

    if args.zip:
        zip_path = ROOT / f"{args.out_dir}.zip"
        print(f"Creating {zip_path} …")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in out.rglob("*"):
                zf.write(f, f.relative_to(ROOT))
        print(f"Wrote {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")

    _log(args, out)
    return 0


def _write_package_readme(out: Path):
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"

    content = f"""# COBMix Replication Package

Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
COBMix commit: {git_sha}

## Layout

```
extractor/      COBMix tool source code and test suite
eval/           All evaluation scripts
results/
  raw/          Machine-generated CSV/JSON (one file per script)
  tables/       Aggregated paper tables (T1–T8)
  figures/      PDF figures for the paper
  paper/        LaTeX table files (tab_T*.tex) and machine_spec.txt
  gates/        Pre-run design decisions (G1–G4)
  datasets/     Train/val/test splits for each task
model/          Model config and training script
```

## Reproducing the Paper

### Prerequisites
```bash
pip install -e "extractor/.[dev]"
pip install scipy matplotlib pandas
```

### Step 1 — Obtain the corpus
```bash
# X-COBOL dataset
git clone https://github.com/RISHA-Lab/X-COBOL corpus/
```

### Step 2 — Profile and gate decisions
```bash
python eval/profile_constructs.py --corpus-dir corpus/
python eval/profile_units.py      --corpus-dir corpus/
# Fill in results/gates/G1_unit_decision.md, then continue
```

### Step 3 — Tool-level evaluation
```bash
pytest extractor/tests/ -v 2>&1 | tee results/raw/test_suite.txt
python eval/run_corpus.py         --corpus-dir corpus/
python eval/benchmark_throughput.py --corpus-dir corpus/ --runs 5
```

### Step 4 — Build datasets
```bash
python eval/build_naming_dataset.py --corpus-dir corpus/
python eval/build_clone_dataset.py  --corpus-dir corpus/
python eval/build_biz_rule_dataset.py --corpus-dir corpus/
```

### Step 5 — Train and evaluate (all conditions × 5 seeds)
```bash
python eval/train_eval.py --task naming  --conditions all --seeds 5
python eval/train_eval.py --task clone   --conditions all --seeds 5
python eval/train_eval.py --task bizrule --conditions all --seeds 5
```

### Step 6 — Ablation and statistics
```bash
python eval/ablation.py
python eval/stats.py
```

All paper tables are now in `results/paper/tab_T*.tex`.
All figures are in `results/figures/*.pdf`.
"""
    (out / "README.md").write_text(content, encoding="utf-8")


def _log(args, out: Path):
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — package.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Output:** `{out}`\n"
        f"- **Zip:** {args.zip}\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
