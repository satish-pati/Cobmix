from __future__ import annotations

from cobmix.tree_parser.context import ProgramContext
from cobmix.utils.graph import add_edge, add_node, new_graph


def build_copybook(ctx: ProgramContext):
    g = new_graph("copybook")
    pid = f"prog:{ctx.program_id}"
    add_node(g, pid, type="program", label=ctx.program_id, role="identification")
    seen: dict[str, str] = {}
    for ref in ctx.copybooks:
        cid = f"copy:{ref.key}"
        add_node(
            g,
            cid,
            type="copybook",
            label=ref.key,
            unresolved=ref.unresolved,
            path=str(ref.path) if ref.path else None,
            role=ref.role,
        )
        add_edge(g, pid, cid, "includes")
        seen[ref.key] = cid
        for item in ref.items:
            add_node(g, item.graph_id, type="data_name", label=item.name, role="data", source=item.source)
            add_edge(g, cid, item.graph_id, "declares")
    return g
