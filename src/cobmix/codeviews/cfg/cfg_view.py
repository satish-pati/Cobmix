from __future__ import annotations

from dataclasses import dataclass, field

from cobmix.tree_parser.context import ProgramContext
from cobmix.tree_parser.cst import Node
from cobmix.utils.graph import add_edge, add_node, new_graph

CONTROL_TYPES = {
    "if_statement",
    "evaluate_statement",
    "perform_statement",
    "goto_statement",
    "call_statement",
    "stop_statement",
}


@dataclass
class CfgStmt:
    node: Node
    sid: str
    paragraph: str


def flatten_statements(node: Node, paragraph: str) -> list[CfgStmt]:
    """Linearize nested IF/EVALUATE/PERFORM bodies as CFG statement nodes."""
    out: list[CfgStmt] = []

    def add(n: Node) -> CfgStmt:
        stmt = CfgStmt(node=n, sid=f"stmt:{n.start_byte}", paragraph=paragraph)
        out.append(stmt)
        return stmt

    def walk(n: Node) -> None:
        if n.type in {"then_branch", "else_branch", "paragraph_name", "condition"}:
            for c in n.children:
                walk(c)
            return
        if n.type == "if_statement":
            add(n)
            for c in n.children:
                walk(c)
            return
        if n.type == "evaluate_statement":
            add(n)
            for arm in n.extra.get("arms") or []:
                for s in arm.get("statements") or []:
                    walk(s)
            return
        if n.type == "perform_statement" and n.extra.get("inline"):
            add(n)
            for s in n.extra.get("body") or []:
                walk(s)
            return
        if n.type.endswith("_statement") or n.type == "copy_statement":
            add(n)
            return
        for c in n.children:
            walk(c)

    walk(node)
    return out


def _proc_division(ctx: ProgramContext):
    """Return the PROCEDURE DIVISION node, or None."""
    for div in ctx.tree.find_all("division"):
        name_nodes = [c for c in (div.children or []) if c.type == "division_name"]
        if name_nodes and name_nodes[0].text.strip().upper() == "PROCEDURE":
            return div
    return None


def paragraphs(ctx: ProgramContext) -> list[Node]:
    paras = ctx.tree.find_all("paragraph") + ctx.tree.find_all("section")
    paras.sort(key=lambda n: n.start_byte)
    if paras:
        return paras

    # No named paragraphs found — synthesize one virtual paragraph wrapping
    # the bare statements directly inside the PROCEDURE DIVISION.
    proc = _proc_division(ctx)
    if proc is None:
        return []
    bare_stmts = [
        c for c in (proc.children or [])
        if c.type.endswith("_statement") or c.type == "copy_statement"
    ]
    if not bare_stmts:
        return []

    # Build a synthetic Node that looks like a paragraph.
    # We reuse the Node dataclass fields that build_cfg reads.
    class _SyntheticParagraph:
        type = "paragraph"
        start_byte = bare_stmts[0].start_byte
        end_byte = bare_stmts[-1].end_byte
        text = ""
        extra = {"name": "MAIN"}
        children = bare_stmts

    return [_SyntheticParagraph()]



def build_cfg(ctx: ProgramContext):
    g = new_graph("cfg")
    paras = paragraphs(ctx)
    para_nodes = {para.extra.get("name", "").upper(): para for para in paras}
    para_stmts: dict[str, list[CfgStmt]] = {}
    order: list[str] = []

    for para in paras:
        name = para.extra.get("name", "").upper()
        pid = f"para:{name}"
        add_node(g, pid, type="paragraph", label=para.extra.get("name"), role="procedure")
        stmts: list[CfgStmt] = []
        for child in para.children:
            if child.type == "paragraph_name":
                continue
            stmts.extend(flatten_statements(child, name))
        para_stmts[name] = stmts
        order.append(name)
        for stmt in stmts:
            add_node(
                g,
                stmt.sid,
                type=stmt.node.type,
                label=stmt.node.type,
                paragraph=name,
                role="procedure",
                text=stmt.node.text[:80].replace("\n", " "),
            )

    para_exits: dict[str, list[tuple[str, str]]] = {}
    
    for name, stmts in para_stmts.items():
        pid = f"para:{name}"
        para = para_nodes[name]
        linear = _top_level_of_paragraph(para, name)
        top_level_nodes = [s.node for s in linear]
        if top_level_nodes:
            exits = _wire_sequence(g, top_level_nodes, [(pid, "next")], order)
            para_exits[name] = exits
        else:
            para_exits[name] = [(pid, "next")]

    _wire_fallthrough(g, order, para_exits, para_stmts)
    _wire_perform_returns(g, order, para_exits, para_stmts)

    return g


def _is_top_level(stmt: CfgStmt, all_stmts: list[CfgStmt]) -> bool:
    return True


def _top_level_of_paragraph(para: Node, name: str) -> list[CfgStmt]:
    result: list[CfgStmt] = []
    for child in para.children:
        if child.type == "paragraph_name":
            continue
        result.append(CfgStmt(node=child, sid=f"stmt:{child.start_byte}", paragraph=name))
    return result


