from pathlib import Path

import pytest

from cobmix import CombinedDriver
from cobmix.tree_parser.context import analyze_program
from cobmix.utils.graph import find_dot

# Skip PNG tests gracefully when Graphviz `dot` is not installed.
requires_graphviz = pytest.mark.skipif(
    find_dot() is None,
    reason="Graphviz `dot` not found on PATH. Install Graphviz to run PNG tests.",
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
COPY = DATA / "copy"


def test_overlay_redefines_contains_occurs_renames():
    src = (DATA / "overlay.cbl").read_text(encoding="utf-8")
    driver = CombinedDriver(src_code=src, graphs=["overlay"])
    g = driver.views["overlay"]
    assert ("data:WS-DATE-ALPHA", "data:WS-DATE") in g.edges
    assert any(
        d.get("type") == "redefines"
        for u, v, d in g.edges(data=True)
        if u == "data:WS-DATE-ALPHA" and v == "data:WS-DATE"
    )
    assert ("data:WS-DATE", "data:WS-YEAR") in g.edges
    assert any(
        d.get("type") == "contains"
        for u, v, d in g.edges(data=True)
        if u == "data:WS-DATE" and v == "data:WS-YEAR"
    )
    assert ("data:WS-YMD", "data:WS-YEAR") in g.edges
    assert any(
        d.get("type") == "renames"
        for u, v, d in g.edges(data=True)
        if u == "data:WS-YMD" and v == "data:WS-YEAR"
    )
    occurs = [
        data
        for u, v, data in g.edges(data=True)
        if data.get("type") == "occurs"
    ]
    assert occurs and occurs[0].get("count") == 10


def test_copybook_shared_across_programs():
    driver = CombinedDriver.from_files(
        [DATA / "copy_user_a.cbl", DATA / "copy_user_b.cbl"],
        copy_paths=[str(COPY)],
        graphs=["copybook"],
    )
    g = driver.graph
    assert "copy:EMPREC" in g
    assert g.nodes["copy:EMPREC"].get("unresolved") is False
    includes = [
        (u, v)
        for u, v, d in g.edges(data=True)
        if d.get("type") == "includes" and v == "copy:EMPREC"
    ]
    assert ("prog:COPY-USER-A", "copy:EMPREC") in includes
    assert ("prog:COPY-USER-B", "copy:EMPREC") in includes
    declares = [
        v
        for u, v, d in g.edges(data=True)
        if u == "copy:EMPREC" and d.get("type") == "declares"
    ]
    assert "data:EMP-ID" in declares
    assert "data:EMP-NAME" in declares


def test_cfg_perform_if_goto():
    src = (DATA / "cfg.cbl").read_text(encoding="utf-8")
    driver = CombinedDriver(src_code=src, graphs=["cfg"])
    g = driver.views["cfg"]
    edge_types = {(u, v, d["type"]) for u, v, d in g.edges(data=True)}
    assert any(t == "true" for _, _, t in edge_types)
    assert any(t == "false" for _, _, t in edge_types)
    assert any(t == "perform" and v == "para:INIT-PARA" for _, v, t in edge_types)
    assert any(t == "thru" for _, _, t in edge_types)
    assert any(t == "goto" and v == "para:EXIT-PARA" for _, v, t in edge_types)
    assert "para:MAIN" in g
    assert "para:WORK-PARA" in g


def test_dfg_move_compute_reaches():
    src = (DATA / "dfg.cbl").read_text(encoding="utf-8")
    driver = CombinedDriver(src_code=src, graphs=["dfg"])
    g = driver.views["dfg"]
    reaches = [
        (u, v, d.get("name"))
        for u, v, d in g.edges(data=True)
        if d.get("type") == "reaches"
    ]
    names = {n for _, _, n in reaches}
    assert "WS-A" in names
    assert "WS-B" in names
    defs = [v for u, v, d in g.edges(data=True) if d.get("type") == "def"]
    assert "data:WS-A" in defs
    assert "data:WS-B" in defs


def test_dfg_overlay_alias_from_redefines():
    src = (DATA / "overlay.cbl").read_text(encoding="utf-8")
    ctx = analyze_program(src)
    assert "WS-DATE" in ctx.aliases.get("WS-DATE-ALPHA", set())
    driver = CombinedDriver(src_code=src, graphs=["dfg"])
    g = driver.views["dfg"]
    # MOVE to WS-DATE-ALPHA should also def overlapping WS-DATE
    def_targets = {v for u, v, d in g.edges(data=True) if d.get("type") == "def"}
    assert "data:WS-DATE-ALPHA" in def_targets
    assert "data:WS-DATE" in def_targets


def test_division_roles():
    src = (DATA / "cfg.cbl").read_text(encoding="utf-8")
    driver = CombinedDriver(src_code=src, graphs=["division", "ast"])
    ast = driver.views["ast"]
    roles = {attrs.get("role") for _, attrs in ast.nodes(data=True)}
    assert "identification" in roles
    assert "data" in roles
    assert "procedure" in roles
    div = driver.views["division"]
    assert "division:data" in div
    assert "division:procedure" in div


@requires_graphviz
def test_combined_and_json_dot_export(tmp_path):
    src = (DATA / "cfg.cbl").read_text(encoding="utf-8")
    out = tmp_path / "out.json"
    driver = CombinedDriver(
        src_code=src,
        graphs=["ast", "cfg", "dfg", "division"],
        output_file=out,
        graph_format="all",
    )
    assert out.exists()
    assert tmp_path.joinpath("out.dot").exists()
    png = tmp_path / "out.png"
    assert png.exists()
    assert png.stat().st_size > 0
    dot = tmp_path / "out.dot"
    assert "splines=true" in dot.read_text(encoding="utf-8")
    assert "overlap=false" in dot.read_text(encoding="utf-8")
    assert driver.graph.number_of_nodes() > 0
    assert "combined" == driver.graph.graph.get("view")


def test_cli_sample(tmp_path):
    from cobmix.cli import main

    out = tmp_path / "cli.json"
    sample = ROOT.parent / "samples" / "emp-main.cbl"
    copies = ROOT.parent / "samples" / "copy"
    rc = main(
        [
            "--code-file",
            str(sample),
            "--copy-path",
            str(copies),
            "--graphs",
            "ast,cfg,dfg,copybook,overlay,division",
            "--format",
            "json",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()


def _stmt_by_text(g, snippet: str):
    snippet = snippet.upper()
    for nid, attrs in g.nodes(data=True):
        text = str(attrs.get("text") or "").upper()
        if snippet in text:
            return nid
    return None


def test_sample_emp_main_dfg_does_not_alias_independent_records():
    sample = ROOT.parent / "samples" / "emp-main.cbl"
    copies = ROOT.parent / "samples" / "copy"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        code_file=sample,
        copy_paths=[str(copies)],
        graphs=["cfg", "dfg", "overlay", "copybook"],
    )
    ctx = driver.context
    assert "WS-FLAG" not in ctx.aliases.get("EMP-ID", set())
    assert "EMP-ID" not in ctx.aliases.get("WS-FLAG", set())
    assert "WS-DATE" in ctx.aliases.get("WS-DATE-ALPHA", set())
    assert "EMP-REC" in ctx.aliases.get("EMP-ID", set())

    g = driver.views["dfg"]
    move_emp = _stmt_by_text(g, "MOVE 1 TO EMP-ID")
    move_flag = _stmt_by_text(g, "MOVE 1 TO WS-FLAG")
    add_flag = _stmt_by_text(g, "ADD 1 TO WS-FLAG")
    display = _stmt_by_text(g, "DISPLAY WS-FLAG")
    assert move_emp and move_flag and add_flag and display

    defs_of = lambda sid: {v for u, v, d in g.edges(data=True) if u == sid and d.get("type") == "def"}
    assert defs_of(move_emp) == {"data:EMP-ID", "data:EMP-REC"}
    assert defs_of(move_flag) == {"data:WS-FLAG"}
    assert "data:WS-FLAG" in defs_of(add_flag)
    assert "data:EMP-NAME" not in defs_of(add_flag)

    reaches = {(u, v, d.get("name")) for u, v, d in g.edges(data=True) if d.get("type") == "reaches"}
    assert (add_flag, display, "WS-FLAG") in reaches
    assert (move_flag, display, "WS-FLAG") in reaches



@requires_graphviz
def test_sample_combined_png_omits_def_use_fans(tmp_path):
    from cobmix.utils.graph import visualization_graph

    sample = ROOT.parent / "samples" / "emp-main.cbl"
    copies = ROOT.parent / "samples" / "copy"
    out = tmp_path / "emp-main.json"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        code_file=sample,
        copy_paths=[str(copies)],
        graphs=["cfg", "dfg", "overlay", "copybook"],
        output_file=out,
        graph_format="all",
    )
    visual = visualization_graph(driver.graph)
    etypes = {d.get("type") for _, _, d in visual.edges(data=True)}
    assert "def" not in etypes
    assert "use" not in etypes
    assert "reaches" in etypes
    assert "perform" in etypes
    assert "redefines" in etypes
    png = tmp_path / "emp-main.png"
    assert png.exists() and png.stat().st_size > 0
    dfg_png = tmp_path / "emp-main-dfg.png"
    assert dfg_png.exists() and dfg_png.stat().st_size > 0
    dot = (tmp_path / "emp-main.dot").read_text(encoding="utf-8")
    assert "MOVE 1 TO EMP-ID" in dot
    assert 'label="def"' not in dot


def test_overlay_sample_redefines_does_not_touch_other_records():
    sample = ROOT.parent / "samples" / "overlay-demo.cbl"
    driver = CombinedDriver(src_code=sample.read_text(encoding="utf-8"), graphs=["dfg", "overlay"])
    ctx = driver.context
    assert "WS-ITEM" not in ctx.aliases.get("WS-DATE-ALPHA", set())
    assert "WS-TABLE" not in ctx.aliases.get("WS-YEAR", set())
    g = driver.views["dfg"]
    move = _stmt_by_text(g, "MOVE")
    assert move
    defs = {v for u, v, d in g.edges(data=True) if u == move and d.get("type") == "def"}
    assert "data:WS-DATE-ALPHA" in defs
    assert "data:WS-DATE" in defs
    assert "data:WS-YEAR" in defs
    assert "data:WS-TABLE" not in defs
    assert "data:WS-ITEM" not in defs


def test_independent_01_records_are_not_storage_aliases():
    src = (DATA / "dfg.cbl").read_text(encoding="utf-8")
    ctx = analyze_program(src)
    assert ctx.aliases.get("WS-A") == {"WS-A"}
    assert ctx.aliases.get("WS-B") == {"WS-B"}


def test_visualization_graph_omits_def_use_fans_no_png():
    """visualization_graph() must strip def/use edges even without Graphviz."""
    from cobmix.utils.graph import visualization_graph

    sample = ROOT.parent / "samples" / "emp-main.cbl"
    copies = ROOT.parent / "samples" / "copy"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        code_file=sample,
        copy_paths=[str(copies)],
        graphs=["cfg", "dfg", "overlay", "copybook"],
    )
    visual = visualization_graph(driver.graph)
    etypes = {d.get("type") for _, _, d in visual.edges(data=True)}
    assert "def" not in etypes, "visualization_graph must not include 'def' edges"
    assert "use" not in etypes, "visualization_graph must not include 'use' edges"
    assert "reaches" in etypes
    assert "perform" in etypes
    assert "redefines" in etypes
    # Combined DOT must not have def/use labels either
    from cobmix.utils.graph import graph_to_dot
    dot_text = graph_to_dot(visual, paper_style=True)
    assert 'label="def"' not in dot_text
    assert 'label="use"' not in dot_text
    assert "MOVE 1 TO EMP-ID" in dot_text


