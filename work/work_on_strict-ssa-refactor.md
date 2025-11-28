# Strict SSA Refactor Worklog

Purpose: track the multi-pass effort to make MIR truly SSA (single definition per SSA name) instead of “mutable locals”.

## Goals
- Each SSA name is defined exactly once (no redefinitions, no `_t` loopholes).
- User variables map to fresh SSA names on every definition/assignment.
- Block params act as φ-defs for all multi-predecessor joins (if/else, loops).
- Verifier enforces single-definition, def-before-use, and dominance with no exceptions.

## Plan (incremental passes)
1. **Introduce SSA environments in lowering**
   - Env: user name → current SSA name; SSA types: ssa name → type.
   - Apply to **all** defs: function params, `let`, assignments, and compiler temps (every temp via `fresh_ssa_name`, never reused).
   - Ban raw user names in MIR: only SSA names (`_x0`, `_t3`, …); user names live only in env/debug info. Temps don’t need to enter `env` (just `ssa_types`/operands), but all SSA names come from a single `fresh_ssa(prefix)` helper.
2. **Generalize φ via block params (all multi-pred blocks)**
   - Blocks with multiple predecessors (if/else joins, chained elses, while headers, break/continue targets, etc.) take params (fresh SSA names) for every live user local they use.
   - Edge args pass current SSA versions; params are fresh SSA ids (e.g., `_x_phi0`), and env inside a block is rebuilt from its params: `env_block(x) = param SSA name for x in that block`.
   - Compute live locals structurally from the construct (structured front-end): e.g., for if/else, locals live after the if; for while, locals live at loop entry and referenced in the loop body/cond.
3. **Verifier hardening (after 1 & 2 land)**
   - Single definition per SSA name (no `_t` escape); defining forms currently: function params, block params (phi), and `Move`/other defining instructions. Each SSA name has exactly one def-site and every defining form must flow through the “define SSA name” path in the verifier.
   - Treat block params explicitly as defs; never allow redefinition anywhere.
   - Def-before-use/dominance remain intact. For now, dominance can be approximated via forward traversal from entry (structured CFG). If/when arbitrary gotos/irreducible flow appear, switch to a proper dominator tree.
4. **Tests**
   - Keep `runtime_while_basic` unskipped; add an if/else join test.
   - Add small MIR-unit tests (straight-line, if/else φ, while loop-carried, and a negative “redefine SSA name” case) to lock invariants without full codegen.
   - Verify codegen; expect temporary breakage during refactor and fix iteratively.

## Current status
- Legacy lowering (`lower_to_mir.py`) is still the active path and remains non-SSA/mutable.
- Strict SSA scaffolding exists in parallel:
  - `lang/ssa_env.py` shares counter/types via SSAContext.
  - `lang/lower_to_mir_ssa.py` does SSA-correct params/let/assign, scaffolded if/else/while, literals, binary ops/comparisons (including string eq/neq via helper), simple calls, returns, and array indexing. Field access is not supported yet (needs real field type lookup).
  - Strict SSA verifier v2 (`lang/mir_verifier_ssa_v2.py`) pre-registers all defs (including call terminator dests), checks uses, and handles block params/terminators (including call-with-edges as terminators); hand-built SSA functions pass it. Type sanity (e.g., index integral) still relies on the checker for now; dominance checks remain TODO.
- Not yet wired into the main pipeline; tests still run against the legacy lowering/codegen.
- Remaining gaps: dominance not enforced; verifier now rejects calls-with-edges in the instruction list (must be terminators).

## Next actions
- Flesh out SSA lowering to cover more expressions (more ops beyond current string eq/neq) and wire operand uses into the verifier as new MIR ops appear.
- Add MIR unit tests (straight-line, if/else φ, while loop-carried, negative redefine) against the SSA verifier.
- Plan integration: run SSA lowering+verifier in parallel to legacy, then swap once feature-complete and tests pass.

## Notes to cover during implementation
- Function entry: params are SSA defs; entry env maps user params → their SSA names.
- Multi-return join blocks (if any) also follow the φ/param rule; otherwise emit direct returns.