def _wire_sequence(g, stmts: list[Node], current_sources: list[tuple[str, str]], order: list[str]) -> list[tuple[str, str]]:
    for node in stmts:
        if node.type in {"then_branch", "else_branch"}:
            continue
            
        sid = f"stmt:{node.start_byte}"
        
        for src_id, etype in current_sources:
            if src_id != sid:
                add_edge(g, src_id, sid, etype)
            
        if node.type == "if_statement":
            then_nodes = node.extra.get("then") or []
            else_nodes = node.extra.get("else") or []
            
            then_exits = _wire_sequence(g, then_nodes, [(sid, "true")], order)
            if else_nodes:
                else_exits = _wire_sequence(g, else_nodes, [(sid, "false")], order)
            else:
                else_exits = [(sid, "false")]
                
            current_sources = then_exits + else_exits
            
        elif node.type == "evaluate_statement":
            arms = node.extra.get("arms") or []
            evaluate_exits = []
            for arm in arms:
                arm_stmts = arm.get("statements") or []
                evaluate_exits.extend(_wire_sequence(g, arm_stmts, [(sid, "true")], order))
            if not arms:
                evaluate_exits = [(sid, "next")]
            current_sources = evaluate_exits
            
        elif node.type == "perform_statement":
            extra = node.extra
            if extra.get("inline"):
                body = extra.get("body") or []
                current_sources = _wire_sequence(g, body, [(sid, "next")], order)
            else:
                target = extra.get("target")
                if target:
                    tname = target.upper()
                    add_edge(g, sid, f"para:{tname}", "perform")
                    thru = extra.get("thru")
                    if thru:
                        t2 = thru.upper()
                        if order:
                            try:
                                i1 = order.index(tname)
                                i2 = order.index(t2)
                                lo, hi = (i1, i2) if i1 <= i2 else (i2, i1)
                                chain = order[lo : hi + 1]
                                for a, b in zip(chain, chain[1:]):
                                    add_edge(g, f"para:{a}", f"para:{b}", "thru")
                            except ValueError:
                                add_edge(g, f"para:{tname}", f"para:{t2}", "thru")
                        else:
                            add_edge(g, f"para:{tname}", f"para:{t2}", "thru")
                    current_sources = [(sid, "next")]
                else:
                    current_sources = [(sid, "next")]
                    
        elif node.type == "goto_statement":
            target = node.extra.get("target")
            if target:
                add_edge(g, sid, f"para:{target.upper()}", "goto")
            current_sources = []
            
        elif node.type == "stop_statement":
            current_sources = []
            
        elif node.type == "call_statement":
            target = node.extra.get("target")
            if target:
                nid = f"prog:{target.upper()}"
                add_node(g, nid, type="program", label=target, role="procedure")
                add_edge(g, sid, nid, "call")
            current_sources = [(sid, "next")]
            
        else:
            current_sources = [(sid, "next")]
            
    return current_sources


def _wire_fallthrough(g, order: list[str], para_exits: dict[str, list[tuple[str, str]]], para_stmts: dict[str, list[CfgStmt]]) -> None:
    """Wire natural fall-through between consecutive paragraphs."""
    perform_targets: set[str] = set()
    thru_chains: set[tuple[str, str]] = set()
    
    for stmts in para_stmts.values():
        for stmt in stmts:
            if stmt.node.type == "perform_statement":
                t = stmt.node.extra.get("target")
                thru = stmt.node.extra.get("thru")
                if t:
                    perform_targets.add(t.upper())
                if thru:
                    perform_targets.add(thru.upper())
                    if t:
                        try:
                            i1 = order.index(t.upper())
                            i2 = order.index(thru.upper())
                            lo, hi = min(i1, i2), max(i1, i2)
                            chain = order[lo : hi + 1]
                            for a, b in zip(chain, chain[1:]):
                                thru_chains.add((a, b))
                        except ValueError:
                            pass

    for i, (a_name, b_name) in enumerate(zip(order, order[1:])):
        if (a_name, b_name) not in thru_chains:
            if b_name in perform_targets and a_name in perform_targets:
                continue
        nxt = f"para:{b_name}"
        for src_id, etype in para_exits.get(a_name, []):
            add_edge(g, src_id, nxt, etype)


def _wire_perform_returns(g, order: list[str], para_exits: dict[str, list[tuple[str, str]]], para_stmts: dict[str, list[CfgStmt]]) -> None:
    """Wire 'return' edges from PERFORM-ed paragraph exits back to the statement after the PERFORM call site."""
    names = [n.upper() for n in order]
    for stmts in para_stmts.values():
        for stmt in stmts:
            if stmt.node.type != "perform_statement" or stmt.node.extra.get("inline"):
                continue
            target = stmt.node.extra.get("target")
            if not target:
                continue
            tname = target.upper()
            thru = stmt.node.extra.get("thru")
            end_name = tname
            if thru and names:
                try:
                    i1 = names.index(tname)
                    i2 = names.index(thru.upper())
                    end_name = names[max(i1, i2)]
                except ValueError:
                    end_name = thru.upper()
            
            returns = [
                v
                for _, v, d in g.out_edges(stmt.sid, data=True)
                if d.get("type") == "next"
            ]
            if not returns:
                continue
                
            for src_id, _ in para_exits.get(end_name, []):
                for dest in returns:
                    if src_id != dest:
                        add_edge(g, src_id, dest, "return")