# ---------------------------------------------------------------------------
# New tests added during comprehensive validation (test2–test5 sample programs)
# ---------------------------------------------------------------------------

def test_figurative_constants_not_in_dfg():
    """ZERO, SPACES etc. must not create spurious data nodes in the DFG."""
    # test3 uses MOVE ZERO TO GRAND-TOTAL; test2 uses VALUE SPACES
    sample = ROOT.parent / "samples" / "test3.cbl"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        graphs=["dfg"],
    )
    g = driver.views["dfg"]
    node_ids = set(g.nodes())
    assert "data:ZERO" not in node_ids, "ZERO is a figurative constant, not a data item"
    assert "data:ZEROS" not in node_ids
    assert "data:ZEROES" not in node_ids
    assert "data:SPACES" not in node_ids


def test_overlay_occurs_attribute_on_node():
    """OCCURS items must carry occurs= and depending_on= as node attributes."""
    sample = ROOT.parent / "samples" / "test5.cbl"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        graphs=["overlay"],
    )
    g = driver.views["overlay"]
    emp_entry = g.nodes.get("data:EMP-ENTRY", {})
    assert emp_entry.get("occurs") == 10, (
        f"EMP-ENTRY must carry occurs=10 on the node, got: {emp_entry.get('occurs')}"
    )


