# Try/Catch Rework — Feature Progress

This document tracks **all changes** related to removing `try/else`, introducing the new `try/catch` expression form, and aligning SSA + MIR + backend semantics with the updated error model.
It also defines the **next phases** so this feature lands without semantic or backend drift.
:contentReference[oaicite:0]{index=0}

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
  * Error dispatch still always routes to the **first** catch-all; **no event discrimination yet**.
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
* Negative event-specific catches (intentionally rejected in SSA lowering):
  * `try_event_catch_stmt`
  * `try_event_catch_expr`  
    → these assert **compile-time errors** and will remain negative until proper event projection & dispatch exist.

All SSA tests (`mir_ssa_tests`, `ssa_check_smoke`, `ssa_programs_test`) and e2e runner cases are passing.

### Spec & docs

* Grammar dropped `try/else`.
* DMIR grammar updated.
* Try/catch expression added to language spec.
* This work log tracks phase-by-phase changes.
* Docs now explicitly state:
  * Event-specific catches are **intentionally unsupported** in SSA until there is a real Error→event projection.
  * No fake event matching or disguised catch-all behavior will be introduced.

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

* No event-specific catch arms; any `catch (MyEvent e)` or `catch(MyEvent)` currently yields `LoweringError`.  
  This is **intentional** until SSA can project the event from `Error`; no fake matching or catch-all fallback will be introduced.
* Only a single catch arm is supported in the expression form (no multi-catch dispatch yet).
* Runtime/SSA now exposes a placeholder `ErrorEvent` projection (via `drift_error_get_code`) to unblock future event dispatch work; semantics still to be defined.

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

We break Phase 1 into two subphases:

- **Phase 1a:** Error event projection in MIR/SSA (plumbing only).  
- **Phase 1b:** Event-based dispatch using that projection.

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
* Event-specific catches are **explicitly documented** as unsupported (compile-time error) until we have a real Error→event projection.

---

### Phase 1a — Error event projection in MIR/SSA (subphase)

**Goal:** introduce a real, first-class way for MIR/SSA to **read the event** from an `Error` value, without changing language surface or try/catch semantics yet.

#### Tasks

1. **Define the projection primitive in MIR**

   * Decide the minimal surface:

     * Either a dedicated instruction, e.g.:

       ```python
       @dataclass(frozen=True)
       class ErrorGetEvent(Instruction):
           dest: Value
           error: Value
           loc: Location = Location()
       ```

     * Or a well-defined use of existing machinery (e.g., `FieldGet` on an `Error` struct’s `event` field) if `Error` is already a known struct in MIR.

   * Update `lang/mir.py` with this primitive and ensure it’s wired into any visitors/printers you have.

2. **Teach SSA lowering to emit the projection**

   * Add a small helper in `lower_to_mir_ssa.py`:

     ```python
     def ssa_read_error_event(err_ssa: str, env: SSAEnv, loc: Location) -> str:
         # produce a new SSA name that holds the event value (probably a String)
         ...
     ```

   * This helper should emit the new `ErrorGetEvent` (or equivalent FieldGet chain) into the current block and return the dest SSA name.

   * For now, this helper is **not** used by try/catch lowering; it just exists and is testable.

3. **Backend support for the projection**

   * Extend `ssa_codegen.py` to lower `ErrorGetEvent` (or your chosen representation) to LLVM IR:

     * Map it to whatever representation your runtime uses for `Error`:
       * If `Error` is a struct with an `event` field, generate a GEP + load.
       * If it’s an opaque pointer, call a small C helper like `error_get_event(Error* err)`.

   * Update / create a C runtime stub (e.g., in `tests/mir_codegen/runtime/error_dummy.c`) to provide the function or struct definition needed.

4. **Tests for the projection primitive itself**

   * Add a minimal SSA/MIR unit test that:
     * Builds an `Error` with a known event (or uses a dummy), calls `ErrorGetEvent`, and checks that the value is plumbed through correctly in LLVM IR (at least structurally).
   * At this stage you can still avoid wiring it into try/catch; the point is to validate IR and codegen behavior for the primitive.

