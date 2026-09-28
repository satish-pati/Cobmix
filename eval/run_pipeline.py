"""
eval/run_pipeline.py
--------------------
Single-process build + evaluate pipeline.

Builds all three datasets IN MEMORY and immediately evaluates them,
bypassing OneDrive file eviction. The only files written are the small
results/raw/*.csv outputs which are never evicted.

Usage:
    python eval/run_pipeline.py --corpus-dir COBOL_Files/COBOL_Files
    python eval/run_pipeline.py --corpus-dir COBOL_Files/COBOL_Files --seeds 3 --tasks naming
"""
from __future__ import annotations

import argparse
import csv

import json
import math
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import torch
import torch.nn as nn
import torch.optim as optim

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cobmix import CombinedDriver  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_BYTES = 50 * 1024          # 300 KB — skip outlier files
MIN_STMTS     = 3                    # paragraph body gate
VIEWS_NAMING  = ["ast", "cfg", "dfg", "overlay", "copybook", "division"]
ALL_VIEWS     = ["ast", "cfg", "dfg", "overlay", "copybook", "division"]

CONDITIONS: dict[str, list[str]] = {
    "C0": [],
    "C1": ["ast", "cfg", "dfg"],
    "C2": ["ast", "cfg", "dfg", "overlay"],
    "C3": ["ast", "cfg", "dfg", "copybook"],
    "C4": ["ast", "cfg", "dfg", "division"],
    "C5": ALL_VIEWS,
    "C5_no_overlay":  [v for v in ALL_VIEWS if v != "overlay"],
    "C5_no_copybook": [v for v in ALL_VIEWS if v != "copybook"],
    "C5_no_division": [v for v in ALL_VIEWS if v != "division"],
}

SEEDS      = [42, 123, 456, 789, 1337]
MAX_PATH_LEN  = 8
MAX_PATHS     = 200
EMBED_DIM     = 64
HIDDEN_DIM    = 128
LEARNING_RATE = 1e-3
EPOCHS        = 20
BATCH_SIZE    = 32

# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _graph_paths(g, max_len=MAX_PATH_LEN, max_paths=MAX_PATHS, rng=None):
    if g is None or g.number_of_nodes() == 0:
        return []
    import networkx as nx  # noqa: F401
    rng = rng or random.Random(42)
    nodes  = list(g.nodes())
    paths  = []
    attempts = 0
    while len(paths) < max_paths and attempts < max_paths * 5:
        attempts += 1
        src  = rng.choice(nodes)
        path = [src]; cur = src
        for _ in range(max_len - 1):
            nbrs = list(g.successors(cur)) + list(g.predecessors(cur))
            if not nbrs: break
            nxt = rng.choice(nbrs)
            if nxt in path: break
            path.append(nxt); cur = nxt
        if len(path) >= 2:
            st = g.nodes[path[0]].get("type", "?")
            et = g.nodes[path[-1]].get("type", "?")
            es = tuple(g.nodes[n].get("type", "?") for n in path[1:-1])
            paths.append((st, es, et))
    return paths


def _encode_unit(unit, views, rng):
    all_paths = []
    graphs = unit.get("graphs", {})
    for vname in views:
        g = graphs.get(vname)
        if g is None: continue
        all_paths.extend(_graph_paths(g, rng=rng))
    if not views:
        prog_path = unit.get("program", "")
        stem = Path(prog_path).stem if prog_path else "unknown"
        tokens = [t for t in re.split(r"[-_. ]+", stem.upper()) if t]
        for t in tokens or ["UNKNOWN"]:
            all_paths.append(("token", (), t))
    return all_paths[:MAX_PATHS]


