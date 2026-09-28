from __future__ import annotations

from cobmix.tree_parser.context import ProgramContext
from cobmix.utils.graph import add_edge, add_node, new_graph


def build_division(ctx: ProgramContext):
    g = new_graph("division")
    for role in ("identification", "environment", "data", "procedure"):
        add_node(g, f"division:{role}", type="division", label=role, role=role)
    add_node(g, f"prog:{ctx.program_id}", type="program", label=ctx.program_id, role="identification")
    for div in ctx.tree.find_all("division"):
        role = div.extra.get("role", "procedure")
        add_edge(g, f"prog:{ctx.program_id}", f"division:{role}", "in_division")
    for item in ctx.items:
        role = "data"
        add_node(g, item.graph_id, type="data_name", label=item.name, role=role)
        add_edge(g, item.graph_id, "division:data", "in_division")
    for para in ctx.tree.find_all("paragraph") + ctx.tree.find_all("section"):
        pid = f"para:{para.extra.get('name', '').upper()}"
        add_node(g, pid, type="paragraph", label=para.extra.get("name"), role="procedure")
        add_edge(g, pid, "division:procedure", "in_division")
    for stmt in _procedure_statements(ctx):
        sid = f"stmt:{stmt.start_byte}"
        add_node(g, sid, type=stmt.type, label=stmt.type, role="procedure")
        add_edge(g, sid, "division:procedure", "in_division")
    return g


def _procedure_statements(ctx: ProgramContext):
    stmts = []
    for para in ctx.tree.find_all("paragraph") + ctx.tree.find_all("section"):
        for child in para.children:
            if child.type not in {"paragraph_name"}:
                stmts.append(child)
    return stmts
