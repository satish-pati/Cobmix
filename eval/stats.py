r"""
eval/stats.py
-------------
Phase 4 -- Statistical Analysis & Paper-Ready Output Generator

Reads all results/raw/*.csv files, computes:
  - Mean +/- std over 5 seeds per condition per task
  - Paired Wilcoxon signed-rank tests (C5 vs C0, C5 vs C1)
  - Cliff's delta effect sizes
  - Bonferroni correction

Writes:
  results/tables/T1_construct_freq.csv  (from corpus_stats.csv)
  results/tables/T2_robustness.csv
  results/tables/T3_throughput.csv
  results/tables/T4_naming.csv
  results/tables/T5_clones.csv
  results/tables/T6_bizrule.csv
  results/tables/T8_per_project.csv
  results/figures/fig_throughput_pareto.pdf
  results/figures/fig_naming_f1_boxplot.pdf
  results/figures/fig_clone_f1_by_origin.pdf
  results/figures/fig_bizrule_agreement.pdf
  results/figures/fig_ablation_heatmap.pdf
  results/paper/tab_T*.tex  (LaTeX booktabs tables; use \input{tab_T4.tex} in paper)

Usage:
    python eval/stats.py
"""
from __future__ import annotations

import csv
import math
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAW   = Path("results/raw")
TABLE = Path("results/tables")
FIG   = Path("results/figures")
PAPER = Path("results/paper")

