from __future__ import annotations

from pathlib import Path

from cobmix.tree_parser.cobol_parser import parse_cobol
from cobmix.tree_parser.cst import Node, make_node


def copybook_key(name: str) -> str:
    return name.strip().strip("\"'").upper().replace("_", "-")


def find_copybook(name: str, copy_paths: list[str | Path]) -> Path | None:
    key = copybook_key(name)
    stems = {key, key.replace("-", "_"), name}
    suffixes = [".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", ".cobcopy", ""]
    dirs = [Path(p) for p in copy_paths]
    for directory in dirs:
        if not directory.exists():
            continue
        if directory.is_file():
            if copybook_key(directory.stem) == key:
                return directory
            continue
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            if copybook_key(entry.stem) == key:
                return entry
            for stem in stems:
                for suf in suffixes:
                    cand = directory / f"{stem}{suf}"
                    if cand.exists():
                        return cand
    return None


def apply_replacing(text: str, pairs: list[tuple[str, str]]) -> str:
    result = text
    for old, new in pairs:
        if not old:
            continue
        result = result.replace(old, new)
        result = result.replace(old.upper(), new)
        result = result.replace(old.lower(), new)
    return result


def wrap_fragment(text: str, role_hint: str = "data") -> str:
    """Copybooks may be fragments without divisions; wrap so the parser can run."""
    upper = text.upper()
    if "IDENTIFICATION DIVISION" in upper or "PROCEDURE DIVISION" in upper or "DATA DIVISION" in upper:
        return text
    if role_hint == "procedure":
        return (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. COPYFRAG.\n"
            "       PROCEDURE DIVISION.\n"
            "       COPY-PARA.\n"
            f"{text}\n"
        )
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. COPYFRAG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{text}\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           STOP RUN.\n"
    )


def parse_copybook_file(path: Path, replacing: list[tuple[str, str]] | None = None, role_hint: str = "data") -> Node:
    text = path.read_text(encoding="utf-8", errors="replace")
    if replacing:
        text = apply_replacing(text, replacing)
    wrapped = wrap_fragment(text, role_hint)
    tree = parse_cobol(text if "IDENTIFICATION DIVISION" in text.upper() else wrapped, filename=str(path))
    tree.extra["copybook_path"] = str(path)
    tree.extra["is_wrapped"] = wrapped != text
    return tree


def collect_copy_statements(tree: Node) -> list[Node]:
    return tree.find_all("copy_statement")
