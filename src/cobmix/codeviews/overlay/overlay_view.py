from __future__ import annotations

from cobmix.tree_parser.context import ProgramContext
from cobmix.tree_parser.data_layout import DataItem
from cobmix.utils.graph import add_edge, add_node, new_graph


def build_overlay(ctx: ProgramContext):
    g = new_graph("overlay")
    by_name = {i.name.upper(): i for i in ctx.items}
    for item in ctx.items:
        add_node(
            g,
            item.graph_id,
            type="data_name",
            label=item.name,
            level=item.level,
            picture=item.picture,
            usage=item.usage,
            occurs=item.occurs,
            depending_on=item.depending_on,
            start=item.start,
            size=item.size,
            source=item.source,
            role="data",
        )
        if item.parent:
            parent = by_name.get(item.parent.upper())
            if parent:
                add_edge(g, parent.graph_id, item.graph_id, "contains")
        if item.redefines:
            target = by_name.get(item.redefines.upper())
            if target:
                add_edge(g, item.graph_id, target.graph_id, "redefines")
            else:
                add_node(g, f"data:{item.redefines.upper()}", type="data_name", label=item.redefines, role="data")
                add_edge(g, item.graph_id, f"data:{item.redefines.upper()}", "redefines")
        if item.occurs:
            add_edge(
                g,
                item.graph_id,
                item.graph_id,
                "occurs",
                count=item.occurs,
                depending_on=item.depending_on,
            )
        if item.renames:
            frm = by_name.get(item.renames.upper())
            if frm:
                add_edge(g, item.graph_id, frm.graph_id, "renames")
            if item.renames_thru:
                thru = by_name.get(item.renames_thru.upper())
                if thru:
                    add_edge(g, item.graph_id, thru.graph_id, "renames")
    return g
