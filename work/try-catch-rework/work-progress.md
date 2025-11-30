# Try/Catch Rework — Feature Progress

This document tracks **all changes** related to removing `try/else`, introducing the new `try/catch` expression form, and aligning SSA + MIR + backend semantics with the updated error model.
It also defines the **next phases** so this feature lands without semantic or backend drift.

---

# 1. Completed in the current pass

### Surface syntax & AST

* Removed `try/else` entirely from grammar and AST.
* Added `TryCatchExpr` with catch-arm variants.
* Parser updated to support expression-form try/catch.
* Legacy `_lower_try_expr` code removed.

### Checker / interpreter / linter

* Statement and expression try/catch checking unified.
* Catch blocks must yield a value of the same type as the attempt.
* Binder is typed as `Error`.
* Interpreter updated to support expression-form try/catch.
* Linter updated accordingly.

### SSA lowering

* SSA lowering now **threads the actual `Error` value** on error edges.
* Both expression and statement forms carry the error into the catch blocks.
* Catch binders are wired to the SSA error parameter.
* Expression-form lowering:
  * Only supports **call attempts** (honest semantics).
  * Accepts simple `Name` and `Name.Attr` callees (e.g., `foo()`, `obj.method()`).
* Statement try/catch:
  * Requires the final statement of the try body to be a `Call(...)` expression (name or name.attr).
  * Supports **multiple catch-all clauses**; each lowered to its own SSA block with `Error` + locals threaded.
  * Error dispatch still always routes to the **first** catch-all; event discrimination not implemented yet.
* SSA verifier understands `err_dest` on call terminators.
* SSA codegen trusts MIR’s `can_error` flags and asserts invariants; no backend rescanning.
* Throw lowering uses an explicit placeholder pair (no backend undef issues).

### Tests

New/updated e2e coverage:

* Invariants / misuse:
  * `call_plain_can_error`
  * `call_with_edges_non_can_error`
* Positive try/catch SSA semantics:
  * `try_call`
  * `try_call_error`
  * `try_catch`
  * `try_multi_catch`  (multi catch-all statement form)
  * `try_expr_binder`  (expr try/catch with binder)
* Negative event-specific catches (currently rejected in SSA lowering):
  * `try_event_catch_stmt`
  * `try_event_catch_expr`

All SSA tests (`mir_ssa_tests`, `ssa_check_smoke`, `ssa_programs_test`) and e2e runner cases are passing.

### Spec & docs

* Grammar dropped `try/else`.
* DMIR grammar updated.
* Try/catch expression added to language spec.
* This work log tracks phase-by-phase changes.

---

# 2. Current state of SSA lowering

## Expression form

Current `_lower_try_catch_expr`:

* Snapshots live user vars.
* Builds:
  * error block (receives the `Error` value + locals)
  * join block (result + locals)
* Emits a `Call` terminator with:
  * `dest` (value)
  * `err_dest` (Error)
  * `normal` / `error` edges
* Wires catch binder (if present) to the `Error` parameter in the error block.
* Only supports attempts that are calls with:
  * `Name` callee, e.g., `foo(x)`
  * `Name.Attr` callee, e.g., `obj.method(x)`
* Non-call attempts still yield `LoweringError` by design.

**Limitations**

* No event-specific catch arms; any `catch (MyEvent e)` or `catch(MyEvent)` currently yields `LoweringError`. This is intentional until SSA can project the event from `Error`; no fake matching or catch-all fallback will be introduced.
* Only a single catch arm is supported in the expression form (no multi-catch dispatch yet).

## Statement form

`lower_try_stmt`:

* Requires non-empty try body.
* Requires the final statement to be an `ExprStmt` wrapping a `Call(...)`:
  * Callee must be `Name` or `Name.Attr`.
* Lowers **all** catch clauses present in the source:
  * Each clause becomes a separate SSA block with params:
    * `Error` value
    * threaded live locals
  * Binder (if present) is bound to the `Error` param.
* Join block:
  * Threads live locals after the try/catch.
  * All fallthrough paths from catch blocks branch to this join with updated locals.
* Error dispatch:
  * If any clause is event-specific (`event != None`), SSA lowering currently **rejects** the construct.
  * For the remaining catch-all clauses, the call terminator’s `error` edge currently always targets the **first** catch-all block.
  * There is no event discrimination tree yet.

---

# 3. Backend & Verifier

## SSAVerifierV2

* Recognizes `err_dest` on call terminators.
* Enforces terminator structure:
  * Only calls-with-edges may define both `dest` and `err_dest`.
* Ensures def-before-use and dominance for both value and error results.
* Validates `can_error` invariants based on MIR annotations.

## SSA Codegen

* No longer rescans MIR to infer can-error; it relies on MIR’s annotations and asserts invariants:
  * No `Throw` in non-`can_error` functions.
  * No call-with-edges to non-`can_error` callees.
  * No plain call to `can_error` callees.
* Splits `{T, Error*}` return pairs correctly.
* Branches based on `err != null` and threads locals through the CFG as set up by SSA lowering.

All aligned with the current SSA lowering shape.

---

# 4. Next Phases

These phases describe the remaining work to fully finish the try/catch redesign.