def test_overlay_group_layout_byte_offsets():
    """Child items inside a group record must have correct start offsets and sizes."""
    sample = ROOT.parent / "samples" / "test3.cbl"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        graphs=["overlay"],
    )
    g = driver.views["overlay"]
    # ITEM-RECORD: ITEM-CODE(4) + ITEM-NAME(20) + ITEM-QTY(5) + ITEM-PRICE(9) + ITEM-TOTAL(11) = 49
    assert g.nodes["data:ITEM-CODE"]["start"] == 0
    assert g.nodes["data:ITEM-CODE"]["size"] == 4
    assert g.nodes["data:ITEM-NAME"]["start"] == 4
    assert g.nodes["data:ITEM-NAME"]["size"] == 20
    assert g.nodes["data:ITEM-QTY"]["start"] == 24
    assert g.nodes["data:ITEM-PRICE"]["start"] == 29
    # PIC 9(7)V99 = 9 display chars
    assert g.nodes["data:ITEM-PRICE"]["size"] == 9
    assert g.nodes["data:ITEM-TOTAL"]["start"] == 38
    # PIC 9(9)V99 = 11 display chars
    assert g.nodes["data:ITEM-TOTAL"]["size"] == 11
    assert g.nodes["data:ITEM-RECORD"]["size"] == 49


