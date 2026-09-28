# G3 — Baseline Set

**Status:** LOCKED — do not change after any model run begins.

## Baselines

### C0 — Structureless baseline
- **Model:** Cobol2Vec-style token autoencoder (sequence-to-sequence over COBOL tokens).
- **Alternative:** If Cobol2Vec is not publicly reproducible, use a frozen CodeBERT encoder
  fine-tuned on COBOL tokens. Record which variant is used in `machine_spec.txt`.
- **Purpose:** Measures the floor — no structural information at all.

### C1 — Standard views baseline
- **Views:** AST + CFG + DFG (the standard three used in Mocktail and COMEX for C/Java).
- **Model:** Identical path-attention pipeline as all other conditions.
- **Purpose:** Isolates the value of COBOL-specific views over generic structure.

### C2, C3, C4 — Incremental ablations
- C2: AST + CFG + DFG + Overlay
- C3: AST + CFG + DFG + Copybook
- C4: AST + CFG + DFG + Division

### C5 — Full COBMix
- **Views:** AST + CFG + DFG + Overlay + Copybook + Division
- **Purpose:** The proposed representation.

## What each comparison isolates
| Comparison | Isolates |
|---|---|
| C5 vs C0 | Value of all structure over no structure |
| C5 vs C1 | Value of COBOL-specific views over generic structure |
| C2 vs C1 | Value of Overlay alone |
| C3 vs C1 | Value of Copybook alone |
| C4 vs C1 | Value of Division alone |

**Date locked:** ___________
**Locked by:** ___________