def _build_vocab(units, views):
    vocab = {"<PAD>": 0, "<UNK>": 1}
    for unit in units:
        for vname in views:
            g = unit.get("graphs", {}).get(vname, {})
            for n in g.get("nodes", []):
                t = n.get("type", "?")
                if t not in vocab: vocab[t] = len(vocab)
    return vocab

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class PathAttentionModel(nn.Module):
    def __init__(self, vocab_size, embed_dim=EMBED_DIM, hidden_dim=HIDDEN_DIM, seed=42):
        super().__init__()
        torch.manual_seed(seed)
        self.node_embed = nn.Embedding(vocab_size, embed_dim)
        self.attn_w    = nn.Linear(embed_dim, 1, bias=False)
        self.fc        = nn.Linear(embed_dim, hidden_dim)

    def _tok(self, t, vocab):
        return vocab.get(t, vocab.get("<UNK>", 0))

    def encode(self, paths, vocab):
        if not paths:
            return torch.zeros(self.fc.out_features)
        starts = torch.tensor([self._tok(p[0], vocab) for p in paths], dtype=torch.long)
        ends   = torch.tensor([self._tok(p[2], vocab) for p in paths], dtype=torch.long)
        v      = (self.node_embed(starts) + self.node_embed(ends)) / 2.0
        w      = torch.softmax(self.attn_w(v), dim=0)
        ctx    = torch.sum(w * v, dim=0)
        return torch.tanh(self.fc(ctx))

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _subword_f1(pred, gold):
    ps, gs = set(pred), set(gold)
    if not ps or not gs: return 0.0, 0.0, 0.0
    tp = len(ps & gs)
    p  = tp / len(ps); r = tp / len(gs)
    f1 = 2*p*r/(p+r) if (p+r) > 0 else 0.0
    return p, r, f1


def _binary_f1(preds, labels):
    tp = sum(1 for p,l in zip(preds,labels) if p==1 and l==1)
    fp = sum(1 for p,l in zip(preds,labels) if p==1 and l==0)
    fn = sum(1 for p,l in zip(preds,labels) if p==0 and l==1)
    pr = tp/(tp+fp) if (tp+fp) > 0 else 0.0
    rc = tp/(tp+fn) if (tp+fn) > 0 else 0.0
    f1 = 2*pr*rc/(pr+rc) if (pr+rc) > 0 else 0.0
    return pr, rc, f1

# ---------------------------------------------------------------------------
# Dataset builders (return data directly, never touch disk)
# ---------------------------------------------------------------------------

def _subwords(name):
    parts = re.split(r"[-_]+", name.lower())
    return [p for p in parts if p]





def build_naming(corpus_dir, copy_paths=None):
    """Build naming dataset in memory."""
    copy_paths = copy_paths or []
    exts  = {".cbl", ".cob", ".cpy", ".cobol"}
    files = sorted(p for p in Path(corpus_dir).rglob("*") if p.suffix.lower() in exts)
    print(f"  [naming] Scanning {len(files)} files …")

    all_units = []
    for i, f in enumerate(files, 1):
        if f.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            driver = CombinedDriver(src_code=src, code_file=f,
                                    copy_paths=copy_paths, graphs=VIEWS_NAMING)
            cfg = driver.views.get("cfg")
            if not cfg: continue
            para_nodes = [n for n, _ in cfg.nodes(data=True) if str(n).startswith("para:")]
            para_set   = set(para_nodes)
            for pn in para_nodes:
                pname = str(pn).removeprefix("para:")
                if not pname or pname.startswith("_"): continue
                visited, queue, stmts = set(), [pn], []
                while queue:
                    cur = queue.pop()
                    for _, nxt in cfg.out_edges(cur):
                        if nxt in visited: continue
                        visited.add(nxt)
                        if str(nxt).startswith("stmt:"):
                            stmts.append(nxt); queue.append(nxt)
                if len(stmts) < MIN_STMTS: continue
                views_json = {}
                for vname in VIEWS_NAMING:
                    g = driver.views.get(vname)
                    if not g:
                        continue
                    # Serialise directly while masking the para name — no deepcopy needed.
                    name_up = pname.upper()
                    def _mask(v):
                        if isinstance(v, str):
                            return v.upper().replace(name_up, "<PARA>") if name_up in v.upper() else v
                        return v
                    views_json[vname] = {
                        "nodes": [{"id": n, **{k: _mask(val) for k, val in d.items()}}
                                  for n, d in g.nodes(data=True)],
                        "edges": [{"src": u, "dst": v, **{k: _mask(val) for k, val in d.items()}}
                                  for u, v, d in g.edges(data=True)],
                    }
                all_units.append({
                    "program": str(f),
                    "paragraph": pname,
                    "label_subwords": _subwords(pname),
                    "graphs": views_json,
                })
        except Exception:
            pass
        if i % 50 == 0:
            print(f"  [naming] {i}/{len(files)} — {len(all_units)} units", flush=True)

    print(f"  [naming] Total units: {len(all_units)}")
    rng = random.Random(42)
    programs = list({u["program"] for u in all_units})
    rng.shuffle(programs)
    n = len(programs)
    n_train = int(n * 0.8); n_val = int(n * 0.1)
    train_progs = set(programs[:n_train])
    val_progs   = set(programs[n_train:n_train+n_val])
    train = [u for u in all_units if u["program"] in train_progs]
    val   = [u for u in all_units if u["program"] in val_progs]
    test  = [u for u in all_units if u["program"] not in train_progs and u["program"] not in val_progs]
    print(f"  [naming] train={len(train)} val={len(val)} test={len(test)}")
    return train, val, test