def test_cfg_if_else_true_false_edges():
    """Nested IF/ELSE must produce true and false CFG edges for each branch."""
    sample = ROOT.parent / "samples" / "test2.cbl"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        graphs=["cfg"],
    )
    g = driver.views["cfg"]
    edge_types = [d["type"] for _, _, d in g.edges(data=True)]
    assert edge_types.count("true") >= 3,  "Expected >= 3 true edges for nested IF"
    assert edge_types.count("false") >= 3, "Expected >= 3 false edges for nested IF"
    # All three paragraphs must exist
    assert "para:MAIN-PARA" in g
    assert "para:CHECK-GRADE" in g
    assert "para:REPORT-PARA" in g
    # PERFORM edges to named paragraphs
    perform_targets = {v for u, v, d in g.edges(data=True) if d["type"] == "perform"}
    assert "para:CHECK-GRADE" in perform_targets
    assert "para:REPORT-PARA" in perform_targets


def test_dfg_compute_defs_uses():
    """COMPUTE Z = X * Y must def Z and use X, Y; must NOT use figurative constants."""
    sample = ROOT.parent / "samples" / "test3.cbl"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        graphs=["dfg"],
    )
    g = driver.views["dfg"]
    def_targets = {v for _, v, d in g.edges(data=True) if d.get("type") == "def"}
    use_targets = {v for _, v, d in g.edges(data=True) if d.get("type") == "use"}
    assert "data:ITEM-TOTAL" in def_targets,  "COMPUTE must def ITEM-TOTAL"
    assert "data:ITEM-QTY" in use_targets,   "COMPUTE must use ITEM-QTY"
    assert "data:ITEM-PRICE" in use_targets, "COMPUTE must use ITEM-PRICE"
    assert "data:ZERO" not in use_targets,   "ZERO is a figurative constant, not a use"
    assert "data:GRAND-TOTAL" in def_targets, "ADD must def GRAND-TOTAL"


def test_overlay_evaluate_redefines():
    """EVALUATE and REDEFINES work correctly in test4.cbl."""
    sample = ROOT.parent / "samples" / "test4.cbl"
    driver = CombinedDriver(
        src_code=sample.read_text(encoding="utf-8"),
        graphs=["cfg", "dfg", "overlay"],
    )
    cfg = driver.views["cfg"]
    dfg = driver.views["dfg"]
    ovl = driver.views["overlay"]

    # CFG: evaluate_statement node present
    eval_nodes = [n for n, d in cfg.nodes(data=True) if d.get("type") == "evaluate_statement"]
    assert len(eval_nodes) == 1, f"Expected 1 evaluate_statement node, got {len(eval_nodes)}"

    # DFG: COMPUTE TAX-AMOUNT = AMOUNT * TAX-RATE
    def_targets = {v for _, v, d in dfg.edges(data=True) if d.get("type") == "def"}
    use_targets = {v for _, v, d in dfg.edges(data=True) if d.get("type") == "use"}
    assert "data:TAX-AMOUNT" in def_targets
    assert "data:AMOUNT" in use_targets
    assert "data:TAX-RATE" in use_targets

    # Overlay: REDEFINES edge and shared start offset
    assert ("data:CHAR-DATA", "data:BINARY-DATA") in ovl.edges
    bd_start = ovl.nodes["data:BINARY-DATA"]["start"]
    cd_start = ovl.nodes["data:CHAR-DATA"]["start"]
    assert bd_start == cd_start, "REDEFINES: CHAR-DATA and BINARY-DATA must share start offset"


def test_redefines_aliases_function():
    """redefines_aliases() must contain only REDEFINES/RENAMES pairs, not parent-child."""
    from cobmix.tree_parser.data_layout import redefines_aliases
    from cobmix.tree_parser.context import analyze_program

    sample = ROOT.parent / "samples" / "overlay-demo.cbl"
    ctx = analyze_program(sample.read_text(encoding="utf-8"))
    rdal = redefines_aliases(ctx.items)

    # WS-DATE-ALPHA REDEFINES WS-DATE -> bidirectional alias
    assert "WS-DATE" in rdal.get("WS-DATE-ALPHA", set())
    assert "WS-DATE-ALPHA" in rdal.get("WS-DATE", set())

    # WS-YEAR is a child of WS-DATE, NOT a REDEFINES alias -> NOT in redef_aliases
    assert "WS-YEAR" not in rdal.get("WS-DATE-ALPHA", set()), (
        "redefines_aliases must not include parent-child containment"
    )
    # WS-TABLE is an independent 01-record -> NOT in redef_aliases
    assert "WS-TABLE" not in rdal.get("WS-DATE-ALPHA", set())
