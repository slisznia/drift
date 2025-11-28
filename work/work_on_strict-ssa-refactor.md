# Strict SSA Refactor Worklog

Purpose: track the multi-pass effort to make MIR truly SSA (single definition per SSA name) instead of “mutable locals”.

## Goals
- Each SSA name is defined exactly once (no redefinitions, no `_t` loopholes).
- User variables map to fresh SSA names on every definition/assignment.
- Block params act as φ-defs for all multi-predecessor joins (if/else, loops).
- Verifier enforces single-definition, def-before-use (lexical), dominance (def block dominates use block), and CFG shape/φ arity.

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
   - Enforce def-before-use lexically within a block, dominance across blocks, reachability of all blocks, known edge targets, and φ arity (edge args vs block params).
4. **Tests**
   - Keep `runtime_while_basic` unskipped; add an if/else join test.
   - Add small MIR-unit tests (straight-line, if/else φ, while loop-carried, and negative cases: redefine, use-before-def, phi-arity mismatch, unreachable block) to lock invariants without full codegen. Add integration tests that run `lower_function_ssa` (including try/else with multiple live locals) through the verifier.
   - Verify codegen; expect temporary breakage during refactor and fix iteratively.

## Current status
- Legacy runner is deprioritized; `just test` runs the SSA-only suite (`test-ssa`). Legacy `run_tests.py` lives under `just legacy-test` and is not maintained.
- SSA pipeline:
  - `lang/ssa_env.py` shares counter/types via SSAContext.
  - `lang/lower_to_mir_ssa.py` lowers params/let/assign (now including field assignment end-to-end), if/else/while, literals, binops/comparisons (incl. string eq/neq helper), method-style calls, returns, array indexing, field access (real field types), FieldSet/ArraySet (side-effecting stores), try/else and try/catch (preludes allowed), and AST-level throw. Live-user snapshots are sorted for stable φ alignment.
  - SSA verifier v2 pre-registers all defs (including call terminator dests), checks uses with intra-block ordering + dominance, enforces call-with-edges-only-as-terminator, “terminator not in instructions,” reachability (explicit entry stored on the function), known edge targets, φ arity (including arg-free edges into param-less blocks), and requires every block to end with a terminator. Type sanity is still checker-driven.
  - SSA simplifier (`lang/mir_simplify_ssa.py`) does scalar const folding + dead pure-def cleanup; folded const types are asserted in tests.
  - Mutation model documented (`docs/mir_mutation_model.md`): SSA names are immutable scalars; FieldSet/ArraySet are side-effecting memory ops (no dest/phi), may alias, and must be treated as barriers unless alias analysis proves otherwise.
- SSA regression harness:
  - Unit/negative tests in `lang/mir_ssa_tests.py`.
  - Smoke tests in `tests/ssa_check_smoke.py` and SSA program suite in `tests/ssa_programs/*` (`tests/ssa_programs_test.py`); includes negative programs for bad fields/types.
  - All SSA runners invoke `driftc.py` with `--ssa-check --ssa-check-mode=fail --ssa-simplify` (and `SSA_ONLY=1` to bypass legacy codegen). `--dump-ssa` flag exists for debugging.

## Next actions
- Keep growing the SSA program suite with real snippets (struct mutation, exceptions, control flow) and run it under `test-ssa`; re-enable more language features only via SSA.
- Extend SSA lowering/verifier only when a real SSA test/program needs it; legacy lowering is out of scope.
- Consider enabling warn-only SSA mode in more places if broader dogfooding is useful; tests currently use fail mode.

## Caveats / reminders
- SSA path is still structurally-only; semantic/type bugs won’t be caught here. The verifier and integration tests never exercise or enforce things like bad index types, invalid field names, or mismatched call/fallback types. Those are all delegated to the checker, so any mistake wiring types in `lower_to_mir_ssa` (e.g., wrong `array_element_type`, `_lookup_field_type` misuse) will sail through the SSA suite.
- SSA lowering remains expression-limited vs the eventual surface. The scaffold still intentionally only handles the current subset: params/let/assign, if/while, literals, basic binops (incl. string eq/neq via helper), simple calls (including method-style calls), returns, array indexing, field access, try `<call> else <expr>`, statement-level try/catch (call as final stmt, preludes allowed), and AST-level throw lowering. Field/array stores exist but are modeled as in-place mutations, so SSA is not yet a safe basis for classic SSA optimizations over aggregates.

- ## Immediate next steps (flag + surface)
- Add an `--ssa-check` compiler flag: run SSA lowering + SSAVerifierV2 alongside legacy lowering; keep codegen on legacy MIR. In dev/debug, treat SSA verifier failures as hard errors; otherwise log and continue. **Implemented in `driftc.py`: `--ssa-check` runs SSA lowering/verifier for all user functions, then proceeds with legacy codegen. `--ssa-check-mode` (`fail`/`warn`) controls abort vs warn.**
- Extend SSA lowering in two slices:
  1) Writes: field/array updates (immutable rebuild or explicit store op) and add verifier operand checks for new MIR ops. (Basic FieldSet/ArraySet now exist; mutation model documented; still need to decide SSA-opt interplay.)
  2) General try/catch: pick a canonical MIR shape (error continuation + join φs) and teach the verifier about the new terminator/edges. Throw terminator/lowering exists; relaxed try/catch to allow preludes with a call as tail; still need to broaden to multiple/fallible ops in the try body and handle event/binder semantics.
- Add checker+lowering+SSA integration tests to catch wiring errors that SSA won’t see:
  - Bad index types, invalid fields.
  - Fallback type mismatch in try/else.
  - (These should fail in the checker or loudly in lowering; they’re not SSA verifier’s job but guard against mis-threaded types.)
- Add driver-level smoke test with `--ssa-check-mode=fail` (see `tests/ssa_check_smoke.py`) to prove SSA runs on a tiny real program; extend SSA lowering/tests as that example grows.
- Build SSA-only regression suite under `tests/ssa_programs/*` and a runner `tests/ssa_programs_test.py` to compile them under `--ssa-check-mode=fail`; `test-ssa` runs SSA unit + smoke + program suite. Legacy runner is deprioritized/kept separate.
- Add an SSA simplification pass (const folding, dead SSA removal) behind a flag and test it.
- Document MIR mutation model explicitly: SSA names are immutable scalars; FieldSet/ArraySet are side-effecting memory ops (no dest, never φ sources), may alias, and must be treated as barriers by SSA optimizations unless alias/memory analysis proves otherwise. **Documented in docs/mir_mutation_model.md and code comments.**
- Add MIR/unit tests that exercise `FieldSet`/`ArraySet` shapes to pin operand threading and env interactions; current suite doesn’t hit the new store ops.
- Decide and document the mutation model in SSA MIR: current `FieldSet`/`ArraySet` mutate in place (not SSA-pure). Before running SSA-based optimizations, define how mutating ops interact with the SSA model (fresh aggregates vs explicit memory).

## Notes to cover during implementation
- Function entry: params are SSA defs; entry env maps user params → their SSA names.
- Multi-return join blocks (if any) also follow the φ/param rule; otherwise emit direct returns.
