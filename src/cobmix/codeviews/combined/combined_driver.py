from __future__ import annotations

from pathlib import Path

import networkx as nx

from cobmix.codeviews.ast.ast_view import build_ast
from cobmix.codeviews.cfg.cfg_view import build_cfg
from cobmix.codeviews.copybook.copybook_view import build_copybook
from cobmix.codeviews.dfg.dfg_view import build_dfg
from cobmix.codeviews.division.division_view import build_division
from cobmix.codeviews.overlay.overlay_view import build_overlay
from cobmix.tree_parser.context import ProgramContext, analyze_program
from cobmix.utils.graph import merge_graphs, write_graph

VIEW_BUILDERS = {
    "ast": build_ast,
    "cfg": build_cfg,
    "dfg": build_dfg,
    "copybook": build_copybook,
    "overlay": build_overlay,
    "division": build_division,
}

ALL_VIEWS = tuple(VIEW_BUILDERS)


class CombinedDriver:
    def __init__(
        self,
        src_code: str | None = None,
        code_file: str | Path | None = None,
        copy_paths: list[str] | None = None,
        graphs: list[str] | None = None,
        output_file: str | Path | None = None,
        graph_format: str = "json",
        extra_contexts: list[ProgramContext] | None = None,
    ):
        if src_code is None and code_file is None:
            raise ValueError("src_code or code_file is required")
        if src_code is None:
            path = Path(code_file)
            src_code = path.read_text(encoding="utf-8", errors="replace")
            filename = str(path)
        else:
            filename = str(code_file) if code_file else "<memory>"
        self.copy_paths = [str(p) for p in (copy_paths or [])]
        self.requested = _normalize_graphs(graphs)
        self.context = analyze_program(src_code, filename=filename, copy_paths=self.copy_paths)
        self.views: dict[str, nx.DiGraph] = {}
        parts = [VIEW_BUILDERS[name](self.context) for name in self.requested]
        if extra_contexts:
            for extra in extra_contexts:
                for name in self.requested:
                    parts.append(VIEW_BUILDERS[name](extra))
        self.graph = merge_graphs(parts)
        self.views = {name: VIEW_BUILDERS[name](self.context) for name in self.requested}
        self.written: list[Path] = []
        if output_file:
            self.written = write_graph(
                self.graph,
                output_file,
                graph_format,
                extra_graphs=self.views if graph_format.lower() in {"dot", "png", "all", "both"} else None,
            )

    @classmethod
    def from_files(
        cls,
        files: list[str | Path],
        copy_paths: list[str] | None = None,
        graphs: list[str] | None = None,
        output_file: str | Path | None = None,
        graph_format: str = "json",
    ) -> "CombinedDriver":
        paths = [Path(f) for f in files]
        first, rest = paths[0], paths[1:]
        extras = [
            analyze_program(p.read_text(encoding="utf-8", errors="replace"), filename=str(p), copy_paths=copy_paths or [])
            for p in rest
        ]
        return cls(
            code_file=first,
            copy_paths=copy_paths,
            graphs=graphs,
            output_file=output_file,
            graph_format=graph_format,
            extra_contexts=extras,
        )


def _normalize_graphs(graphs: list[str] | None) -> list[str]:
    if not graphs:
        return list(ALL_VIEWS)
    names: list[str] = []
    for item in graphs:
        for part in str(item).split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in VIEW_BUILDERS:
                raise ValueError(f"Unknown graph view '{name}'. Choose from: {', '.join(ALL_VIEWS)}")
            if name not in names:
                names.append(name)
    return names
