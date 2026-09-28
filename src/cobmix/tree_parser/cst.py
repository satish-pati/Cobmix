from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Node:
    type: str
    text: str
    start_byte: int
    end_byte: int
    start_point: tuple[int, int]
    end_point: tuple[int, int]
    children: list["Node"] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find_all(self, ntype: str) -> list["Node"]:
        return [n for n in self.walk() if n.type == ntype]

    def named_children(self) -> list["Node"]:
        return list(self.children)


def point_of(text: str, index: int) -> tuple[int, int]:
    line = text.count("\n", 0, index)
    last_nl = text.rfind("\n", 0, index)
    col = index if last_nl < 0 else index - last_nl - 1
    return line, col


def make_node(
    ntype: str,
    source: str,
    start: int,
    end: int,
    children: list[Node] | None = None,
    extra: dict[str, Any] | None = None,
) -> Node:
    return Node(
        type=ntype,
        text=source[start:end],
        start_byte=start,
        end_byte=end,
        start_point=point_of(source, start),
        end_point=point_of(source, max(start, end - 1) if end > start else start),
        children=children or [],
        extra=extra or {},
    )
