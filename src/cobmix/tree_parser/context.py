from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cobmix.tree_parser.cobol_parser import parse_cobol
from cobmix.tree_parser.copy_resolver import (
    copybook_key,
    find_copybook,
    parse_copybook_file,
)
from cobmix.tree_parser.cst import Node
from cobmix.tree_parser.data_layout import DataItem, collect_data_items, finalize_layout, overlay_groups, redefines_aliases


@dataclass
class CopybookRef:
    name: str
    key: str
    node: Node
    path: Path | None
    tree: Node | None
    unresolved: bool
    items: list[DataItem] = field(default_factory=list)
    role: str = "data"


@dataclass
class ProgramContext:
    source: str
    filename: str
    tree: Node
    program_id: str
    copy_paths: list[str]
    copybooks: list[CopybookRef]
    items: list[DataItem]
    aliases: dict[str, set[str]]
    redef_aliases: dict[str, set[str]]  # REDEFINES/RENAMES only (for DFG)

    @property
    def role_at(self):
        ranges = []
        for div in self.tree.find_all("division"):
            ranges.append((div.start_byte, div.end_byte, div.extra.get("role", "procedure")))
        ranges.sort()

        def lookup(pos: int) -> str:
            for start, end, role in ranges:
                if start <= pos <= end:
                    return role
            return "procedure"

        return lookup


def analyze_program(source: str, filename: str = "<memory>", copy_paths: list[str] | None = None) -> ProgramContext:
    copy_paths = copy_paths or []
    tree = parse_cobol(source, filename)
    program_id = tree.extra.get("program_id") or Path(filename).stem
    copybooks: list[CopybookRef] = []
    program_items = collect_data_items(tree, source="program", layout=False)
    ctx_tmp_ranges = [(d.start_byte, d.end_byte, d.extra.get("role")) for d in tree.find_all("division")]

    def site_role(pos: int) -> str:
        for start, end, role in ctx_tmp_ranges:
            if start <= pos <= end:
                return role or "data"
        return "data"

    for copy_node in tree.find_all("copy_statement"):
        name = copy_node.extra.get("name") or copy_node.text
        key = copybook_key(name)
        path = find_copybook(name, copy_paths)
        replacing = copy_node.extra.get("replacing") or []
        role = site_role(copy_node.start_byte)
        if path is None:
            copybooks.append(
                CopybookRef(
                    name=name,
                    key=key,
                    node=copy_node,
                    path=None,
                    tree=None,
                    unresolved=True,
                    role=role,
                )
            )
            continue
        ctree = parse_copybook_file(path, replacing=replacing, role_hint=role)
        citems = collect_data_items(ctree, source=f"copy:{key}", layout=False)
        copybooks.append(
            CopybookRef(
                name=name,
                key=key,
                node=copy_node,
                path=path,
                tree=ctree,
                unresolved=False,
                items=citems,
                role=role,
            )
        )
    items = _merge_copy_items(program_items, copybooks)
    finalize_layout(items)
    aliases = overlay_groups(items)
    rdaliases = redefines_aliases(items)
    return ProgramContext(
        source=source,
        filename=filename,
        tree=tree,
        program_id=program_id,
        copy_paths=copy_paths,
        copybooks=copybooks,
        items=items,
        aliases=aliases,
        redef_aliases=rdaliases,
    )


def _merge_copy_items(program_items: list[DataItem], copybooks: list[CopybookRef]) -> list[DataItem]:
    """Insert COPY records at the COPY statement site so 01-level layout is sequential."""
    events: list[tuple[int, int, int, object]] = [
        (item.node.start_byte, 1, idx, item) for idx, item in enumerate(program_items)
    ]
    for idx, ref in enumerate(copybooks):
        events.append((ref.node.start_byte, 0, idx, ref))
    events.sort()
    merged: list[DataItem] = []
    for _pos, kind, _idx, payload in events:
        if kind == 0:
            merged.extend(payload.items)
        else:
            merged.append(payload)
    return merged
