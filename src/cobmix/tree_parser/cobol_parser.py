from __future__ import annotations

import re
from dataclasses import dataclass

from cobmix.tree_parser.cst import Node, make_node, point_of

STATEMENT_VERBS = {
    "MOVE",
    "COMPUTE",
    "ADD",
    "SUBTRACT",
    "MULTIPLY",
    "DIVIDE",
    "PERFORM",
    "IF",
    "GO",
    "GOTO",
    "CALL",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "START",
    "SET",
    "DISPLAY",
    "STOP",
    "EXIT",
    "OPEN",
    "CLOSE",
    "ACCEPT",
    "STRING",
    "UNSTRING",
    "INITIALIZE",
    "INSPECT",
    "CONTINUE",
    "EVALUATE",
    "GOBACK",
    "RETURN",
    "SEARCH",
    "INITIALIZE",
    "NEXT",
    "SORT",
    "MERGE",
    "RELEASE",
}

END_WORDS = {
    "END-IF",
    "END-PERFORM",
    "END-EVALUATE",
    "END-READ",
    "END-SEARCH",
    "ELSE",
    "WHEN",
}

DIVISION_ROLES = {
    "IDENTIFICATION": "identification",
    "ID": "identification",
    "ENVIRONMENT": "environment",
    "DATA": "data",
    "PROCEDURE": "procedure",
}


@dataclass
class Token:
    kind: str
    value: str
    start: int
    end: int


_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_STRING = re.compile(r"(?:\"[^\"]*\"|'[^']*')")
_EQEQ = re.compile(r"==")
_PUNCT = re.compile(r"==|>=|<=|<>|\.|[(),=+\-*/<>:]")


def is_fixed_format(text: str) -> bool:
    lines = [ln.rstrip("\n") for ln in text.splitlines() if lstrip_keep(ln)]
    if not lines:
        return False
    sample = lines[:30]
    hits = 0
    for line in sample:
        prefix = line[:6] if len(line) >= 6 else line
        if prefix.strip() == "" or prefix.replace(" ", "").isdigit():
            hits += 1
    return hits >= max(2, int(0.5 * len(sample)))


def lstrip_keep(line: str) -> str:
    return line.strip()


def extract_spans(source: str) -> list[tuple[int, int]]:
    """Return (start, end) slices of executable source, skipping comments."""
    spans: list[tuple[int, int]] = []
    offset = 0
    fixed = is_fixed_format(source)
    for line in source.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        line_start = offset
        offset += len(line)
        if not raw.strip():
            continue
        if fixed and len(raw) >= 7:
            indicator = raw[6]
            if indicator in "*D/d":
                continue
            code = raw[7:72]
            rel = 7
            # keep original index for first non-space in code area
            abs_start = line_start + rel
            abs_end = line_start + min(len(raw), 72)
            if code.strip():
                spans.append((abs_start, abs_end))
            continue
        stripped = raw.lstrip()
        if stripped.startswith("*") or stripped.startswith("*>"):
            continue
        spans.append((line_start, line_start + len(raw)))
    return spans


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    for start, end in extract_spans(source):
        i = start
        while i < end:
            ch = source[i]
            if ch.isspace():
                i += 1
                continue
            m = _STRING.match(source, i, end)
            if m:
                tokens.append(Token("string", m.group(0), m.start(), m.end()))
                i = m.end()
                continue
            if source.startswith("==", i) and i + 2 <= end:
                tokens.append(Token("punct", "==", i, i + 2))
                i += 2
                continue
            m = _WORD.match(source, i, end)
            if m:
                tokens.append(Token("word", m.group(0), m.start(), m.end()))
                i = m.end()
                continue
            m = _PUNCT.match(source, i, end)
            if m:
                tokens.append(Token("punct", m.group(0), m.start(), m.end()))
                i = m.end()
                continue
            i += 1
    return tokens


