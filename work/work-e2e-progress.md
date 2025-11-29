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
- E2E runner (`tests/e2e_runner.py`) always drives the SSA pipeline; `mode: "run"` compiles with the `ssa-llvm` backend, links with clang, and executes.
- Backend now lowers multiple SSA functions with block params/branches and simple calls (no error edges, no runtime I/O yet). `hello` and new `call_pure` run end-to-end.
- SSA-only program suite and smoke tests remain green (`just test-ssa`).
- Legacy codegen is bypassed; SSA→LLVM is the active path for run-mode e2e.

## Next steps
- Extend SSA→LLVM to cover more ops (console calls/strings, arrays/structs, error edges) and flip additional e2e cases (control_flow/for_array/etc.) to `mode: "run"`.
- Keep any unsupported e2e cases in compile mode until their features are codegen-covered.
