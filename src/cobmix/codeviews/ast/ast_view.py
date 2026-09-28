from __future__ import annotations

from cobmix.tree_parser.context import ProgramContext
from cobmix.tree_parser.cst import Node
from cobmix.utils.graph import add_edge, add_node, new_graph

DROP_TYPES = {"punct", "environment_clause"}


def build_ast(ctx: ProgramContext):
    g = new_graph("ast")
    counter = {"n": 0}

    def nid(node: Node) -> str:
        counter["n"] += 1
        return f"ast:{node.start_byte}:{node.type}:{counter['n']}"

    def keep(node: Node) -> bool:
        if node.type in DROP_TYPES:
            return False
        if node.type == "environment_body":
            return True
        return True

    def walk(node: Node, parent_id: str | None) -> str | None:
        if not keep(node):
            return parent_id
        ident = nid(node)
        role = ctx.role_at(node.start_byte)
        add_node(
            g,
            ident,
            type=node.type,
            label=(node.extra.get("name") or node.type),
            text=node.text[:120].replace("\n", " "),
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            role=role,
        )
        if parent_id:
            add_edge(g, parent_id, ident, "ast")
        for child in node.children:
            walk(child, ident)
        return ident

    walk(ctx.tree, None)
    return g
