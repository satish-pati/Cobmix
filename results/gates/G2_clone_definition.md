# G2 — Clone Definition

**Status:** PENDING — must be filled in BEFORE building the clone dataset.

## Definitions

### Type A — Copybook-induced clone
Two program units are copybook-induced clones if they include the same COPY book
and thereby share identical data declarations, even if their procedural logic differs.

**How detected:** Two programs both have `includes` edge to the same `copy:X` node
in the COBMix Copybook view.

### Type B — Logic clone
Two program units are logic clones if their procedural paragraphs share >= T% of
CFG/DFG path contexts, regardless of copybook sharing.

**Threshold T:** _____ (to be fixed on validation set, not test set)

## Critical Rule
Copybook-induced clones and logic clones are reported **separately** in all tables.
Pooling them is forbidden.

**Date decided:** ___________
**Decided by:** ___________