def build_clones(corpus_dir, copy_paths=None):
    """Build clone pairs in memory."""
    copy_paths = copy_paths or []
    exts    = {".cbl", ".cob"}
    files   = sorted(p for p in Path(corpus_dir).rglob("*") if p.suffix.lower() in exts)
    print(f"  [clone] Scanning {len(files)} files …")

    programs = []
    for i, f in enumerate(files, 1):
        if f.stat().st_size > MAX_FILE_BYTES: continue
        try:
            src    = f.read_text(encoding="utf-8", errors="replace")
            driver = CombinedDriver(src_code=src, code_file=f,
                                    copy_paths=copy_paths, graphs=["cfg", "copybook"])
            cfg    = driver.views.get("cfg")
            cb_g   = driver.views.get("copybook")
            cbs    = set()
            if cb_g:
                for n, d in cb_g.nodes(data=True):
                    if d.get("type") == "copybook":
                        cbs.add(str(n))
            cfg_bag = {}
            if cfg:
                for n, d in cfg.nodes(data=True):
                    t = d.get("type", "?")
                    cfg_bag[t] = cfg_bag.get(t, 0) + 1
            programs.append({"path": str(f), "copybooks": cbs, "cfg_bag": cfg_bag})
        except Exception:
            pass
        if i % 200 == 0:
            print(f"  [clone] {i}/{len(files)}", flush=True)

    print(f"  [clone] Loaded {len(programs)} programs. Building pairs …")
    by_cb: dict[str, list[int]] = {}
    for idx, p in enumerate(programs):
        for cb in p["copybooks"]:
            by_cb.setdefault(cb, []).append(idx)

    positive = []
    for cb, idxs in by_cb.items():
        if len(idxs) < 2: continue
        for i in range(len(idxs)):
            for j in range(i+1, len(idxs)):
                a, b = programs[idxs[i]], programs[idxs[j]]
                positive.append({"program_a": a["path"], "program_b": b["path"],
                                 "label": 1, "origin": "copybook", "shared_copybook": cb})

    def _jac(a, b):
        keys = set(a) | set(b)
        if not keys: return 0.0
        inter = sum(min(a.get(k,0), b.get(k,0)) for k in keys)
        union = sum(max(a.get(k,0), b.get(k,0)) for k in keys)
        return inter / union if union else 0.0

    pos_set = {(p["program_a"], p["program_b"]) for p in positive}
    rng     = random.Random(42)
    all_idx = list(range(len(programs)))
    n_neg   = int(len(positive) * 2.0)
    negative = []
    attempts = 0
    while len(negative) < n_neg and attempts < n_neg * 10:
        i, j = rng.sample(all_idx, 2)
        a, b = programs[i], programs[j]
        key  = (a["path"], b["path"])
        if key not in pos_set and (b["path"], a["path"]) not in pos_set:
            negative.append({"program_a": a["path"], "program_b": b["path"],
                             "label": 0, "origin": None})
            pos_set.add(key)
        attempts += 1

    pairs = positive + negative
    rng.shuffle(pairs)
    print(f"  [clone] pos={len(positive)} neg={len(negative)} total={len(pairs)}")
    return pairs


