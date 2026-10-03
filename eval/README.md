# COBMix Evaluation Scripts

Step-by-step guide for running the full evaluation and producing all paper artefacts.

## Prerequisites

```powershell
# Install COBMix in editable mode
pip install -e "..[dev]"

# Install eval dependencies
pip install scipy matplotlib pandas psutil
```

## Execution Order

### Phase 0 — Fill in gate documents (before anything else)

Review and complete:
- `results/gates/G1_unit_decision.md` — after profiling units
- `results/gates/G2_clone_definition.md` — before building clone dataset
- `results/gates/G3_baselines.md` — before any model run
- `results/gates/G4_stats_plan.md` — before any model run

### Phase 1 — Corpus profiling

```powershell
python eval/profile_constructs.py --corpus-dir <X-COBOL-path>
python eval/profile_units.py      --corpus-dir <X-COBOL-path>
```

Outputs: `results/raw/corpus_stats.csv`, `results/raw/unit_sizes.csv`

### Phase 2 — Tool-level evaluation

```powershell
# 2.1 Unit tests
pytest tests/ -v 2>&1 | Tee-Object -FilePath results/raw/test_suite.txt

# 2.2 Robustness
python eval/run_corpus.py --corpus-dir <X-COBOL-path>

# 2.4 Throughput (runs all 7 view combinations × 5 repetitions)
python eval/benchmark_throughput.py --corpus-dir <X-COBOL-path> --runs 5
```

Outputs: `results/raw/robustness.csv`, `results/raw/throughput.csv`

### Phase 3 — Dataset preparation

```powershell
python eval/build_naming_dataset.py  --corpus-dir <X-COBOL-path>
python eval/build_clone_dataset.py   --corpus-dir <X-COBOL-path>
python eval/build_biz_rule_dataset.py --corpus-dir <X-COBOL-path>
```

Outputs: `results/datasets/naming/`, `results/datasets/clones/`, `results/datasets/bizrule/`

### Phase 3 — Model training & evaluation

```powershell
python eval/train_eval.py --task naming  --conditions all --seeds 10
python eval/train_eval.py --task clone   --conditions all --seeds 10
python eval/train_eval.py --task bizrule --conditions all --seeds 10
```

Outputs: `results/raw/naming_metrics.csv`, `results/raw/clone_metrics.csv`, `results/raw/bizrule_metrics.csv`

The six conditions (C0–C5) and three ablation conditions (C5_no_overlay,
C5_no_copybook, C5_no_division) are all run automatically.

### Phase 3.5 — Ablation analysis

```powershell
python eval/ablation.py
```

Outputs: `results/raw/ablation_deltas.csv`, `results/tables/T7_ablation.csv`

### Phase 4 — Statistical analysis + paper outputs

```powershell
python eval/stats.py
```

Outputs:
- `results/tables/T1_construct_freq.csv` … `T8_per_project.csv`
- `results/figures/fig_*.pdf`
- `results/paper/tab_T*.tex`  ← paste `\input{tab_T4.tex}` directly in your paper

### Phase 5 — Replication package

```powershell
python eval/package.py --zip
```

Outputs: `replication_package/` + `replication_package.zip`

---

## Output Files Reference

| File | Paper Table/Figure | Script that creates it |
|---|---|---|
| `results/raw/corpus_stats.csv` | T1 | `profile_constructs.py` |
| `results/raw/unit_sizes.csv` | G1 decision | `profile_units.py` |
| `results/raw/robustness.csv` | T2 | `run_corpus.py` |
| `results/raw/throughput.csv` | T3 | `benchmark_throughput.py` |
| `results/raw/naming_metrics.csv` | T4 | `train_eval.py` |
| `results/raw/clone_metrics.csv` | T5 | `train_eval.py` |
| `results/raw/bizrule_metrics.csv` | T6 | `train_eval.py` |
| `results/raw/ablation_deltas.csv` | T7 | `ablation.py` |
| `results/tables/T*.csv` | All tables | `stats.py` |
| `results/figures/*.pdf` | All figures | `stats.py` |
| `results/paper/tab_T*.tex` | LaTeX tables | `stats.py` |
| `results/paper/machine_spec.txt` | Threats §6 | `benchmark_throughput.py` |
| `results/results_log.md` | Audit trail | All scripts (append) |

---

## Troubleshooting

- **Graphviz missing**: PNG tests are skipped automatically. Install Graphviz for full coverage.
- **scipy missing**: Wilcoxon tests show `nan`. Install `scipy`.
- **matplotlib missing**: Figures are skipped. Install `matplotlib`.
- **X-COBOL not found**: Download from https://github.com/RISHA-Lab/X-COBOL