class TokenStream:
    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.i = 0

    def peek(self, n: int = 0) -> Token | None:
        j = self.i + n
        if 0 <= j < len(self.tokens):
            return self.tokens[j]
        return None

    def at_end(self) -> bool:
        return self.i >= len(self.tokens)

    def next(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def match_word(self, *words: str) -> Token | None:
        tok = self.peek()
        if tok and tok.kind == "word" and tok.value.upper() in {w.upper() for w in words}:
            return self.next()
        return None

    def match_punct(self, *values: str) -> Token | None:
        tok = self.peek()
        if tok and tok.kind == "punct" and tok.value in values:
            return self.next()
        return None

    def upper(self, n: int = 0) -> str:
        tok = self.peek(n)
        return tok.value.upper() if tok else ""

    def pos(self) -> int:
        tok = self.peek()
        if tok:
            return tok.start
        if self.tokens:
            return self.tokens[-1].end
        return 0


def leaf(source: str, ntype: str, tok: Token, extra: dict | None = None) -> Node:
    return make_node(ntype, source, tok.start, tok.end, extra=extra)


class CobolParser:
    def __init__(self, source: str, filename: str = "<memory>"):
        self.source = source
        self.filename = filename
        self.ts = TokenStream(tokenize(source), source)

    def parse(self) -> Node:
        start = 0
        children: list[Node] = []
        while not self.ts.at_end():
            if self._looking_division():
                children.append(self.parse_division())
            else:
                # skip unknown tokens to stay robust on incomplete snippets
                self.ts.next()
        end = len(self.source)
        program_id = "UNKNOWN"
        for n in children:
            for pid in n.find_all("program_name"):
                program_id = pid.text.strip().rstrip(".").strip()
                break
        root = make_node("source_file", self.source, start, end, children)
        root.extra["program_id"] = program_id
        root.extra["filename"] = self.filename
        return root

    def _looking_division(self) -> bool:
        a, b = self.ts.upper(0), self.ts.upper(1)
        if a in DIVISION_ROLES and b == "DIVISION":
            return True
        return a == "ID" and b == "DIVISION"

    def parse_division(self) -> Node:
        name_tok = self.ts.next()
        self.ts.match_word("DIVISION")
        self.ts.match_punct(".")
        role = DIVISION_ROLES.get(name_tok.value.upper(), "procedure")
        start = name_tok.start
        children: list[Node] = [leaf(self.source, "division_name", name_tok)]
        if role == "identification":
            children.extend(self.parse_identification_body())
        elif role == "environment":
            children.extend(self.parse_until_next_division())
        elif role == "data":
            children.extend(self.parse_data_body())
        else:
            children.extend(self.parse_procedure_body())
        end = children[-1].end_byte if children else name_tok.end
        node = make_node("division", self.source, start, end, children, extra={"role": role})
        return node

    def parse_identification_body(self) -> list[Node]:
        nodes: list[Node] = []
        while not self.ts.at_end() and not self._looking_division():
            if self.ts.match_word("PROGRAM-ID"):
                self.ts.match_punct(".")
                name = self.ts.next()
                self.ts.match_punct(".")
                nodes.append(
                    make_node(
                        "program_id_paragraph",
                        self.source,
                        name.start,
                        name.end,
                        [leaf(self.source, "program_name", name)],
                    )
                )
            else:
                self.ts.next()
        return nodes

    def parse_until_next_division(self) -> list[Node]:
        nodes: list[Node] = []
        start = self.ts.pos()
        while not self.ts.at_end() and not self._looking_division():
            tok = self.ts.next()
            nodes.append(leaf(self.source, "environment_clause", tok))
        if not nodes:
            return []
        return [
            make_node(
                "environment_body",
                self.source,
                start,
                nodes[-1].end_byte,
                nodes,
            )
        ]

    def parse_data_body(self) -> list[Node]:
        nodes: list[Node] = []
        while not self.ts.at_end() and not self._looking_division():
            if self._looking_section():
                nodes.append(self.parse_section_header())
                continue
            if self.ts.upper() == "COPY":
                nodes.append(self.parse_copy())
                continue
            if self._looking_data_item():
                nodes.append(self.parse_data_description())
                continue
            self.ts.next()
        return nodes

    def _looking_section(self) -> bool:
        a, b, c = self.ts.upper(0), self.ts.upper(1), self.ts.upper(2)
        sections = {
            "FILE",
            "WORKING-STORAGE",
            "LOCAL-STORAGE",
            "LINKAGE",
            "COMMUNICATION",
            "REPORT",
            "SCREEN",
        }
        return a in sections and b == "SECTION" or (a == "WORKING" and b.startswith("STORAGE"))

    def parse_section_header(self) -> Node:
        start = self.ts.pos()
        name = self.ts.next()
        if name.value.upper() == "WORKING" and self.ts.upper() in {"STORAGE", "STORAGE-SECTION"}:
            # WORKING STORAGE SECTION (rare spacing)
            self.ts.next()
        self.ts.match_word("SECTION")
        end_tok = self.ts.match_punct(".")
        end = end_tok.end if end_tok else name.end
        ntype = {
            "WORKING-STORAGE": "working_storage_section",
            "LINKAGE": "linkage_section",
            "FILE": "file_section",
            "LOCAL-STORAGE": "local_storage_section",
        }.get(name.value.upper(), "data_section")
        return make_node(ntype, self.source, start, end, extra={"section": name.value.upper()})

    def _looking_data_item(self) -> bool:
        tok = self.ts.peek()
        if not tok or tok.kind != "word":
            return False
        return bool(re.fullmatch(r"\d{1,2}", tok.value))

    def parse_data_description(self) -> Node:
        level_tok = self.ts.next()
        start = level_tok.start
        children: list[Node] = [leaf(self.source, "level_number", level_tok)]
        name_tok = None
        if self.ts.peek() and self.ts.peek().kind == "word" and self.ts.upper() not in {
            "PIC",
            "PICTURE",
            "REDEFINES",
            "OCCURS",
            "VALUE",
            "USAGE",
            "IS",
            "RENAMES",
            "COPY",
        }:
            name_tok = self.ts.next()
            children.append(leaf(self.source, "entry_name", name_tok))
        extra: dict = {"level": int(level_tok.value)}
        if name_tok:
            extra["name"] = name_tok.value
        while not self.ts.at_end() and not self.ts.match_punct("."):
            if self.ts.upper() in {"PIC", "PICTURE"}:
                children.append(self.parse_picture())
            elif self.ts.upper() == "REDEFINES":
                children.append(self.parse_redefines())
            elif self.ts.upper() == "OCCURS":
                children.append(self.parse_occurs())
            elif self.ts.upper() == "RENAMES":
                children.append(self.parse_renames())
            elif self.ts.upper() == "VALUE":
                children.append(self.parse_value())
            elif self.ts.upper() in {"USAGE", "COMP", "COMP-1", "COMP-2", "COMP-3", "COMP-4", "COMP-5", "BINARY", "PACKED-DECIMAL", "DISPLAY"}:
                children.append(self.parse_usage())
            elif self.ts.upper() == "DEPENDING":
                self.ts.next()
                self.ts.match_word("ON")
                dep = self.ts.next()
                children.append(leaf(self.source, "depending_on", dep))
            else:
                self.ts.next()
        end = self.ts.tokens[self.ts.i - 1].end if self.ts.i else start
        extra["picture"] = None
        extra["usage"] = None
        extra["redefines"] = None
        extra["occurs"] = None
        extra["renames"] = None
        extra["renames_thru"] = None
        extra["value"] = None
        extra["depending_on"] = None
        for c in children:
            if c.type == "picture_clause":
                extra["picture"] = c.extra.get("picture")
            elif c.type == "redefines_clause":
                extra["redefines"] = c.extra.get("target")
            elif c.type == "occurs_clause":
                extra["occurs"] = c.extra.get("count")
                extra["depending_on"] = c.extra.get("depending_on")
            elif c.type == "renames_clause":
                extra["renames"] = c.extra.get("from")
                extra["renames_thru"] = c.extra.get("thru")
            elif c.type == "value_clause":
                extra["value"] = c.extra.get("value")
            elif c.type == "usage_clause":
                extra["usage"] = c.extra.get("usage")
            elif c.type == "depending_on":
                extra["depending_on"] = c.text
        return make_node("data_description", self.source, start, end, children, extra=extra)

    def parse_picture(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        self.ts.match_word("IS")
        pic_parts: list[str] = []
        pic_start = self.ts.pos()
        while not self.ts.at_end():
            u = self.ts.upper()
            if u in {
                "REDEFINES",
                "OCCURS",
                "VALUE",
                "USAGE",
                "COMP",
                "COMP-1",
                "COMP-2",
                "COMP-3",
                "COMP-4",
                "COMP-5",
                "BINARY",
                "PACKED-DECIMAL",
                "DISPLAY",
                "DEPENDING",
            } or self.ts.peek().kind == "punct" and self.ts.peek().value == ".":
                break
            tok = self.ts.next()
            pic_parts.append(tok.value)
        picture = "".join(pic_parts)
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "picture_clause",
            self.source,
            start,
            end,
            extra={"picture": picture},
        )

    def parse_redefines(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        target = self.ts.next()
        return make_node(
            "redefines_clause",
            self.source,
            start,
            target.end,
            [leaf(self.source, "entry_name", target)],
            extra={"target": target.value},
        )

    def parse_occurs(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        count = None
        depending = None
        if self.ts.peek() and re.fullmatch(r"\d+", self.ts.peek().value):
            count_tok = self.ts.next()
            count = int(count_tok.value)
        self.ts.match_word("TIMES")
        if self.ts.match_word("DEPENDING"):
            self.ts.match_word("ON")
            dep = self.ts.next()
            depending = dep.value
        end = self.ts.tokens[self.ts.i - 1].end
        extra = {"count": count, "depending_on": depending}
        return make_node("occurs_clause", self.source, start, end, extra=extra)

    def parse_renames(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        frm = self.ts.next()
        thru = None
        if self.ts.match_word("THRU", "THROUGH"):
            thru_tok = self.ts.next()
            thru = thru_tok.value
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "renames_clause",
            self.source,
            start,
            end,
            extra={"from": frm.value, "thru": thru},
        )

    def parse_value(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        self.ts.match_word("IS")
        val = self.ts.next()
        return make_node("value_clause", self.source, start, val.end, extra={"value": val.value})

    def parse_usage(self) -> Node:
        start = self.ts.pos()
        tok = self.ts.next()
        usage = tok.value.upper()
        if usage == "USAGE":
            self.ts.match_word("IS")
            if not self.ts.at_end():
                usage = self.ts.next().value.upper()
        return make_node("usage_clause", self.source, start, self.ts.tokens[self.ts.i - 1].end, extra={"usage": usage})

    def parse_copy(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        name = self.ts.next()
        extra: dict = {"name": name.value.strip("\"'"), "replacing": []}
        children = [leaf(self.source, "copybook_name", name)]
        if self.ts.match_word("OF", "IN"):
            lib = self.ts.next()
            extra["library"] = lib.value
        if self.ts.match_word("REPLACING"):
            while not self.ts.at_end() and not self.ts.match_punct("."):
                if self.ts.match_word("BY"):
                    continue
                old = self._copy_token_text()
                self.ts.match_word("BY")
                new = self._copy_token_text()
                extra["replacing"].append((old, new))
            end = self.ts.tokens[self.ts.i - 1].end
            return make_node("copy_statement", self.source, start, end, children, extra=extra)
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node("copy_statement", self.source, start, end, children, extra=extra)

    def _copy_token_text(self) -> str:
        if self.ts.match_punct("=="):
            parts = []
            while not self.ts.at_end() and not self.ts.match_punct("=="):
                parts.append(self.ts.next().value)
            return " ".join(parts)
        tok = self.ts.next()
        return tok.value.strip("\"'")

    def parse_procedure_body(self) -> list[Node]:
        nodes: list[Node] = []
        # optional USING / CHAINING after PROCEDURE DIVISION
        while not self.ts.at_end() and self.ts.upper() in {"USING", "CHAINING", "RETURNING"}:
            self._skip_until_period()
        while not self.ts.at_end() and not self._looking_division():
            if self.ts.upper() == "COPY":
                nodes.append(self.parse_copy())
                continue
            if self._looking_paragraph():
                nodes.append(self.parse_paragraph())
                continue
            # stray statement before first paragraph
            nodes.append(self.parse_statement())
        return nodes

    def _looking_paragraph(self) -> bool:
        tok = self.ts.peek()
        nxt = self.ts.peek(1)
        if not tok or tok.kind != "word":
            return False
        name = tok.value.upper()
        if name in STATEMENT_VERBS or name in END_WORDS or name in DIVISION_ROLES:
            return False
        if nxt and nxt.kind == "word" and nxt.value.upper() == "SECTION":
            return True
        if nxt and nxt.kind == "punct" and nxt.value == ".":
            # paragraph header if not a verb
            return name not in STATEMENT_VERBS
        return False

    def parse_paragraph(self) -> Node:
        name_tok = self.ts.next()
        start = name_tok.start
        is_section = False
        if self.ts.match_word("SECTION"):
            is_section = True
        self.ts.match_punct(".")
        children: list[Node] = [leaf(self.source, "paragraph_name", name_tok)]
        stmts: list[Node] = []
        while not self.ts.at_end() and not self._looking_division() and not self._looking_paragraph():
            if self.ts.upper() == "COPY":
                stmts.append(self.parse_copy())
                continue
            if self.ts.peek() and self.ts.peek().kind == "punct" and self.ts.peek().value == ".":
                self.ts.next()
                continue
            stmts.append(self.parse_statement())
        children.extend(stmts)
        end = children[-1].end_byte
        ntype = "section" if is_section else "paragraph"
        return make_node(
            ntype,
            self.source,
            start,
            end,
            children,
            extra={"name": name_tok.value, "is_section": is_section},
        )

    def parse_statement(self) -> Node:
        u = self.ts.upper()
        if u == "IF":
            return self.parse_if()
        if u == "EVALUATE":
            return self.parse_evaluate()
        if u == "PERFORM":
            return self.parse_perform()
        if u in {"GO", "GOTO"}:
            return self.parse_goto()
        if u == "CALL":
            return self.parse_call()
        if u == "MOVE":
            return self.parse_move()
        if u == "COMPUTE":
            return self.parse_compute()
        if u in {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"}:
            return self.parse_arithmetic()
        if u == "READ":
            return self.parse_read()
        if u == "SET":
            return self.parse_set()
        if u == "STOP":
            return self.parse_stop()
        return self.parse_generic_statement()

    def parse_if(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        cond_tokens: list[Token] = []
        while not self.ts.at_end():
            if self.ts.upper() == "THEN":
                self.ts.next()
                break
            if self.ts.upper() in STATEMENT_VERBS or self.ts.upper() in END_WORDS:
                break
            cond_tokens.append(self.ts.next())
        cond_node = None
        if cond_tokens:
            cond_node = make_node(
                "condition",
                self.source,
                cond_tokens[0].start,
                cond_tokens[-1].end,
                extra={"text": self.source[cond_tokens[0].start : cond_tokens[-1].end]},
            )
        then_stmts = self._parse_stmt_list({"ELSE", "END-IF"})
        else_stmts: list[Node] = []
        if self.ts.match_word("ELSE"):
            else_stmts = self._parse_stmt_list({"END-IF"})
        self.ts.match_word("END-IF")
        self.ts.match_punct(".")
        children = []
        if cond_node:
            children.append(cond_node)
        then_wrap = make_node(
            "then_branch",
            self.source,
            then_stmts[0].start_byte if then_stmts else start,
            then_stmts[-1].end_byte if then_stmts else start,
            then_stmts,
        )
        children.append(then_wrap)
        if else_stmts:
            children.append(
                make_node(
                    "else_branch",
                    self.source,
                    else_stmts[0].start_byte,
                    else_stmts[-1].end_byte,
                    else_stmts,
                )
            )
        end = self.ts.tokens[self.ts.i - 1].end
        cond_uses = [
            tok.value
            for tok in cond_tokens
            if tok.kind == "word"
            and re.match(r"[A-Za-z]", tok.value)
            and tok.value.upper()
            not in {
                "AND",
                "OR",
                "NOT",
                "THEN",
                "EQUAL",
                "EQUALS",
                "TO",
                "IS",
                "THAN",
                "GREATER",
                "LESS",
                "ZERO",
                "ZEROS",
                "ZEROES",
                "SPACE",
                "SPACES",
                "THROUGH",
                "THRU",
                "NUMERIC",
                "ALPHABETIC",
            }
        ]
        extra = {
            "kind": "if",
            "then": then_stmts,
            "else": else_stmts,
            "uses": cond_uses,
            "defs": [],
        }
        node = make_node("if_statement", self.source, start, end, children, extra=extra)
        return node

    def parse_evaluate(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        arms: list[tuple[str, list[Node]]] = []
        current_when = "subject"
        current_stmts: list[Node] = []
        # skip subject until first WHEN
        while not self.ts.at_end() and self.ts.upper() not in {"WHEN", "END-EVALUATE"}:
            self.ts.next()
        while not self.ts.at_end() and not self.ts.match_word("END-EVALUATE"):
            if self.ts.match_word("WHEN"):
                if current_when != "subject":
                    arms.append((current_when, current_stmts))
                other = self.ts.match_word("OTHER")
                current_when = "OTHER" if other else "WHEN"
                current_stmts = []
                # skip when condition until a verb
                while not self.ts.at_end() and self.ts.upper() not in STATEMENT_VERBS | {"WHEN", "END-EVALUATE"}:
                    if self.ts.peek() and self.ts.peek().kind == "punct" and self.ts.peek().value == ".":
                        break
                    if self.ts.upper() in STATEMENT_VERBS:
                        break
                    if self.ts.upper() not in STATEMENT_VERBS:
                        nxt = self.ts.upper()
                        if nxt in STATEMENT_VERBS or nxt in {"WHEN", "END-EVALUATE"}:
                            break
                    if self.ts.upper() in STATEMENT_VERBS:
                        break
                    # consume condition token if not a statement
                    if self.ts.upper() not in STATEMENT_VERBS and self.ts.upper() not in {"WHEN", "END-EVALUATE"}:
                        if self.ts.peek() and self.ts.peek().kind == "word" and self.ts.upper() in STATEMENT_VERBS:
                            break
                        if self.ts.upper() in STATEMENT_VERBS:
                            break
                        # stop when next is statement verb
                        if self.ts.upper() in STATEMENT_VERBS:
                            break
                        tok_u = self.ts.upper()
                        if tok_u in STATEMENT_VERBS:
                            break
                        if tok_u in {"WHEN", "END-EVALUATE"}:
                            break
                        if tok_u in STATEMENT_VERBS:
                            break
                        if self._is_stmt_start():
                            break
                        self.ts.next()
                continue
            current_stmts.append(self.parse_statement())
        if current_when != "subject":
            arms.append((current_when, current_stmts))
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        children = []
        extra_arms = []
        for label, stmts in arms:
            extra_arms.append({"label": label, "statements": stmts})
            if stmts:
                children.extend(stmts)
        return make_node(
            "evaluate_statement",
            self.source,
            start,
            end,
            children,
            extra={"kind": "evaluate", "arms": extra_arms},
        )

    def _is_stmt_start(self) -> bool:
        return self.ts.upper() in STATEMENT_VERBS

    def _at_clause_end(self) -> bool:
        if self.ts.at_end():
            return True
        tok = self.ts.peek()
        if tok and tok.kind == "punct" and tok.value == ".":
            return True
        if self.ts.upper() in STATEMENT_VERBS or self.ts.upper() in END_WORDS:
            return True
        if self._looking_division():
            return True
        return False

    def _parse_stmt_list(self, enders: set[str]) -> list[Node]:
        stmts: list[Node] = []
        while not self.ts.at_end() and self.ts.upper() not in enders and not self._looking_division() and not self._looking_paragraph():
            if self.ts.peek() and self.ts.peek().kind == "punct" and self.ts.peek().value == ".":
                # period can close a classic IF sentence
                if "END-IF" in enders:
                    break
                self.ts.next()
                continue
            stmts.append(self.parse_statement())
            # classic period-terminated IF: after first statement, if next is ELSE/END-IF/period handled by caller
            if "END-IF" in enders:
                # allow multiple statements until ender
                continue
        return stmts

    def parse_perform(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        extra: dict = {"kind": "perform"}
        children: list[Node] = []
        inline_stmts: list[Node] = []
        if self.ts.upper() in {"UNTIL", "VARYING", "WITH", "TEST"} or self.ts.upper() in STATEMENT_VERBS:
            extra["inline"] = True
            inline_stmts = self._parse_stmt_list({"END-PERFORM"})
            self.ts.match_word("END-PERFORM")
            extra["body"] = inline_stmts
            children.extend(inline_stmts)
        else:
            target = self.ts.next()
            extra["target"] = target.value
            children.append(leaf(self.source, "paragraph_name", target))
            if self.ts.match_word("THRU", "THROUGH"):
                thru = self.ts.next()
                extra["thru"] = thru.value
                children.append(leaf(self.source, "thru_paragraph", thru))
            if self.ts.match_word("UNTIL"):
                extra["until"] = True
                while not self.ts.at_end() and not (
                    self.ts.peek().kind == "punct" and self.ts.peek().value == "."
                ) and self.ts.upper() not in STATEMENT_VERBS | {"END-PERFORM"}:
                    self.ts.next()
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node("perform_statement", self.source, start, end, children, extra=extra)

    def parse_goto(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        self.ts.match_word("TO")
        target = self.ts.next()
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "goto_statement",
            self.source,
            start,
            end,
            [leaf(self.source, "paragraph_name", target)],
            extra={"kind": "goto", "target": target.value},
        )

    def parse_call(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        target = self.ts.next()
        using: list[str] = []
        if self.ts.match_word("USING"):
            while not self._at_clause_end():
                tok = self.ts.next()
                if tok.kind == "word" and tok.value.upper() not in {"BY", "REFERENCE", "CONTENT", "VALUE"}:
                    using.append(tok.value)
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "call_statement",
            self.source,
            start,
            end,
            extra={"kind": "call", "target": target.value.strip("\"'"), "using": using},
        )

    def parse_move(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        src_toks: list[str] = []
        while not self.ts.at_end() and self.ts.upper() != "TO":
            src_toks.append(self.ts.next().value)
        self.ts.match_word("TO")
        targets: list[str] = []
        children: list[Node] = []
        while not self._at_clause_end():
            tok = self.ts.next()
            if tok.kind == "word":
                targets.append(tok.value)
                children.append(leaf(self.source, "entry_name", tok))
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        source_text = " ".join(src_toks)
        extra = {
            "kind": "move",
            "uses": [s for s in src_toks if re.match(r"[A-Za-z]", s)],
            "defs": targets,
            "source_expr": source_text,
        }
        return make_node("move_statement", self.source, start, end, children, extra=extra)

    def parse_compute(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        target = self.ts.next()
        self.ts.match_punct("=")
        uses: list[str] = []
        while not self._at_clause_end() and self.ts.upper() != "END-COMPUTE":
            tok = self.ts.next()
            if tok.kind == "word" and re.match(r"[A-Za-z]", tok.value):
                uses.append(tok.value)
        self.ts.match_word("END-COMPUTE")
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "compute_statement",
            self.source,
            start,
            end,
            extra={"kind": "compute", "defs": [target.value], "uses": uses},
        )

    def parse_arithmetic(self) -> Node:
        start = self.ts.pos()
        verb = self.ts.next().value.upper()
        uses: list[str] = []
        defs: list[str] = []
        giving = False
        tokens_left: list[Token] = []
        while not self._at_clause_end():
            if self.ts.match_word("GIVING"):
                giving = True
                continue
            if self.ts.match_word("TO", "FROM", "BY", "INTO"):
                continue
            tok = self.ts.next()
            tokens_left.append(tok)
            if tok.kind == "word" and re.match(r"[A-Za-z]", tok.value):
                if giving:
                    defs.append(tok.value)
                else:
                    uses.append(tok.value)
        if not giving and uses:
            # ADD A TO B  => def B
            defs = [uses[-1]]
            uses = uses[:-1] + uses[-1:]
            # last identifier is destination for TO-form
            defs = [defs[0]]
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            f"{verb.lower()}_statement",
            self.source,
            start,
            end,
            extra={"kind": verb.lower(), "defs": defs, "uses": uses},
        )

    def parse_read(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        file_tok = self.ts.next()
        defs: list[str] = []
        uses = [file_tok.value]
        if self.ts.match_word("INTO"):
            dest = self.ts.next()
            defs.append(dest.value)
        while not self._at_clause_end():
            if self.ts.upper() in {"AT", "END", "NOT", "END-READ"}:
                break
            self.ts.next()
        # optional AT END statements skipped for CFG by treating as same node
        while not self.ts.at_end() and self.ts.upper() in {"AT", "END", "NOT", "INVALID", "KEY"}:
            self.ts.next()
        self.ts.match_word("END-READ")
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "read_statement",
            self.source,
            start,
            end,
            extra={"kind": "read", "defs": defs, "uses": uses},
        )

    def parse_set(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        defs: list[str] = []
        uses: list[str] = []
        if self.ts.peek():
            defs.append(self.ts.next().value)
        self.ts.match_word("TO", "UP", "DOWN")
        self.ts.match_word("BY")
        while not self._at_clause_end():
            tok = self.ts.next()
            if tok.kind == "word" and re.match(r"[A-Za-z]", tok.value):
                uses.append(tok.value)
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            "set_statement",
            self.source,
            start,
            end,
            extra={"kind": "set", "defs": defs, "uses": uses},
        )

    def parse_stop(self) -> Node:
        start = self.ts.pos()
        self.ts.next()
        self.ts.match_word("RUN")
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node("stop_statement", self.source, start, end, extra={"kind": "stop"})

    def parse_generic_statement(self) -> Node:
        start = self.ts.pos()
        verb_tok = self.ts.next()
        uses: list[str] = []
        while not self._at_clause_end():
            tok = self.ts.next()
            if tok.kind == "word" and re.match(r"[A-Za-z]", tok.value):
                uses.append(tok.value)
        self.ts.match_punct(".")
        end = self.ts.tokens[self.ts.i - 1].end
        return make_node(
            f"{verb_tok.value.lower()}_statement",
            self.source,
            start,
            end,
            extra={"kind": verb_tok.value.lower(), "defs": [], "uses": uses},
        )

    def _skip_until_period(self) -> None:
        while not self.ts.at_end() and not self.ts.match_punct("."):
            self.ts.next()


def parse_cobol(source: str, filename: str = "<memory>") -> Node:
    return CobolParser(source, filename).parse()