def build_classification(corpus_dir, copy_paths=None):
    """Build classification dataset in memory."""
    copy_paths = copy_paths or []
    exts  = {".cbl", ".cob"}
    from pathlib import Path
    corpus = Path(corpus_dir)
    files = sorted(p for p in corpus.rglob("*") if p.suffix.lower() in exts)
    print(f"  [classification] Scanning {len(files)} files …")

    all_units = []
    for i, f in enumerate(files, 1):
        if f.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            driver = CombinedDriver(src_code=src, code_file=f,
                                    copy_paths=copy_paths, graphs=VIEWS_NAMING)
            graphs = {}
            for v in VIEWS_NAMING:
                g = driver.views.get(v)
                if g:
                    from networkx.readwrite import json_graph
                    graphs[v] = json_graph.node_link_data(g)
            if graphs:
                rel_path = f.relative_to(corpus)
                label = rel_path.parts[0] if len(rel_path.parts) > 0 else "unknown"
                all_units.append({
                    "program": str(f),
                    "label": label,
                    "graphs": graphs
                })
        except Exception:
            pass
        if i % 200 == 0:
            print(f"  [classification] {i}/{len(files)}", flush=True)

    print(f"  [classification] Total valid programs={len(all_units)}")
    
    rng = random.Random(42)
    rng.shuffle(all_units)
    n = len(all_units)
    n_train = int(n * 0.7)
    n_val = int(n * 0.15)
    
    train = all_units[:n_train]
    val = all_units[n_train:n_train+n_val]
    test = all_units[n_train+n_val:]
    
    return train, val, test


def eval_naming(condition, views, seed, train, val, test, out_path):
    rng        = random.Random(seed)
    vocab      = _build_vocab(train + val + test, views)
    all_labels = [sw for u in train for sw in u.get("label_subwords", [])]
    label_vocab = {t: i for i, t in enumerate(sorted(set(all_labels)))}
    if not label_vocab:
        return {"condition": condition, "seed": seed, "f1_subword": 0.0}

    model      = PathAttentionModel(len(vocab), seed=seed)
    classifier = nn.Linear(HIDDEN_DIM, len(label_vocab))
    optimizer  = optim.Adam(list(model.parameters()) + list(classifier.parameters()), lr=LEARNING_RATE)
    criterion  = nn.BCEWithLogitsLoss()

    train_paths = [(u, _encode_unit(u, views, rng)) for u in train]
    model.train(); classifier.train()
    for _ in range(EPOCHS):
        rng.shuffle(train_paths)
        for i in range(0, len(train_paths), BATCH_SIZE):
            batch = train_paths[i:i+BATCH_SIZE]
            embs, golds = [], []
            for u, paths in batch:
                if not paths: continue
                embs.append(model.encode(paths, vocab))
                gv = torch.zeros(len(label_vocab))
                for lbl in u.get("label_subwords", []):
                    if lbl in label_vocab: gv[label_vocab[lbl]] = 1.0
                golds.append(gv)
            if not embs: continue
            logits = classifier(torch.stack(embs))
            loss   = criterion(logits, torch.stack(golds))
            optimizer.zero_grad(); loss.backward(); optimizer.step()

    model.eval(); classifier.eval()
    inv_label = {v: k for k, v in label_vocab.items()}
    test_paths = [(u, _encode_unit(u, views, rng)) for u in test]
    f1s = []
    with torch.no_grad():
        for u, paths in test_paths:
            emb    = model.encode(paths, vocab)
            logits = classifier(emb)
            probs  = torch.sigmoid(logits)
            pred   = [inv_label[i] for i, p in enumerate(probs) if p > 0.5]
            if not pred:
                top_idx = torch.topk(logits, k=min(2, len(logits))).indices.tolist()
                pred    = [inv_label[idx] for idx in top_idx]
            gold = u.get("label_subwords", [])
            _, _, f1 = _subword_f1(pred, gold)
            f1s.append(f1)

    avg_f1 = round(sum(f1s) / max(len(f1s), 1), 4)
    row = {"condition": condition, "seed": seed, "split": "test", "f1_subword": avg_f1,
           "run_timestamp": datetime.now(timezone.utc).isoformat()}
    _append_csv(row, out_path,
                ["condition", "seed", "split", "f1_subword", "run_timestamp"])
    return row


