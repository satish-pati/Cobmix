from __future__ import annotations

import re

from cobmix.codeviews.cfg.cfg_view import build_cfg, paragraphs
from cobmix.tree_parser.context import ProgramContext
from cobmix.tree_parser.cst import Node
from cobmix.utils.graph import add_edge, add_node, new_graph

IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")

# COBOL figurative constants — not real data items, exclude from DFG def/use
FIGURATIVE_CONSTANTS = {
    "ZERO", "ZEROS", "ZEROES",
    "SPACE", "SPACES",
    "HIGH-VALUE", "HIGH-VALUES",
    "LOW-VALUE", "LOW-VALUES",
    "QUOTE", "QUOTES",
    "ALL", "NULL", "NULLS",
}


def defs_uses(node: Node) -> tuple[list[str], list[str]]:
    extra = node.extra or {}
    defs = [
        d.upper() for d in extra.get("defs") or []
        if IDENT.match(str(d)) and d.upper() not in FIGURATIVE_CONSTANTS
    ]
    uses = [
        u.upper() for u in extra.get("uses") or []
        if IDENT.match(str(u)) and u.upper() not in FIGURATIVE_CONSTANTS
    ]
    return defs, uses


def expand_aliases(names: list[str], aliases: dict[str, set[str]]) -> set[str]:
    out: set[str] = set()
    for name in names:
        key = name.upper()
        out.add(key)
        out.update({a.upper() for a in aliases.get(key, set())})
    return out


def iter_cfg_statements(ctx: ProgramContext) -> list[Node]:
    nodes: list[Node] = []
    seen: set[int] = set()

    def add(n: Node) -> None:
        if n.start_byte in seen:
            return
        seen.add(n.start_byte)
        nodes.append(n)

    def walk(n: Node) -> None:
        if n.type.endswith("_statement") or n.type == "copy_statement":
            add(n)
        if n.type == "if_statement":
            for s in n.extra.get("then") or []:
                walk(s)
            for s in n.extra.get("else") or []:
                walk(s)
            return
        if n.type == "evaluate_statement":
            for arm in n.extra.get("arms") or []:
                for s in arm.get("statements") or []:
                    walk(s)
            return
        if n.type == "perform_statement" and n.extra.get("inline"):
            for s in n.extra.get("body") or []:
                walk(s)
            return

    for para in paragraphs(ctx):
        for child in para.children:
            if child.type == "paragraph_name":
                continue
            walk(child)
    return nodes


def build_dfg(ctx: ProgramContext):
    cfg = build_cfg(ctx)
    g = new_graph("dfg")
    for nid, attrs in cfg.nodes(data=True):
        add_node(g, nid, **attrs)

    for item in ctx.items:
        add_node(g, item.graph_id, type="data_name", label=item.name, role="data")

    stmts = iter_cfg_statements(ctx)
    stmt_by_id = {f"stmt:{n.start_byte}": n for n in stmts}
    names = {i.name.upper() for i in ctx.items}

    in_sets: dict[str, dict[str, set[str]]] = {s: {n: set() for n in names} for s in stmt_by_id}
    out_sets: dict[str, dict[str, set[str]]] = {s: {n: set() for n in names} for s in stmt_by_id}

    def stmt_succs(sid: str) -> list[str]:
        result: list[str] = []
        stack = list(cfg.successors(sid)) if sid in cfg else []
        seen: set[str] = set()
        while stack:
            nxt = stack.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            if nxt in stmt_by_id:
                result.append(nxt)
            elif str(nxt).startswith("para:"):
                stack.extend(cfg.successors(nxt))
        return result

    changed = True
    iterations = 0
    while changed and iterations < 200:
        changed = False
        iterations += 1
        for sid, node in stmt_by_id.items():
            defs, _uses = defs_uses(node)
            def_names = expand_aliases(defs, ctx.aliases)
            new_out = {n: set(in_sets[sid].get(n, set())) for n in names}
            for n in def_names:
                if n in new_out:
                    new_out[n] = {sid}
            if new_out != out_sets[sid]:
                out_sets[sid] = new_out
                changed = True
            for succ in stmt_succs(sid):
                for n in names:
                    before = len(in_sets[succ][n])
                    in_sets[succ][n].update(out_sets[sid][n])
                    if len(in_sets[succ][n]) != before:
                        changed = True

    for sid, node in stmt_by_id.items():
        defs, uses = defs_uses(node)
        use_names = expand_aliases(uses, ctx.aliases)
        def_names = expand_aliases(defs, ctx.aliases)
        for name in def_names:
            did = f"data:{name}"
            add_node(g, did, type="data_name", label=name, role="data")
            add_edge(g, sid, did, "def")
        for name in use_names:
            did = f"data:{name}"
            add_node(g, did, type="data_name", label=name, role="data")
            add_edge(g, sid, did, "use")
            for def_sid in in_sets.get(sid, {}).get(name, set()):
                add_edge(g, def_sid, sid, "reaches", name=name)
                
    # Remove nodes that have zero DFG edges (def/use/reaches).
    dfg_edge_types = {"def", "use", "reaches"}
    nodes_with_dfg = set()
    for u, v, d in g.edges(data=True):
        if d.get("type") in dfg_edge_types:
            nodes_with_dfg.add(u)
            nodes_with_dfg.add(v)
    remove = [n for n in g.nodes() if n not in nodes_with_dfg]
    g.remove_nodes_from(remove)
    
    # Add invisible structural edges to enforce a clean top-to-bottom chronological layout
    dfg_stmts = sorted(
        [n for n in g.nodes() if str(n).startswith("stmt:")],
        key=lambda x: int(x.split(":")[1])
    )
    for a, b in zip(dfg_stmts, dfg_stmts[1:]):
        add_edge(g, a, b, "dfg_order", style="invis", weight=100)
        
    return g
