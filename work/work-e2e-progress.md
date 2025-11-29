# SSA-first e2e (restore end-to-end)

## Scope
- E2E tests must drive the SSA pipeline all the way to an object file (and runtime execution when enabled). Legacy lowering/codegen is deprecated; e2e focuses on SSA MIR → LLVM → runtime.

## Plan
1) Lower SSA MIR to the LLVM backend
   - Teach the LLVM emitter to consume SSA `mir.Function` (blocks/params/terminators), mapping SSA types to LLVM types.
   - Cover the SSA ops we support: ArrayLen, FieldGet/FieldSet, ArrayGet/ArraySet, Call with/without edges, Throw/try edges, Console I/O, etc.
   - Preserve the current `{T, Error*}` ABI and existing string/array/struct layouts and runtime calls.
   - Control flow: translate block params/edge args into PHI-like constructs; ensure call-with-edges/Throw terminate correctly.
   - Treat side-effect ops (stores, calls, console) as barriers; no reordering across them yet.

2) Drive SSA from `driftc`
   - Pipeline when SSA is on (eventually unconditionally): parse/type-check → SSA lowering → simplifier → SSA verifier → SSA→LLVM → write object.
   - Drop legacy `lower_to_mir`/legacy verifier from the default path; keep only under `legacy-test` if needed.

3) Minimal runtime/linking
   - Reuse existing C stubs (string/console/error/array).
   - Link with clang-15; export `main` as before.
   - Update e2e runner to drop `SSA_ONLY` for run-mode cases and actually link/run binaries.

4) Tests
   - Flip `tests/e2e/hello` to `mode: "run"` and get it to compile/link/run via SSA→LLVM.
   - Once green, flip `control_flow` and `for_array` to `mode: "run"`.
   - Keep other e2e cases in `mode: "compile"` until their surface area is codegen-covered.

5) Incrementally expand codegen coverage
   - Add LLVM lowering for remaining SSA ops as needed: ArrayLen (len field), FieldGet/FieldSet (struct layout), ArrayGet/ArraySet, try/catch/throw (error edges via `{T, Error*}`), borrows/refs (erase to pointers or chosen ABI).
   - Keep the simplifier optional; rerun SSA verifier after any SSA transformations.

## Current status
- E2E runner exists (`tests/e2e_runner.py`); all cases currently `mode: "compile"` except `hello` (set to `mode: "run"` but skipped because runtime is not yet wired).
- SSA-only program suite and smoke tests remain green (`just test-ssa`).
- Legacy codegen bypassed in `driftc.py`; object files are stubbed out when SSA_ONLY is set.

## Next steps
- Implement SSA→LLVM lowering for the current SSA surface.
- Enable run-mode in the runner by removing `SSA_ONLY` when mode is `"run"` and wiring link/execute; get `hello` passing as a true run test, then promote `control_flow` and `for_array` to run mode.
- Leave other e2e cases in compile mode until their features are supported in codegen.