def eval_clone(condition, views, seed, pairs, out_path):
    rng = random.Random(seed)
    # build simple graph-representation units from pairs
    units = [{"program": p["program_a"], "graphs": {}} for p in pairs]
    vocab = _build_vocab(units, views)

    model      = PathAttentionModel(len(vocab) or 2, seed=seed)
    classifier = nn.Linear(HIDDEN_DIM, 1)
    optimizer  = optim.Adam(list(model.parameters()) + list(classifier.parameters()), lr=LEARNING_RATE)
    criterion  = nn.BCEWithLogitsLoss()

    n_train = int(len(pairs) * 0.8)
    rng.shuffle(pairs)
    train_p = pairs[:n_train]; test_p = pairs[n_train:]

    model.train(); classifier.train()
    for _ in range(EPOCHS):
        rng.shuffle(train_p)
        for i in range(0, len(train_p), BATCH_SIZE):
            batch = train_p[i:i+BATCH_SIZE]
            embs, golds = [], []
            for p in batch:
                ua = {"program": p["program_a"], "graphs": {}}
                ub = {"program": p["program_b"], "graphs": {}}
                pa = _encode_unit(ua, views, rng)
                pb = _encode_unit(ub, views, rng)
                if not pa and not pb: continue
                ea = model.encode(pa, vocab)
                eb = model.encode(pb, vocab)
                embs.append(ea - eb)
                golds.append(torch.tensor([float(p["label"])]))
            if not embs: continue
            logits = classifier(torch.stack(embs)).squeeze(-1)
            loss   = criterion(logits, torch.cat(golds))
            optimizer.zero_grad(); loss.backward(); optimizer.step()

    model.eval(); classifier.eval()
    preds, labels = [], []
    with torch.no_grad():
        for p in test_p:
            ua = {"program": p["program_a"], "graphs": {}}
            ub = {"program": p["program_b"], "graphs": {}}
            ea = model.encode(_encode_unit(ua, views, rng), vocab)
            eb = model.encode(_encode_unit(ub, views, rng), vocab)
            logit  = classifier(ea - eb).item()
            preds.append(1 if logit > 0 else 0)
            labels.append(p["label"])

    pr, rc, f1 = _binary_f1(preds, labels)
    row = {"condition": condition, "seed": seed, "split": "test",
           "clone_origin": "all", "f1": round(f1, 4),
           "precision": round(pr, 4), "recall": round(rc, 4),
           "run_timestamp": datetime.now(timezone.utc).isoformat()}
    _append_csv(row, out_path,
                ["condition", "seed", "split", "clone_origin", "f1", "precision", "recall", "run_timestamp"])
    return row


