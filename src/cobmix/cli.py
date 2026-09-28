from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cobmix.codeviews.combined.combined_driver import ALL_VIEWS, CombinedDriver


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cobmix",
        description="Generate customized COBOL code-view graphs (COMEX-style).",
    )
    parser.add_argument("--code-file", action="append", dest="code_files", required=True, help="COBOL source file (.cbl/.cob). Repeatable.")
    parser.add_argument("--copy-path", action="append", dest="copy_paths", default=[], help="Directory or file to search for COPY books.")
    parser.add_argument("--graphs", default=",".join(ALL_VIEWS), help="Comma-separated views: ast,cfg,dfg,copybook,overlay,division")
    parser.add_argument(
        "--format",
        dest="graph_format",
        default="json",
        choices=["json", "dot", "png", "all"],
        help="Output format. 'all' writes .json, .dot, and .png next to --output",
    )
    parser.add_argument(
        "--output",
        default="cobmix-output.json",
        help="Output path; the suffix is replaced for each format (out.json / out.dot / out.png)",
    )
    args = parser.parse_args(argv)

    graphs = [part.strip() for part in args.graphs.split(",") if part.strip()]
    files = [Path(p) for p in args.code_files]
    missing = [p for p in files if not p.exists()]
    if missing:
        print(f"File not found: {missing[0]}", file=sys.stderr)
        return 2
    try:
        driver = CombinedDriver.from_files(
            files=files,
            copy_paths=args.copy_paths,
            graphs=graphs,
            output_file=args.output,
            graph_format=args.graph_format,
        )
    except Exception as exc:
        print(f"Failed to write graphs: {exc}", file=sys.stderr)
        return 1
    written = ", ".join(str(p) for p in driver.written) or args.output
    print(f"Wrote {driver.graph.number_of_nodes()} nodes, {driver.graph.number_of_edges()} edges -> {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
