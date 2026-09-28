# COBMix view definitions

Node and edge types for each extractor view. Ablations should add or remove a whole view, not a subset of its edge kinds.

## AST

- **Nodes:** named syntax nodes from the COBOL CST (punctuation and implicit tokens dropped).
- **Edges:** `ast` — parent to child.
- **Construct:** the program grammar (divisions, data descriptions, statements).

## CFG

- **Nodes:** `para:{name}` paragraph/section headers and `stmt:{id}` procedure statements.
- **Edges:**
  - `next` — sequential control inside a paragraph
  - `true` / `false` — IF / EVALUATE arms
  - `perform` — PERFORM to a paragraph (return is `next` after the PERFORM once the target finishes)
  - `thru` — PERFORM THRU chain between paragraphs
  - `goto` — GO TO
  - `call` — CALL to a nested program or stub
- **Construct:** PROCEDURE DIVISION control flow.

## DFG

- **Nodes:** the CFG statement nodes plus `data:{name}` data names.
- **Edges:** `reaches` from a defining statement to a using statement (via the data name when combined); `def` / `use` from statement to data name.
- **Construct:** MOVE, COMPUTE, arithmetic, READ INTO, SET, and overlay aliases.

## Copybook

- **Nodes:** `prog:{id}`, `copy:{name}`, and `data:{name}` declared in the copybook.
- **Edges:** `includes` (program → copybook), `declares` (copybook → data name).
- **Construct:** COPY. The same copybook identity is one node; missing books are stubs with `unresolved=true`.

## Overlay

- **Nodes:** `data:{name}` (FILLER kept as `data:FILLER#{n}`).
- **Edges:** `contains` (level hierarchy), `redefines`, `occurs`, `renames`.
- **Construct:** level numbers, REDEFINES, OCCURS, RENAMES.

## Division role

- **Nodes:** the same AST / CFG / data nodes, plus `division:{role}` where role is `identification`, `environment`, `data`, or `procedure`.
- **Edges:** `in_division`.
- **Attribute:** every retained node has `role` set to exactly one of those four, inherited from the enclosing division (COPY inherits the include site).