def eval_classification(condition, views, seed, train, val, test, out_path):
    rng = random.Random(seed)
    
    # Simple vocab builder for classification
    vocab = {"<PAD>": 0, "<UNK>": 1}
    for unit in train + val + test:
        for vname in views:
            g = unit.get("graphs", {}).get(vname, {})
            for n in g.get("nodes", []):
                t = n.get("type", "?")
                if t not in vocab: vocab[t] = len(vocab)

    labels = sorted(list(set(u["label"] for u in train)))
    label_vocab = {t: i for i, t in enumerate(labels)}
    
    if not label_vocab:
        return {"condition": condition, "seed": seed, "accuracy": 0.0}

    model = PathAttentionModel(len(vocab), seed=seed)
    classifier = nn.Linear(HIDDEN_DIM, len(label_vocab))
    optimizer = optim.Adam(list(model.parameters()) + list(classifier.parameters()), lr=LEARNING_RATE)
    criterion = nn.CrossEntropyLoss()

    train_paths = [(u, _encode_unit(u, views, rng)) for u in train]
    model.train(); classifier.train()
    
    for _ in range(EPOCHS):
        rng.shuffle(train_paths)
        for i in range(0, len(train_paths), BATCH_SIZE):
            batch = train_paths[i:i+BATCH_SIZE]
            embs, golds = [], []
            for u, paths in batch:
                if not paths: continue
                embs.append(model.encode(paths, vocab))
                golds.append(label_vocab[u["label"]])
            if not embs: continue
            logits = classifier(torch.stack(embs))
            loss = criterion(logits, torch.tensor(golds))
            optimizer.zero_grad(); loss.backward(); optimizer.step()

    model.eval(); classifier.eval()
    test_paths = [(u, _encode_unit(u, views, rng)) for u in test]
    
    correct = 0
    total = 0
    with torch.no_grad():
        for u, paths in test_paths:
            if not paths: continue
            emb = model.encode(paths, vocab)
            logits = classifier(emb)
            pred = torch.argmax(logits).item()
            if pred == label_vocab[u["label"]]:
                correct += 1
            total += 1

    acc = correct / max(total, 1)
    
    row = {"condition": condition, "seed": seed, "split": "test", "accuracy": acc,
           "run_timestamp": datetime.now(timezone.utc).isoformat()}
    _append_csv(row, out_path, ["condition", "seed", "split", "accuracy", "run_timestamp"])
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description="COBMix end-to-end pipeline (in-memory).")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[])
    parser.add_argument("--tasks", default="naming,clone,classification",
                        help="Comma-separated subset of: naming,clone,classification")
    parser.add_argument("--conditions", default="all")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    corpus   = args.corpus_dir
    cps      = args.copy_paths
    tasks    = [t.strip() for t in args.tasks.split(",")]
    conds    = list(CONDITIONS.keys()) if args.conditions == "all" \
               else [c.strip() for c in args.conditions.split(",")]
    seeds    = SEEDS[:args.seeds]
    raw_dir  = Path("results/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()

    # ---- NAMING ----
    if "naming" in tasks:
        out = raw_dir / "naming_metrics.csv"
        if args.overwrite and out.exists():
            out.unlink(); print("Deleted existing", out)
        print("\n=== Building naming dataset ===")
        train, val, test = build_naming(corpus, cps)
        print(f"\n=== Evaluating naming ({len(conds)} conditions × {len(seeds)} seeds) ===")
        for cond in conds:
            views = CONDITIONS[cond]
            for seed in seeds:
                print(f"  [{cond}] seed={seed} views={views or ['(token-bag)']}", flush=True)
                r = eval_naming(cond, views, seed, train, val, test, out)
                print(f"    F1={r['f1_subword']:.4f}")

    # ---- CLONE ----
    if "clone" in tasks:
        out = raw_dir / "clone_metrics.csv"
        if args.overwrite and out.exists():
            out.unlink(); print("Deleted existing", out)
        print("\n=== Building clone dataset ===")
        pairs = build_clones(corpus, cps)
        print(f"\n=== Evaluating clone ({len(conds)} conditions × {len(seeds)} seeds) ===")
        for cond in conds:
            views = CONDITIONS[cond]
            for seed in seeds:
                print(f"  [{cond}] seed={seed}", flush=True)
                r = eval_clone(cond, views, seed, pairs, out)
                print(f"    F1={r['f1']:.4f}")

    # ---- CLASSIFICATION ----
    if "classification" in tasks:
        out = raw_dir / "classification_metrics.csv"
        if args.overwrite and out.exists():
            out.unlink(); print("Deleted existing", out)
        print("\n=== Building classification dataset ===")
        train, val, test = build_classification(corpus, cps)
        print(f"\n=== Evaluating classification ({len(conds)} conditions x {len(seeds)} seeds) ===")
        for cond in conds:
            views = CONDITIONS[cond]
            for seed in seeds:
                print(f"  [{cond}] seed={seed}", flush=True)
                r = eval_classification(cond, views, seed, train, val, test, out)
                print(f"    Accuracy={r['accuracy']:.4f}")

if __name__ == "__main__":
    raise SystemExit(main())