---

## Phase 1 — Full try/catch semantics in SSA

*(multi-catch + event matching + binder correctness)*

### Goals

* Support **multiple catch clauses** in SSA with correct dispatch.
* Support **event-specific catches**:

  * `catch (MyEvent e) { ... }`
  * `catch(MyEvent)` with no binder
* Support catch-all fallback with predictable ordering.

### DONE (Phase 1 so far)

* SSA stmt try/catch:
  * Lowers all catch clauses.
  * Threads `Error` and locals into each catch block.
  * Supports multiple catch-all blocks.
* SSA expr try/catch:
  * Threads `Error` and binder.
  * Supports call attempts with `Name` or `Name.Attr` callees.
* Verifier recognizes `err_dest` and enforces call-with-edges invariants.
* New SSA/e2e tests:
  * `try_multi_catch`
  * `try_expr_binder`
  * `try_event_catch_stmt` (negative)
  * `try_event_catch_expr` (negative)

### Remaining (Phase 1 next steps)

* Implement **event-specific dispatch** in SSA:

  1. **Statement form (priority)**  
     * Instead of always targeting the first catch-all, introduce a dispatch path for the error edge:
       * Check the thrown error’s event (or equivalent discriminator) against each catch’s event.
       * Route to the matching catch block or a catch-all if none match.
     * Preserve current behavior for programs that only use catch-all blocks.
     * Add SSA + e2e tests:
       * `try` with `catch(MyEvent e)` and `catch { ... }` to verify correct arm chosen.

  2. **Expression form (after stmt form is stable)**  
     * Extend `_lower_try_catch_expr` to support event-specific catch arms, mirroring the stmt semantics.
     * Add small e2e cases to confirm the expression result/type is correct for both success and error paths.

* Keep event-specific catches as a compile-time error **until** the SSA dispatch is implemented and fully tested.

---

## Phase 2 — Broaden “attempt” surface for expr try/catch

*(beyond direct calls)*

### Goals

* Potentially allow richer forms of attempts, not only direct call shapes, while keeping semantics aligned with the interpreter.

### Strategy (to be decided after Phase 1)

1. **Option A (safe & narrow)**  
   * Continue to support only call-like constructs (`foo()`, `obj.method()`) as attempts.  
   * Document this explicitly in the language spec as a current limitation.

2. **Option B (full)**  
   * Introduce a dedicated SSA “try body” block that runs the entire attempt expression and surfaces errors via a single call-with-edges or throw.
   * More work, more power, but higher complexity.

### Required steps

* Decide between Option A vs B.
* If broadening beyond calls:
  * Update `_lower_try_catch_expr` to build a dedicated try-body region.
  * Ensure that any throw in that region correctly routes to the catch arm.
* Add negative tests for illegal attempt forms.
* Update the language spec to reflect supported attempts.

---

## Phase 3 — SSA becomes the primary e2e backend

*(proof that error-edge semantics hold under real execution)*

### Goals

* Run a subset of e2e programs through the SSA backend only.
* Validate end-to-end behavior for:
  * try/catch
  * throw
  * call-with-edges
  * error propagation

### Required steps

1. Identify a seed set of test programs (e.g., `throw_try`, `try_catch`, `try_multi_catch`, `array_string`).
2. Add a build target, e.g., `just test-e2e-ssa`, that:
   * Lowers via strict SSA.
   * Emits an object/binary via `ssa_codegen`.
   * Runs the binary and compares output/exit code with `expected.json`.
3. Fix any backend/SSA discrepancies found.
4. Gradually expand coverage until SSA is trusted as the main codegen path.

### Progress

- Added `--backend` override to `tests/e2e_runner.py` and a `test-e2e-ssa-subset` Just target to run SSA backend over a small subset (`hello`, `throw_try`).

---

# 5. Final Cleanup Targets

These are reserved for after the 3 phases are complete.

* Remove duplicate try-lowering logic in `lower_to_mir.py`.
* Update all spec examples to remove `try_else` remnants and align with the new SSA shape.
* Consider a general “error dispatch” MIR op if we want multi-catch dispatch to be first-class.
* Audit lifetime and scope rules for catch binders (both stmt and expr forms).
* Ensure DMIR → SSA lowering path is unified, not forked.

---

# 6. Status Summary

| Area                               | Status                                      |
| ---------------------------------- | ------------------------------------------- |
| Parser/AST                         | ✓ done                                      |
| Interpreter                        | ✓ done                                      |
| Checker                            | ✓ done                                      |
| SSA expression T/C                 | ✓ done (call-only, name/attr callees)       |
| SSA stmt T/C                       | ✓ multi catch-all, no event dispatch yet    |
| Error-edge threading               | ✓ done                                      |
| SSA verifier                       | ✓ updated                                   |
| Backend                            | ✓ invariant-driven                          |
| Multi-catch                        | ✓ catch-all only; event dispatch TODO       |
| Event-matching                     | ✗ Phase 1 (next coding step)                |
| Full attempt generalization        | ✗ Phase 2                                   |
| SSA-driven e2e                     | ✗ Phase 3                                   |
| Cleanup (docs, duplicate lowering) | pending                                     |
