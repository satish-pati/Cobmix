from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import networkx as nx

CFG_EDGE_TYPES = {"next", "true", "false", "perform", "thru", "goto", "call", "return"}
DFG_EDGE_TYPES = {"reaches", "def", "use"}
AST_EDGE_TYPES = {"ast"}
OVERLAY_EDGE_TYPES = {"contains", "redefines", "occurs", "renames"}
COPY_EDGE_TYPES = {"includes", "declares"}
DIVISION_EDGE_TYPES = {"in_division"}

EDGE_STYLE = {
    **{t: ("#d62728", "solid", "CFG") for t in CFG_EDGE_TYPES},
    "return": ("#8b0000", "dashed", "CFG"),  # dark-red dashed = PERFORM return
    **{t: ("#1f77b4", "dashed", "DFG") for t in DFG_EDGE_TYPES},
    "def": ("#d62728", "solid", "DFG"),
    "use": ("#2ca02c", "solid", "DFG"),
    "reaches": ("#1f77b4", "dashed", "DFG"),
    **{t: ("#7f7f7f", "dotted", "AST") for t in AST_EDGE_TYPES},
    **{t: ("#ff7f0e", "solid", "overlay") for t in OVERLAY_EDGE_TYPES},
    **{t: ("#2ca02c", "solid", "copybook") for t in COPY_EDGE_TYPES},
    **{t: ("#9467bd", "dashed", "division") for t in DIVISION_EDGE_TYPES},
}

NODE_FILL = {
    "paragraph": "#f4cccc",
    "program": "#cfe2f3",
    "copybook": "#d9ead3",
    "data_name": "#fff2cc",
    "division": "#e6e6e6",
    "if_statement": "#fce5cd",
    "perform_statement": "#d0e2f3",
    "goto_statement": "#ead1dc",
    "stop_statement": "#d5a6bd",
    "call_statement": "#d0e2f3",
}


def new_graph(view: str) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.graph["view"] = view
    return g


def add_node(g: nx.DiGraph, nid: str, **attrs) -> None:
    if nid in g:
        g.nodes[nid].update({k: v for k, v in attrs.items() if v is not None})
    else:
        g.add_node(nid, **{k: v for k, v in attrs.items() if v is not None})


def add_edge(g: nx.DiGraph, src: str, dst: str, etype: str, **attrs) -> None:
    g.add_edge(src, dst, type=etype, **attrs)


def merge_graphs(graphs: list[nx.DiGraph]) -> nx.MultiDiGraph:
    merged = nx.MultiDiGraph()
    merged.graph["view"] = "combined"
    merged.graph["views"] = [g.graph.get("view") for g in graphs]
    for g in graphs:
        view = g.graph.get("view")
        for nid, attrs in g.nodes(data=True):
            payload = dict(attrs)
            payload.setdefault("views", [])
            if nid in merged:
                existing = merged.nodes[nid]
                views = list(existing.get("views", []))
                if view and view not in views:
                    views.append(view)
                existing.update({k: v for k, v in payload.items() if k != "views"})
                existing["views"] = views
            else:
                payload["views"] = [view] if view else []
                merged.add_node(nid, **payload)
        for u, v, attrs in g.edges(data=True):
            data = dict(attrs)
            data.setdefault("view", view)
            merged.add_edge(u, v, **data)
    return merged


def graph_to_json(g: nx.DiGraph) -> dict:
    return {
        "directed": True,
        "multigraph": True,
        "view": g.graph.get("view"),
        "views": g.graph.get("views"),
        "nodes": [{"id": n, **_json_safe(attrs)} for n, attrs in g.nodes(data=True)],
        "edges": [
            {"source": u, "target": v, **_json_safe(attrs)}
            for u, v, attrs in g.edges(data=True)
        ],
    }


def _json_safe(attrs: dict) -> dict:
    out = {}
    for key, value in attrs.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = [str(x) for x in value]
        else:
            out[key] = str(value)
    return out


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _wrap_label(text: str, width: int = 36) -> str:
    text = " ".join(str(text).split())
    if len(text) <= width:
        return text
    parts: list[str] = []
    rest = text
    while rest:
        parts.append(rest[:width])
        rest = rest[width:]
        if len(parts) >= 4:
            if rest:
                parts[-1] = parts[-1][: max(0, width - 3)] + "..."
            break
    return "\n".join(parts)


