from __future__ import annotations

import re
from dataclasses import dataclass, field

from cobmix.tree_parser.cst import Node


@dataclass
class DataItem:
    name: str
    level: int
    node: Node
    picture: str | None = None
    usage: str | None = None
    redefines: str | None = None
    occurs: int | None = None
    depending_on: str | None = None
    renames: str | None = None
    renames_thru: str | None = None
    parent: str | None = None
    start: int = 0
    size: int = 0
    source: str = "program"  # program | copy:{name}
    filler_id: int | None = None

    @property
    def graph_id(self) -> str:
        if self.filler_id is not None:
            return f"data:FILLER#{self.filler_id}"
        return f"data:{self.name.upper()}"


def picture_size(picture: str | None, usage: str | None) -> int:
    if not picture:
        return 0
    pic = picture.upper().replace(" ", "")
    # expand X(n) 9(n) A(n)
    def expand(match: re.Match[str]) -> str:
        ch, n = match.group(1), int(match.group(2))
        return ch * n

    pic = re.sub(r"([9XASVZNP])\((\d+)\)", expand, pic)
    digits = len(re.findall(r"[9]", pic))
    chars = len(re.findall(r"[XA]", pic))
    other = len(re.findall(r"[^9XASV.P+\-]", pic))
    display = max(digits + chars, len(pic.replace("S", "").replace("V", "").replace(".", "")))
    usage_u = (usage or "DISPLAY").upper()
    if usage_u in {"COMP-3", "PACKED-DECIMAL"}:
        return max(1, (digits + 1) // 2) if digits else display
    if usage_u in {"COMP", "COMP-4", "COMP-5", "BINARY"}:
        if digits <= 4:
            return 2
        if digits <= 9:
            return 4
        return 8
    if usage_u in {"COMP-1"}:
        return 4
    if usage_u in {"COMP-2"}:
        return 8
    return max(1, display)


def collect_data_items(tree: Node, source: str = "program", *, layout: bool = True) -> list[DataItem]:
    items: list[DataItem] = []
    filler_n = 0
    for node in tree.find_all("data_description"):
        level = int(node.extra.get("level", 1))
        name = node.extra.get("name")
        filler_id = None
        if not name or name.upper() == "FILLER":
            filler_n += 1
            filler_id = filler_n
            name = f"FILLER#{filler_n}"
        items.append(
            DataItem(
                name=name,
                level=level,
                node=node,
                picture=node.extra.get("picture"),
                usage=node.extra.get("usage"),
                redefines=node.extra.get("redefines"),
                occurs=node.extra.get("occurs"),
                depending_on=node.extra.get("depending_on"),
                renames=node.extra.get("renames"),
                renames_thru=node.extra.get("renames_thru"),
                source=source,
                filler_id=filler_id,
            )
        )
    _assign_parents(items)
    if layout:
        _layout(items)
    return items


def finalize_layout(items: list[DataItem]) -> list[DataItem]:
    """Recompute parent links and byte layout after splicing COPY books."""
    _assign_parents(items)
    _layout(items)
    return items


def _assign_parents(items: list[DataItem]) -> None:
    stack: list[DataItem] = []
    for item in items:
        if item.level in {1, 66, 77}:
            stack.clear()
            item.parent = None
            stack.append(item)
            continue
        if item.level == 88:
            item.parent = stack[-1].name if stack else None
            continue
        while stack and stack[-1].level >= item.level:
            stack.pop()
        item.parent = stack[-1].name if stack else None
        stack.append(item)


def _layout(items: list[DataItem]) -> None:
    by_name = {i.name.upper(): i for i in items}
    # children map
    children: dict[str, list[DataItem]] = {}
    for item in items:
        if item.parent:
            children.setdefault(item.parent.upper(), []).append(item)

    def size_of(item: DataItem) -> int:
        if item.level == 88:
            item.size = 0
            return 0
        if item.renames:
            item.size = 0
            return 0
        occurs = item.occurs or 1
        kids = [c for c in children.get(item.name.upper(), []) if c.level != 88]
        if item.picture:
            base = picture_size(item.picture, item.usage)
        elif kids:
            # groups: sequential children, REDEFINES share the target's start
            total = 0
            cursor = 0
            for kid in kids:
                if kid.redefines:
                    tgt = by_name.get(kid.redefines.upper())
                    kid.start = tgt.start if tgt else item.start + cursor
                else:
                    kid.start = item.start + cursor
                ksize = size_of(kid)
                if kid.redefines:
                    total = max(total, kid.start - item.start + ksize)
                else:
                    cursor += ksize
                    total = max(total, cursor)
            base = total
        else:
            base = 1
        item.size = base * occurs
        return item.size

    offset = 0
    for item in items:
        if item.parent:
            continue
        if item.redefines:
            tgt = by_name.get(item.redefines.upper())
            item.start = tgt.start if tgt else offset
        else:
            item.start = offset
        size_of(item)
        if not item.redefines and item.level != 66:
            offset = item.start + item.size

    for item in items:
        if not item.renames:
            continue
        frm = by_name.get(item.renames.upper())
        if not frm:
            continue
        item.start = frm.start
        if item.renames_thru:
            thru = by_name.get(item.renames_thru.upper())
            if thru:
                item.size = max(frm.size, thru.start + thru.size - item.start)
            else:
                item.size = frm.size
        else:
            item.size = frm.size


def _storage_root(item: DataItem, by_name: dict[str, DataItem]) -> str:
    """Independent 01/77 records are separate storage; REDEFINES/RENAMES follow the target."""
    cur = item
    seen: set[str] = set()
    while cur is not None:
        key = cur.name.upper()
        if key in seen:
            break
        seen.add(key)
        if cur.renames:
            tgt = by_name.get(cur.renames.upper())
            if tgt:
                cur = tgt
                continue
        if cur.redefines:
            tgt = by_name.get(cur.redefines.upper())
            if tgt:
                cur = tgt
                continue
        if cur.parent:
            cur = by_name.get(cur.parent.upper())
            continue
        break
    return cur.name.upper() if cur else item.name.upper()


def overlay_groups(items: list[DataItem]) -> dict[str, set[str]]:
    """Names that occupy overlapping storage (same record / REDEFINES / RENAMES).

    Used by the overlay view; includes parent<->child containment.
    For DFG alias expansion use :func:`redefines_aliases` instead.
    """
    by_name = {i.name.upper(): i for i in items}
    groups: dict[str, set[str]] = {i.name.upper(): {i.name.upper()} for i in items if i.level != 88}
    regions: dict[str, list[DataItem]] = {}
    for item in items:
        if item.level == 88:
            continue
        regions.setdefault(_storage_root(item, by_name), []).append(item)

    for region_items in regions.values():
        sized = [i for i in region_items if i.size > 0]
        for a in sized:
            a_end = a.start + a.size
            for b in sized:
                if a.name == b.name:
                    continue
                b_end = b.start + b.size
                if a.start < b_end and b.start < a_end:
                    groups[a.name.upper()].add(b.name.upper())
        for item in region_items:
            if item.parent:
                parent_key = item.parent.upper()
                if parent_key in groups and item.name.upper() in groups:
                    groups[item.name.upper()].add(parent_key)
                    groups[parent_key].add(item.name.upper())

    for item in items:
        key = item.name.upper()
        if item.redefines:
            tgt = item.redefines.upper()
            groups.setdefault(key, {key}).add(tgt)
            groups.setdefault(tgt, {tgt}).add(key)
        if item.renames:
            tgt = item.renames.upper()
            groups.setdefault(key, {key}).add(tgt)
            groups.setdefault(tgt, {tgt}).add(key)
            if item.renames_thru:
                thru = item.renames_thru.upper()
                groups[key].add(thru)
                groups.setdefault(thru, {thru}).add(key)
                start = item.start
                end = item.start + item.size
                for other in items:
                    if other.level in {66, 88} or other.name.upper() == key:
                        continue
                    other_end = other.start + max(other.size, 0)
                    if other.start >= start and other_end <= end and _storage_root(other, by_name) == _storage_root(item, by_name):
                        groups[key].add(other.name.upper())
                        groups.setdefault(other.name.upper(), {other.name.upper()}).add(key)
    return groups


def redefines_aliases(items: list[DataItem]) -> dict[str, set[str]]:
    """Return only REDEFINES / RENAMES alias pairs -- for DFG def/use expansion.

    Unlike overlay_groups() this does NOT include parent<->child containment
    or OCCURS-sibling relationships.  Those relationships are structural (overlay),
    not data-flow aliases: writing to EMP-SALARY does not mean EMP-ENTRY
    or EMPLOYEE-TABLE are also written.
    """
    aliases: dict[str, set[str]] = {}
    for item in items:
        key = item.name.upper()
        if item.redefines:
            tgt = item.redefines.upper()
            aliases.setdefault(key, set()).add(tgt)
            aliases.setdefault(tgt, set()).add(key)
        if item.renames:
            tgt = item.renames.upper()
            aliases.setdefault(key, set()).add(tgt)
            aliases.setdefault(tgt, set()).add(key)
            if item.renames_thru:
                thru = item.renames_thru.upper()
                aliases.setdefault(key, set()).add(thru)
                aliases.setdefault(thru, set()).add(key)
    return aliases