5. **Docs / progress**

   * Update this doc:
     * Mark Phase 1a as “in progress” or “done” as you complete the above.
     * Keep event-specific catches negative; this subphase only enables *reading* the event, not dispatch.

**Important:**  
Phase 1a does **not** flip any event-catch tests. `try_event_catch_stmt` and `try_event_catch_expr` remain negative. No catch behavior changes yet.

---

### Phase 1b — Event-based dispatch in SSA

**Goal:** once Phase 1a is done, use the new Error→event projection to implement **real event-based dispatch** in stmt/expr try/catch.

#### Tasks

1. **Statement form (priority)**

   * In `lower_try_stmt`:
     * Partition `stmt.catches` into event-specific vs catch-all.
     * Introduce a dispatch block that:
       * Takes `(err, locals…)` as params.
       * Uses `ssa_read_error_event(err, ...)` to read the event.
       * Compares against each event-specific catch in source order.
       * Branches to the matching catch block (with `[err, locals]`).
       * Falls back to the first catch-all if no event matches.
       * Optionally rethrows if there is no catch-all and no event matches.

   * Wire the call’s `error` edge to the dispatch block instead of a catch block.

   * Turn `try_event_catch_stmt` into a **positive** test:
     * Check that `catch(MyEvent e)` is taken when event == `MyEvent`.
     * Check that catch-all handles mismatched events.

2. **Expression form**

   * Once stmt dispatch is stable:
     * Decide whether expression try/catch supports multiple arms or stays single-arm-only.
     * If multiple:
       * Mirror the stmt dispatch logic via a similar dispatch block feeding expression catch blocks that each produce a value.
     * If single:
       * Either:
         * Allow only event-less catch (catch-all), or
         * Allow a single event-specific catch and use `ErrorGetEvent` to assert the event, rethrow otherwise.

   * Turn `try_event_catch_expr` into a **positive** test.

3. **Finalize Phase 1 status**

   * When both stmt and expr forms have working event-based dispatch and positive tests, mark Phase 1 as complete.
   * Docs: update to say event-specific catches are now supported under SSA.

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
2. Use `tests/e2e_runner.py` with `--backend=ssa-llvm` and a Just target like `test-e2e-ssa-subset` to:
   * Lower via strict SSA.
   * Emit an object/binary via `ssa_codegen`.
   * Run the binary and compare output/exit code with `expected.json`.
3. Fix any backend/SSA discrepancies found.
4. Gradually expand coverage until SSA is trusted as the main codegen path.

### Progress

* `tests/e2e_runner.py` accepts `--backend` and case filters. :contentReference[oaicite:1]{index=1}  
* Justfile includes `test-e2e-ssa-subset` that runs `hello` and `throw_try` via SSA backend.
* Added `ErrorEvent` projection wired to `drift_error_get_code` and a dedicated SSA test to ensure it codegens end-to-end.

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

| Area                               | Status                                              |
| ---------------------------------- | --------------------------------------------------- |
| Parser/AST                         | ✓ done                                              |
| Interpreter                        | ✓ done                                              |
| Checker                            | ✓ done                                              |
| SSA expression T/C                 | ✓ done (call-only, name/attr callees)               |
| SSA stmt T/C                       | ✓ multi catch-all, no event dispatch yet            |
| Error-edge threading               | ✓ done                                              |
| SSA verifier                       | ✓ updated                                           |
| Backend                            | ✓ invariant-driven                                  |
| Phase 1a: Error event projection   | ◔ planned (next concrete coding step)              |
| Phase 1b: Event-based dispatch     | ✗ blocked on Phase 1a                               |
| Multi-catch                        | ✓ catch-all only; event dispatch TODO               |
| Event-matching                     | ✗ Phase 1b                                          |
| Full attempt generalization        | ✗ Phase 2                                           |
| SSA-driven e2e                     | ◔ subset wired (`hello`, `throw_try`)               |
| Cleanup (docs, duplicate lowering) | pending                                             |
