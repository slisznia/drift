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
- `_t*` reserved in checker; verifier still allows reassign/redeclare (needs tightening).
- Lowering threads user locals in loops but reuses names (non-SSA); temps can be reused.
- Need to implement passes 1–3; tests currently green except skipped cases.
- SSA scaffolding added: `lang/ssa_env.py` now shares counter/types via SSAContext; `lang/lower_to_mir_ssa.py` does SSA-correct params/let/assign and a scaffolded if/else with block params; strict-SSA verifier skeleton is in `work/mir_verifier_ssa_skeleton.py` for future integration.

## Next actions
- Implement SSA env + fresh naming for params/lets/assignments/temps; ban raw user names in MIR.
- Switch block params/edges to carry SSA names (fresh params) for all multi-pred blocks; rebuild env per block.
- After lowering emits unique names, tighten verifier to single-definition (remove `_t` loophole).
- Add/enable tests: runtime_while_basic, if/else join, small MIR unit cases.

## Notes to cover during implementation
- Function entry: params are SSA defs; entry env maps user params → their SSA names.
- Multi-return join blocks (if any) also follow the φ/param rule; otherwise emit direct returns.