for d in [TABLE, FIG, PAPER]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_csv(name: str) -> list[dict]:
    p = RAW / name
    if not p.exists():
        print(f"  [!] Missing: {p} — skipping.")
        return []
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(rows: list[dict], path: Path, fieldnames: list[str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("# no data\n", encoding="utf-8")
        return
    fn = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fn, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _wilcoxon(x: list[float], y: list[float]) -> tuple[float, float]:
    """Wilcoxon signed-rank test. Returns (statistic, p_value).
    Returns (nan, nan) when scipy is unavailable or data is degenerate."""
    try:
        import warnings
        from scipy.stats import wilcoxon as _wilcoxon_scipy
        if len(x) < 2 or len(x) != len(y):
            return float("nan"), float("nan")
        diffs = [xi - yi for xi, yi in zip(x, y)]
        if all(d == 0 for d in diffs):  # identical — test undefined
            return float("nan"), float("nan")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            stat, p = _wilcoxon_scipy(diffs, alternative="greater")
        return float(stat), float(p)
    except ImportError:
        return float("nan"), float("nan")


def _cliffs_delta(x: list[float], y: list[float]) -> tuple[float, str]:
    """Cliff's delta between x and y. Returns (d, magnitude)."""
    if not x or not y:
        return float("nan"), "n/a"
    count = sum(1 if xi > yi else (-1 if xi < yi else 0)
                for xi in x for yi in y)
    d = count / (len(x) * len(y))
    if abs(d) < 0.147:
        mag = "negligible"
    elif abs(d) < 0.33:
        mag = "small"
    elif abs(d) < 0.474:
        mag = "medium"
    else:
        mag = "large"
    return round(d, 4), mag


def _bonferroni(p: float, n_tests: int) -> float:
    return min(1.0, p * n_tests) if not math.isnan(p) else float("nan")


# ---------------------------------------------------------------------------
# T1 — Construct Frequency
# ---------------------------------------------------------------------------

def make_T1():
    rows = _load_csv("corpus_stats.csv")
    if not rows:
        return

    total = len(rows)
    valid = [r for r in rows if not r.get("error")]
    n = len(valid)

    def pct(k):
        count = sum(1 for r in valid if str(r.get(k, "")).lower() == "true")
        return {"count": count, "pct": round(100 * count / n, 1) if n else 0}

    summary = [
        {"construct": "REDEFINES",        **pct("has_redefines")},
        {"construct": "RENAMES (Level 66)",**pct("has_renames")},
        {"construct": "OCCURS",            **pct("has_occurs")},
        {"construct": "PERFORM ... THRU",  **pct("has_perform_thru")},
        {"construct": "File control (SELECT)", **pct("has_file_control")},
        {"construct": "Total programs",    "count": total, "pct": 100.0},
    ]
    _write_csv(summary, TABLE / "T1_construct_freq.csv", ["construct", "count", "pct"])
    _write_latex_T1(summary)
    print(f"  T1 written ({n} programs)")


def _write_latex_T1(summary):
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{COBOL construct frequencies in the X-COBOL corpus (RQ6).}",
        r"\label{tab:constructs}",
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Construct & Programs & \% \\",
        r"\midrule",
    ]
    for row in summary[:-1]:  # skip "Total programs" row
        lines.append(f"  {row['construct']} & {row['count']} & {row['pct']}\\\\")
    lines += [
        r"\midrule",
        f"  Total & {summary[-1]['count']} & 100.0\\\\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    (PAPER / "tab_T1.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# T2 — Robustness
# ---------------------------------------------------------------------------

def make_T2():
    """Read the pre-aggregated robustness summary written by run_corpus.py.

    run_corpus.py already produces a per-metric summary CSV with columns
    metric / count / pct.  We just forward it into the table; we do NOT
    try to re-derive the numbers by treating each row as a per-program row.
    """
    rows = _load_csv("robustness.csv")
    if not rows:
        return

    # Accept the summary as-is; robustness.csv has one row per metric.
    summary = [{"metric": r.get("metric", ""),
                "count":  r.get("count", ""),
                "pct":    r.get("pct", "")} for r in rows]

    _write_csv(summary, TABLE / "T2_robustness.csv", ["metric", "count", "pct"])
    _write_latex_T2(summary)
    print(f"  T2 written")


def _write_latex_T2(summary):
    lines = [
        r"\begin{table}[t]", r"\centering",
        r"\caption{COBMix extractor robustness on the X-COBOL corpus.}",
        r"\label{tab:robustness}",
        r"\begin{tabular}{lrr}", r"\toprule",
        r"Metric & Count & \% \\", r"\midrule",
    ]
    for r in summary:
        lines.append(f"  {r['metric']} & {r['count']} & {r['pct']}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (PAPER / "tab_T2.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# T3 — Throughput
# ---------------------------------------------------------------------------

def make_T3():
    """Read the pre-aggregated throughput CSV written by benchmark_throughput.py.

    benchmark_throughput.py writes: views, median_ms, iqr_ms, n
    We pass these rows straight through to the table rather than trying to
    re-aggregate per-run wall times (which would require wall_time_ms/views_active).
    """
    rows = _load_csv("throughput.csv")
    if not rows:
        return

    # Detect which column layout we have and normalise.
    summary = []
    for r in rows:
        if "views" in r and "median_ms" in r:
            # Pre-aggregated format written by benchmark_throughput.py
            summary.append({
                "views":     r["views"],
                "n":         r.get("n", ""),
                "median_ms": r["median_ms"],
                "iqr_ms":    r.get("iqr_ms", ""),
            })
        elif "views_active" in r and "wall_time_ms" in r:
            # Raw per-run format — accumulate and summarise below.
            pass  # handled in second branch

    if not summary:
        # Fallback: raw per-run rows
        by_cond: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            t = float(r.get("wall_time_ms", -1))
            if t >= 0:
                by_cond[r["views_active"]].append(t)
        for views_str, times in sorted(by_cond.items()):
            qs = statistics.quantiles(times, n=4) if len(times) >= 4 else [0, 0, 0]
            summary.append({
                "views":     views_str,
                "n":         len(times),
                "median_ms": round(statistics.median(times), 1),
                "iqr_ms":    round(qs[2] - qs[0], 1),
            })

    _write_csv(summary, TABLE / "T3_throughput.csv")
    _write_latex_T3(summary)
    _plot_throughput(summary)
    print(f"  T3 written ({len(summary)} conditions)")


def _write_latex_T3(summary):
    lines = [
        r"\begin{table}[t]", r"\centering",
        r"\caption{Extraction throughput per view combination (median $\pm$ IQR ms/program).}",
        r"\label{tab:throughput}",
        r"\begin{tabular}{lrr}", r"\toprule",
        r"Views & Median (ms) & IQR (ms) \\", r"\midrule",
    ]
    for r in summary:
        v = r["views"].split(",")
        label = ",".join(v) if len(v) <= 3 else "Full COBMix"
        lines.append(f"  {label} & {r['median_ms']} & {r['iqr_ms']}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (PAPER / "tab_T3.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plot_throughput(summary):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels  = [",".join(r["views"].split(",")[:2]) + ("…" if "," in r["views"][4:] else "")
                   for r in summary]
        medians = [r["median_ms"] for r in summary]
        iqrs    = [r["iqr_ms"]    for r in summary]

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.barh(labels, medians, xerr=iqrs, capsize=4, color="#4C72B0")
        ax.set_xlabel("Median wall-clock time (ms / program)")
        ax.set_title("COBMix extraction throughput per view combination")
        ax.invert_yaxis()
        fig.tight_layout()
        out = FIG / "fig_throughput_pareto.pdf"
        fig.savefig(out)
        plt.close(fig)
        print(f"  Figure: {out}")
    except Exception as exc:
        print(f"  [!] throughput plot failed: {exc}")


# ---------------------------------------------------------------------------
# T4 — Paragraph Naming
# ---------------------------------------------------------------------------

def make_T4():
    _make_task_table(
        csv_file="naming_metrics.csv",
        metric_col="f1_subword",
        out_table=TABLE / "T4_naming.csv",
        out_tex=PAPER / "tab_T4.tex",
        fig_out=FIG / "fig_naming_f1_boxplot.pdf",
        caption=r"Paragraph naming subword F1 per condition ($\mu \pm \sigma$ over 5 seeds).",
        label="tab:naming",
        task="naming",
    )


# ---------------------------------------------------------------------------
# T5 — Clone Detection
# ---------------------------------------------------------------------------

def make_T5():
    rows = _load_csv("clone_metrics.csv")
    if not rows:
        return

    conditions = sorted({r["condition"] for r in rows})
    origins    = ["all", "copybook", "logic"]
    N_TESTS    = 6  # Bonferroni

    out_rows = []
    for cond in conditions:
        for origin in origins:
            subset = [float(r["f1"]) for r in rows
                      if r["condition"] == cond
                      and r.get("clone_origin", "all") == origin
                      and r.get("split", "") in ("test", "")]
            if not subset:
                continue
            c5_subset = [float(r["f1"]) for r in rows
                         if r["condition"] == "C5"
                         and r.get("clone_origin", "all") == origin
                         and r.get("split", "") in ("test", "")]
            stat, p  = _wilcoxon(c5_subset, subset)
            p_corr   = _bonferroni(p, N_TESTS)
            d, mag   = _cliffs_delta(c5_subset, subset)
            out_rows.append({
                "condition":    cond,
                "clone_origin": origin,
                "f1_mean":      round(statistics.mean(subset), 4),
                "f1_std":       round(statistics.stdev(subset), 4) if len(subset) > 1 else 0,
                "wilcoxon_p":   round(p, 4) if not math.isnan(p) else "n/a",
                "p_bonferroni": round(p_corr, 4) if not math.isnan(p_corr) else "n/a",
                "cliffs_delta": d,
                "effect_mag":   mag,
            })

    _write_csv(out_rows, TABLE / "T5_clones.csv")
    _write_latex_task(out_rows, PAPER / "tab_T5.tex",
                      r"Clone detection F1 by clone origin and condition.",
                      "tab:clones")
    _plot_clone_f1(out_rows)
    print(f"  T5 written")


def _plot_clone_f1(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        conditions = sorted({r["condition"] for r in rows})
        origins    = ["copybook", "logic"]
        x = np.arange(len(conditions))
        width = 0.35

        fig, ax = plt.subplots(figsize=(9, 5))
        for i, origin in enumerate(origins):
            means = [next((r["f1_mean"] for r in rows
                           if r["condition"] == c and r["clone_origin"] == origin), 0)
                     for c in conditions]
            stds  = [next((r["f1_std"] for r in rows
                           if r["condition"] == c and r["clone_origin"] == origin), 0)
                     for c in conditions]
            ax.bar(x + i * width, means, width, yerr=stds, capsize=3,
                   label=f"{origin} clones", alpha=0.85)

        ax.set_xticks(x + width / 2)
        ax.set_xticklabels(conditions, rotation=25, ha="right")
        ax.set_ylabel("F1")
        ax.set_title("Clone Detection F1 by Clone Origin")
        ax.legend()
        ax.set_ylim(0, 1.05)
        fig.tight_layout()
        out = FIG / "fig_clone_f1_by_origin.pdf"
        fig.savefig(out)
        plt.close(fig)
        print(f"  Figure: {out}")
    except Exception as exc:
        print(f"  [!] clone plot failed: {exc}")


# ---------------------------------------------------------------------------
# T6 — Program Classification
# ---------------------------------------------------------------------------

def make_T6():
    csv_file = "classification_metrics.csv" if (RAW / "classification_metrics.csv").exists() else "bizrule_metrics.csv"
    metric_col = "accuracy" if csv_file == "classification_metrics.csv" else "agreement_f1"
    caption = r"Program classification accuracy per condition ($\mu \pm \sigma$ over 5 seeds)."
    label = "tab:classification"
    task = "classification"
    _make_task_table(
        csv_file=csv_file,
        metric_col=metric_col,
        out_table=TABLE / "T6_classification.csv",
        out_tex=PAPER / "tab_T6.tex",
        fig_out=FIG / "fig_classification_accuracy.pdf",
        caption=caption,
        label=label,
        task=task,
    )
    import shutil
    if (TABLE / "T6_classification.csv").exists():
        shutil.copy(TABLE / "T6_classification.csv", TABLE / "T6_bizrule.csv")


# ---------------------------------------------------------------------------
# T8 — Per-Project Results
# ---------------------------------------------------------------------------

def make_T8():
    for task, csv_file, metric_col in [
        ("naming",         "naming_metrics.csv",         "f1_subword"),
        ("clone",          "clone_metrics.csv",          "f1"),
        ("classification", "classification_metrics.csv", "accuracy"),
        ("bizrule",        "bizrule_metrics.csv",        "agreement_f1"),
    ]:
        rows = _load_csv(csv_file)
        if not rows:
            continue
        by_proj: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            proj = r.get("project", r.get("program_path", "unknown"))
            try:
                by_proj[proj].append(float(r[metric_col]))
            except (KeyError, ValueError):
                pass
        proj_rows = [
            {"project": proj, "task": task,
             "f1_mean": round(statistics.mean(vals), 4),
             "f1_std":  round(statistics.stdev(vals), 4) if len(vals) > 1 else 0,
             "n_units": len(vals)}
            for proj, vals in sorted(by_proj.items())
        ]
        _write_csv(proj_rows, TABLE / "T8_per_project.csv",
                   ["project", "task", "f1_mean", "f1_std", "n_units"])
    print(f"  T8 written")


# ---------------------------------------------------------------------------
# Generic task table helper
# ---------------------------------------------------------------------------

CONDITIONS_ORDER = ["C0", "C1", "C2", "C3", "C4", "C5",
                    "C5_no_overlay", "C5_no_copybook", "C5_no_division"]
N_TESTS = 6  # Bonferroni: 3 tasks × 2 comparisons


def _make_task_table(csv_file, metric_col, out_table, out_tex, fig_out,
                     caption, label, task):
    rows = _load_csv(csv_file)
    if not rows:
        return

    conditions = sorted(
        {r["condition"] for r in rows},
        key=lambda c: CONDITIONS_ORDER.index(c) if c in CONDITIONS_ORDER else 99,
    )
    c5_vals = [float(r[metric_col]) for r in rows
               if r.get("condition") == "C5" and r.get("split", "") in ("test", "")]

    out_rows = []
    for cond in conditions:
        subset = [float(r[metric_col]) for r in rows
                  if r["condition"] == cond and r.get("split", "") in ("test", "")]
        if not subset:
            continue
        stat, p  = _wilcoxon(c5_vals, subset) if cond != "C5" else (float("nan"), float("nan"))
        p_corr   = _bonferroni(p, N_TESTS)
        d, mag   = _cliffs_delta(c5_vals, subset) if cond != "C5" else (float("nan"), "—")
        out_rows.append({
            "condition":    cond,
            "mean":         round(statistics.mean(subset), 4),
            "std":          round(statistics.stdev(subset), 4) if len(subset) > 1 else 0,
            "n_seeds":      len(subset),
            "wilcoxon_p":   round(p, 4)      if not math.isnan(p)      else "—",
            "p_bonferroni": round(p_corr, 4) if not math.isnan(p_corr) else "—",
            "cliffs_delta": d                 if not math.isnan(d)      else "—",
            "effect_mag":   mag,
        })

    _write_csv(out_rows, out_table)
    _write_latex_task(out_rows, out_tex, caption, label)
    _plot_boxplot(rows, metric_col, conditions, fig_out, task)
    print(f"  {out_table.name} written")


def _write_latex_task(out_rows, out_tex: Path, caption: str, label: str):
    lines = [
        r"\begin{table}[t]", r"\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        r"\begin{tabular}{lrrrrr}", r"\toprule",
        r"Condition & $\mu$ & $\sigma$ & $p$ (Bonf.) & $d$ & Effect \\",
        r"\midrule",
    ]
    for r in out_rows:
        # Support both 'mean'/'std' (task tables) and 'f1_mean'/'f1_std' (clone table)
        mean_val = r.get("mean", r.get("f1_mean", "—"))
        std_val  = r.get("std",  r.get("f1_std",  "—"))
        # Add clone_origin column when present
        extra = f"{r['clone_origin']} & " if "clone_origin" in r else ""
        cond_escaped = str(r.get('condition', '?')).replace('_', r'\_')
        lines.append(
            f"  {extra}{cond_escaped} & {mean_val} & {std_val} & "
            f"{r.get('p_bonferroni', '—')} & {r.get('cliffs_delta', '—')} & "
            f"{r.get('effect_mag', '—')}\\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    out_tex.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plot_boxplot(rows, metric_col, conditions, fig_out, title):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        data = []
        labels = []
        for cond in conditions:
            vals = [float(r[metric_col]) for r in rows
                    if r["condition"] == cond and r.get("split", "") in ("test", "")]
            if vals:
                data.append(vals)
                labels.append(cond)

        fig, ax = plt.subplots(figsize=(9, 5))
        bp = ax.boxplot(data, tick_labels=labels, patch_artist=True)
        for patch in bp["boxes"]:
            patch.set_facecolor("#4C72B0")
            patch.set_alpha(0.7)
        ax.set_ylabel(metric_col)
        ax.set_title(f"{title.capitalize()} — {metric_col} across conditions")
        ax.set_ylim(0, 1.05)
        fig.tight_layout()
        fig.savefig(fig_out)
        plt.close(fig)
        print(f"  Figure: {fig_out}")
    except Exception as exc:
        print(f"  [!] boxplot failed ({fig_out.name}): {exc}")


def _plot_ablation_heatmap(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        views = sorted({r["view_removed"] for r in rows})
        tasks = sorted({r["task"]         for r in rows})

        data = np.zeros((len(views), len(tasks)))
        for r in rows:
            if r.get("delta_f1_mean") not in (None, ""):
                i = views.index(r["view_removed"])
                j = tasks.index(r["task"])
                data[i, j] = float(r["delta_f1_mean"])

        fig, ax = plt.subplots(figsize=(6, 4))
        im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-0.05, vmax=0.15)
        ax.set_xticks(range(len(tasks)))
        ax.set_yticks(range(len(views)))
        ax.set_xticklabels(tasks)
        ax.set_yticklabels(views)
        ax.set_title(r"$\Delta$ F1 when view removed from Full COBMix")
        plt.colorbar(im, ax=ax, label="delta F1")
        for i in range(len(views)):
            for j in range(len(tasks)):
                ax.text(j, i, f"{data[i,j]:.3f}", ha="center", va="center", fontsize=8)
        fig.tight_layout()
        out = FIG / "fig_ablation_heatmap.pdf"
        fig.savefig(out)
        plt.close(fig)
        print(f"  Figure: {out}")
    except Exception as exc:
        print(f"  [!] ablation heatmap failed: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=== COBMix Statistical Analysis ===\n")
    make_T1()
    make_T2()
    make_T3()
    make_T4()
    make_T5()
    make_T6()
    make_T8()

    # Ablation heatmap (reads from raw/ablation_deltas.csv produced by ablation.py)
    abl_rows = _load_csv("ablation_deltas.csv")
    if abl_rows:
        _plot_ablation_heatmap(abl_rows)
        _make_T7(abl_rows)

    print("\n=== Done ===")
    print(f"  Tables  : {TABLE}")
    print(f"  Figures : {FIG}")
    print(f"  LaTeX   : {PAPER}")

def _make_T7(abl_rows):
    out_tex = PAPER / "tab_T7.tex"
    lines = [
        r"\begin{table}[t]", r"\centering",
        r"\caption{Ablation results: $\Delta$ F1 when removing views from C5.}",
        r"\label{tab:ablation}",
        r"\begin{tabular}{llrrrl}", r"\toprule",
        r"View Removed & Task & $\Delta$ F1 & $\sigma$ & Threshold & Earns \\",
        r"\midrule",
    ]
    for r in abl_rows:
        view = r.get("view_removed", "").replace("_", r"\_")
        lines.append(f"  {view} & {r['task']} & {r['delta_f1_mean']} & {r['delta_f1_std']} & {r['threshold_2std']} & {r['earns_place']} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    out_tex.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  tab_T7.tex written")

    _log()
    return 0


def _log():
    log = Path("results/results_log.md")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    entry = (
        f"\n## Run: {ts} — stats.py\n"
        f"- **Git commit:** `{git_sha}`\n"
        f"- **Input:** results/raw/*.csv\n"
        f"- **Output files:** results/tables/T*.csv, results/figures/*.pdf, results/paper/tab_T*.tex\n"
        f"- **Notes:** \n"
    )
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(entry)


if __name__ == "__main__":
    raise SystemExit(main())