def _node_label(nid: str, attrs: dict) -> str:
    ntype = str(attrs.get("type") or "")
    text = attrs.get("text")
    name = attrs.get("label") or attrs.get("name") or nid
    if ntype.endswith("_statement") and text:
        return f"{name}\n{_wrap_label(text)}"
    if ntype == "paragraph":
        return f"{name}"
    if ntype == "data_name":
        pic = attrs.get("picture")
        extra = f" PIC {pic}" if pic else ""
        return f"{name}{extra}"
    if text and ntype not in {"source_file", "division", "environment_body"}:
        body = _wrap_label(str(text)[:80])
        return f"{name}\n{body}" if str(name) != body else body
    return str(name)


def _node_shape(nid: str, attrs: dict) -> tuple[str, str, str]:
    ntype = str(attrs.get("type") or "")
    if nid.startswith("para:") or ntype == "paragraph":
        return "box", "filled", NODE_FILL["paragraph"]
    if nid.startswith("data:") or ntype == "data_name":
        return "ellipse", "filled", NODE_FILL["data_name"]
    if nid.startswith("copy:") or ntype == "copybook":
        return "folder", "filled", NODE_FILL["copybook"]
    if nid.startswith("prog:") or ntype == "program":
        return "box", "filled,bold", NODE_FILL["program"]
    if nid.startswith("division:") or ntype == "division":
        return "hexagon", "filled", NODE_FILL["division"]
    if nid.startswith("stmt:") or ntype.endswith("_statement"):
        # Statements default to Light Green unless specifically overridden
        fill = NODE_FILL.get(ntype, "#d9ead3")
        return "box", "rounded,filled", fill
        
    # Logic and branching (Light Orange)
    if "branch" in ntype or "condition" in ntype or "evaluate" in ntype:
        return "box", "rounded,filled", "#fce5cd"
        
    # Data Division Syntax (Light Yellow)
    if "data" in ntype or "picture" in ntype or "value" in ntype or "occurs" in ntype or "level" in ntype or "entry" in ntype:
        return "box", "rounded,filled", "#fff2cc"
        
    # Program Architecture Syntax (Light Purple)
    if "division" in ntype or "section" in ntype or "paragraph" in ntype or "source_file" in ntype:
        return "box", "rounded,filled", "#e4d7f5"
        
    # Default fallback for unclassified AST nodes (Light Gray)
    return "box", "rounded,filled", "#f3f3f3"


def _clusters_for(view: str | None) -> bool:
    return view in {None, "combined", "cfg", "dfg", "overlay", "copybook"}


def graph_to_dot(g: nx.DiGraph, *, paper_style: bool = True) -> str:
    view = g.graph.get("view") or "combined"
    rankdir = "LR" if view == "ast" else "TB"
    title = f"COBMix {view}"
    # Per-view layout tuning
    if view == "dfg":
        # DFG standalone: TB, data nodes at top, procedure nodes below.
        # After pruning isolated nodes, the graph is small enough to lay
        # out cleanly with reaches edges as the vertical spine.
        rankdir = "TB"
        ranksep = "1.0"
        nodesep = "0.8"
    elif view == "ast":
        rankdir = "LR"
        ranksep = "0.7"
        nodesep = "0.5"
    else:
        rankdir = "TB"
        ranksep = "0.8"
        nodesep = "0.5"
    lines = [
        "digraph cobmix {",
        f'  graph [rankdir={rankdir} splines=true overlap=false concentrate=false newrank=true',
        f'    nodesep={nodesep} ranksep={ranksep} bgcolor="white" fontname="Helvetica"',
        f'    label="{_escape(title)}" labelloc=t fontsize=16];',
        '  node [fontname="Helvetica" fontsize=10 color="#444444"];',
        '  edge [fontname="Helvetica" fontsize=9 arrowsize=0.7 color="#444444"];',
    ]

    hide_data = (view == "dfg")
    use_clusters = paper_style and view != "ast"
    buckets = {"procedure": [], "data": [], "copy": [], "other": []}
    for nid, attrs in g.nodes(data=True):
        if nid.startswith("stmt:") or nid.startswith("para:") or attrs.get("type") == "paragraph":
            buckets["procedure"].append((nid, attrs))
        elif nid.startswith("data:") or attrs.get("type") == "data_name":
            if not hide_data:
                buckets["data"].append((nid, attrs))
        elif nid.startswith("copy:") or nid.startswith("prog:"):
            buckets["copy"].append((nid, attrs))
        else:
            buckets["other"].append((nid, attrs))

    def emit_node(nid: str, attrs: dict, indent: str = "  ") -> None:
        shape, style, fill = _node_shape(nid, attrs)
        label = _node_label(nid, attrs)
        lines.append(
            f'{indent}"{_escape(nid)}" [label="{_escape(label)}" shape={shape} '
            f'style="{style}" fillcolor="{fill}" margin="0.12,0.08"];'
        )

    if use_clusters and (buckets["procedure"] or buckets["data"] or buckets["copy"]):
        if buckets["copy"]:
            lines.append('  subgraph cluster_copy {')
            lines.append('    label="Programs / copybooks"; color="#6aa84f"; style=rounded;')
            for nid, attrs in buckets["copy"]:
                emit_node(nid, attrs, "    ")
            lines.append("  }")
        if buckets["data"]:
            lines.append('  subgraph cluster_data {')
            lines.append('    label="DATA DIVISION"; color="#bf9000"; style=rounded;')
            for nid, attrs in buckets["data"]:
                emit_node(nid, attrs, "    ")
            lines.append("  }")
        if buckets["procedure"]:
            lines.append('  subgraph cluster_proc {')
            lines.append('    label="PROCEDURE DIVISION"; color="#cc0000"; style=rounded;')
            for nid, attrs in buckets["procedure"]:
                emit_node(nid, attrs, "    ")
            lines.append("  }")
        for nid, attrs in buckets["other"]:
            emit_node(nid, attrs)
    else:
        for nid, attrs in g.nodes(data=True):
            emit_node(nid, attrs)

    for u, v, attrs in g.edges(data=True):
        etype = str(attrs.get("type") or "")
        
        if hide_data and etype in {"def", "use"}:
            continue
            
        if etype == "dfg_order":
            lines.append(f'  "{_escape(u)}" -> "{_escape(v)}" [style=invis weight=100];')
            continue
            
        color, style, family = EDGE_STYLE.get(etype, ("#444444", "solid", ""))
        label = etype
        if etype == "reaches" and attrs.get("name"):
            label = f"reaches {attrs.get('name')}"
        if etype == "occurs" and attrs.get("count"):
            label = f"occurs {attrs.get('count')}"
            
        # Self-loops never constrain rank
        if u == v:
            constraint = "false"
        elif etype in {"def", "use"}:
            # stmt->data cross-cluster: unconstrained so data cluster
            # floats freely without distorting the procedure spine
            constraint = "false"
        elif etype == "reaches":
            # reaches between two procedure nodes: constrain to build the spine
            u_proc = u.startswith("stmt:") or u.startswith("para:")
            v_proc = v.startswith("stmt:") or v.startswith("para:")
            constraint = "true" if (u_proc and v_proc) else "false"
        else:
            constraint = "false" if etype in DFG_EDGE_TYPES else "true"
            
        lines.append(
            f'  "{_escape(u)}" -> "{_escape(v)}" [label="{_escape(label)}" '
            f'color="{color}" fontcolor="{color}" style={style} constraint={constraint}];'
        )
    # DFG-only view: one invisible edge forces DATA cluster above PROCEDURE.
    # With isolated nodes already pruned, this makes the graph compact and clean.
    if view == "dfg" and buckets["data"] and buckets["procedure"]:
        anc_d = buckets["data"][0][0]
        anc_p = buckets["procedure"][0][0]
        lines.append(f'  "{_escape(anc_d)}" -> "{_escape(anc_p)}" [style=invis weight=10];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def find_dot() -> str | None:
    env = os.environ.get("GRAPHVIZ_DOT") or os.environ.get("DOT")
    candidates = [
        env,
        shutil.which("dot"),
        r"C:\Program Files\Graphviz\bin\dot.exe",
        r"C:\Program Files (x86)\Graphviz\bin\dot.exe",
        "/usr/bin/dot",
        "/usr/local/bin/dot",
        "/opt/homebrew/bin/dot",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return str(path)
    return None


def graph_to_png(g: nx.DiGraph, path: str | Path) -> Path:
    """Render with Graphviz `dot`, matching COMEX paper figures (no overlapping spring layout)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dot_exe = find_dot()
    if not dot_exe:
        raise RuntimeError(
            "Graphviz 'dot' was not found. Install Graphviz and ensure `dot` is on PATH "
            "(https://graphviz.org/download/), or set GRAPHVIZ_DOT to the full path of dot.exe."
        )
    dot_text = graph_to_dot(g, paper_style=True)
    env = os.environ.copy()
    bindir = str(Path(dot_exe).parent)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [dot_exe, "-Tpng", "-Gdpi=150", "-o", str(path.resolve())],
        input=dot_text.encode("utf-8"),
        capture_output=True,
        check=False,
        env=env,
        cwd=bindir,
    )
    if proc.returncode != 0 or not path.exists() or path.stat().st_size == 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"Graphviz failed to write {path}: {err}")
    return path


def visualization_graph(g: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Paper-style combined picture: CFG + reaching DFG + overlay + copybook (no def/use fans)."""
    keep_nodes: set[str] = set()
    out = nx.MultiDiGraph()
    out.graph["view"] = "combined"
    out.graph["views"] = [
        v for v in (g.graph.get("views") or []) if v in {"cfg", "dfg", "overlay", "copybook"}
    ]
    for u, v, attrs in g.edges(data=True):
        etype = attrs.get("type")
        view = attrs.get("view")
        if view in {"ast", "division"}:
            continue
        if etype in DIVISION_EDGE_TYPES or etype in AST_EDGE_TYPES:
            continue
        if etype in {"def", "use"}:
            continue
        keep_nodes.add(u)
        keep_nodes.add(v)
        if u not in out:
            out.add_node(u, **g.nodes[u])
        if v not in out:
            out.add_node(v, **g.nodes[v])
        out.add_edge(u, v, **attrs)
    for nid, attrs in g.nodes(data=True):
        ntype = attrs.get("type")
        if ntype in {"data_name", "copybook", "program", "paragraph"} or str(nid).startswith(
            ("data:", "copy:", "prog:", "para:")
        ):
            if nid not in out:
                views = set(attrs.get("views") or [])
                if views & {"overlay", "copybook", "cfg", "dfg"} or ntype in {"data_name", "copybook", "program"}:
                    out.add_node(nid, **attrs)
    for nid in keep_nodes:
        if nid not in out:
            out.add_node(nid, **g.nodes[nid])
    return out if out.number_of_nodes() else g


def _formats_for(graph_format: str) -> list[str]:
    fmt = graph_format.lower()
    if fmt in {"all", "both"}:
        return ["json", "dot", "png"]
    return [fmt]


def write_graph(
    g: nx.DiGraph,
    output_file: str | Path,
    graph_format: str = "json",
    extra_graphs: dict[str, nx.DiGraph] | None = None,
) -> list[Path]:
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    errors: list[str] = []
    visual = visualization_graph(g) if isinstance(g, nx.MultiDiGraph) else g

    for kind in _formats_for(graph_format):
        if kind == "json":
            path = output.with_suffix(".json")
            path.write_text(json.dumps(graph_to_json(g), indent=2), encoding="utf-8")
            written.append(path)
        elif kind == "dot":
            path = output.with_suffix(".dot")
            path.write_text(graph_to_dot(visual, paper_style=True), encoding="utf-8")
            written.append(path)
        elif kind == "png":
            path = output.with_suffix(".png")
            try:
                graph_to_png(visual, path)
                written.append(path)
            except Exception as exc:
                errors.append(f"PNG failed ({path}): {exc}")
        else:
            raise ValueError(f"Unknown graph format '{kind}'")

    if extra_graphs and graph_format.lower() in {"dot", "png", "all", "both"}:
        want_dot = graph_format.lower() in {"dot", "all", "both"}
        want_png = graph_format.lower() in {"png", "all", "both"}
        for name, vg in extra_graphs.items():
            if want_png:
                view_path = output.with_name(f"{output.stem}-{name}.png")
                try:
                    graph_to_png(vg, view_path)
                    written.append(view_path)
                except Exception as exc:
                    errors.append(f"PNG failed ({view_path}): {exc}")
            if want_dot:
                view_dot = output.with_name(f"{output.stem}-{name}.dot")
                view_dot.write_text(graph_to_dot(vg, paper_style=True), encoding="utf-8")
                written.append(view_dot)

    if errors:
        raise RuntimeError("; ".join(errors))
    return written
