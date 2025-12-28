# Function pointer values (`fn(...) returns T`) — work-progress

## Goal
Add first-class **non-capturing** function values (function pointers) with a
dedicated type form, consistent with Drift’s two-world callable model and
effect-based throw ABI.

## Pinned decisions (must match spec + implementation)
- Two callable worlds:
  - **Capturing closures**: closure values (may borrow captures, non-escaping).
  - **Function pointers**: **no captures**, safe to store/return.
- `TypeKind.FUNCTION` carries **throw mode**:
  - `CAN_THROW` vs `NOTHROW` (effect qualifier, not return type).
  - `fn(...) returns T` defaults to `CAN_THROW`.
  - `fn(...) returns T nothrow` is `NOTHROW`.
- Function values are **positional-only** for MVP: kwargs on function values are
  a hard error.
- Function reference throw mode:
  - **exported/extern** functions → `CAN_THROW` function value (always).
  - **internal** functions → use existing can-throw analysis/metadata.
  - captureless lambdas → use can-throw analysis of the body.
- Coercions:
  - `NOTHROW` function value can coerce to `CAN_THROW` via thunk
    (wrap in `Ok(...)` / `FnResult::Ok`).
  - `CAN_THROW` → `NOTHROW` is rejected.
  - captureless lambda → function pointer allowed.
  - capturing lambda → function pointer rejected.
- Call lowering must be target-aware:
  - Carry `CallTarget.Direct(SymbolId)` or `CallTarget.Indirect(value)` at the call site.
  - `CallTarget.Direct` stores a **canonical** `FunctionId` (no raw name strings).
  - MIR `Call` carries `can_throw`; codegen must use it (no FnInfo-based ABI guessing).
  - MIR calls should be `Call(target, args, CallSig)`; no name-based re-resolution in lowering.
- `call_abi_ret_type(CallSig)` must use a single canonical `Error` TypeId resolved from the core/prelude.

## Plan (detailed)
1) **Type system + parser** (partial)
   - Add `TypeKind.FUNCTION` payload with `fn_throws`.
   - Parse `fn(...) returns T [nothrow]` in type positions.
   - Serialize/deserialize `fn_throws` in type tables.
2) **Type keys + equality**
   - Ensure function types compare by `(params, ret, throw_mode)`.
   - Update any TypeKey or trait/type-id keys to include `throw_mode`.
3) **Function references (values)**
   - Allow `val f: fn(...) returns T = name` with typed-context resolution.
   - Ambiguous overload set without expected type → hard error.
   - Support explicit cast: `cast<T>(expr)` (e.g., `cast<fn(...) returns T>(name)`).
4) **Function value calls**
   - Support call-by-value (HIR/MIR): `f(...)` where `f: fn(...) returns T`.
   - Enforce positional-only args (kwargs error).
   - Validate throw-mode in call lowering and result typing.
   - Lower using `CallTarget` + `CallSig` (no name-based fallback).
   - Cut over Stage2 direct-call lowering to `CallInfo` immediately (remove `_callee_is_can_throw(name)` path).
5) **Throw-mode ABI**
   - `CAN_THROW` function values lower to indirect calls returning `FnResult<T>`.
   - `NOTHROW` function values lower to indirect calls returning `T`.
   - Generate wrappers when coercing `NOTHROW` → `CAN_THROW`.
6) **Closures → function pointer coercion**
   - If lambda captures nothing, allow coercion to `fn(...) returns T`.
   - If lambda captures anything, reject.
7) **Non-retaining analysis + borrow validation**
   - Include `TypeKind.FUNCTION` in callback-like detection.
   - Do **not** apply “borrowed-capture closure” restrictions to function values.
8) **Docs + grammar alignment**
   - Update `docs/design/drift-lang-grammar.md` with `fn(...) returns T nothrow`.
   - Update `docs/design/drift-lang-spec.md` to match throw-mode type syntax.
9) **Tests**
   - Stage1 parsing/typing (before MIR/SSA/LLVM):
     - Parse `fn(...) returns T [nothrow]` and validate `fn_throws` on `TypeExpr`.
     - `_pretty_type_name` renders `fn(...) returns T [nothrow]`.
     - Structural identity: same `fn` type built via distinct paths reuses the same TypeId.
     - Unification rejects throw-mode mismatches; nothrow → can-throw behavior is explicit.
     - Captureless lambda → `fn` coercion success; capturing lambda → error.
     - Value call typing emits `HInvoke` + positional-only rule (kwargs error).
     - Direct calls also carry CallSig/CallTarget (typed HIR), not name lookups.
     - Function reference uses wrapper symbol for exported/extern (CAN_THROW).
     - `call_abi_ret_type` uses canonical core `Error` TypeId (FnResult uses core error).
     - Trait impl matching respects function throw-mode.
   - Later-stage: MIR/SSA/LLVM indirect calls for NOTHROW vs CAN_THROW.
10) **`nothrow` on function definitions**
   - Parse `fn ... returns T nothrow` on definitions (incl. impl methods).
   - Thread `declared_nothrow` into signatures as `declared_can_throw=False`.
   - Enforce: explicit nothrow rejects bodies that may throw.
   - Update spec/grammar + add parser and integration tests.

## Status
- Step 1: **done** (type/core + parser changes landed).
- Step 2: **done** (function type interning + linker key fixed).
- Step 3: **in progress**
  - ✅ HFnPtrConst/MFnPtrConst IR plumbing (HIR/MIR/LLVM).
  - ✅ Typed-context function reference resolution in type checker.
  - ✅ Basic function reference tests (typed context, ambiguity, exported can-throw).
  - ✅ Stage2 + LLVM tests for FnPtrConst lowering.
  - ✅ Explicit `cast<T>(expr)` for function-reference disambiguation (fn types only).
- Step 4: **in progress**:
  - ✅ NodeId assigned in stage1 HIR; typed side tables keyed by NodeId.
  - ✅ CallInfo/CallSig recorded for direct calls; Stage2 HCall uses CallInfo (no name-based throw lookup).
  - ✅ CallTarget.Direct uses canonical `FunctionId` in CallInfo.
  - ✅ MIR `Call` includes `can_throw`; LLVM lowering uses it instead of `FnInfo.declared_can_throw`.
  - ✅ Method calls now record CallInfo in stage1; Stage2 method lowering uses CallInfo (no name-based can-throw).
  - ✅ HInvoke + indirect call lowering (CallIndirect in MIR + LLVM).
- Step 5: **done**
  - ✅ NOTHROW → CAN_THROW thunk generation for function values (Ok-wrap thunks).
- Step 6: **done**
  - ✅ Captureless lambda → function pointer coercion; capturing lambda rejection.
- Step 7: **done**
  - ✅ TypeKind.FUNCTION included in non-retaining analysis; borrow gating excludes function values.
- Step 8: **done**
  - ✅ Grammar + spec aligned with `fn(...) returns T nothrow` and `cast<T>(expr)`.
- Step 9: **in progress**
  - ✅ Stage1 tests: NodeId determinism, NodeId-keyed typed tables, CallInfo for direct calls, CallSig ABI return check.
  - ✅ Stage1 tests: canonical Error TypeId across modules in a single workspace build.
  - ✅ Stage2 tests: missing CallInfo hard-fails; direct call ABI return types verified.
  - ✅ Tests for HInvoke/CallIndirect (stage1 + stage2).
  - ✅ Stage1 tests for function references (typed-context, ambiguity, exported can-throw).
  - ✅ Wrapper/impl selection test for cross-module exported function references.
  - ✅ Stage1 tests: nothrow→can-throw thunk selection + captureless/capturing lambda coercion.
  - ✅ Stage2 tests: synthetic thunk + captureless lambda functions emitted in MIR.
  - ✅ Codegen e2e tests for fnptr refs/cast/thunks/lambdas/cross-module wrappers (runtime + diagnostics).
  - ✅ Codegen e2e tests for nothrow defs + boundary-call handling (direct throw, throwing call, try/catch ok, same-module pub ok, can-throw→nothrow fnptr reject).
  - ⏸️ Cross-module method boundary enforcement e2e is skipped pending method-call wrappers for can-throw ABI.
  - ⏸️ Codegen e2e for fnptr parameter overload/instantiation moved to `__pending_*` (LLVM lacks function-type params in signatures).
- Step 10: **done**
  - ✅ Parse `nothrow` on function definitions and propagate to signatures.
  - ✅ Enforce explicit nothrow on throwing bodies.
  - ✅ Parser + integration tests for nothrow definitions.
- Tri-state `fn_throws` refactor:
  - ✅ Phase 1: added `can_throw()` helpers and migrated logic to use them (raw tri-state preserved for serialization).
  - ✅ Phase 2: switched storage to 2-state (`fn_throws: bool`), updated constructors/decoders, and refreshed tests.

## Recent fixes (test stabilization)
- Prelude call resolution: register unqualified `lang.core` aliases in `CallableRegistry` for `print/println/eprintln`.
- Try/catch + match scoping: bind catch/try-expr binders and type arm results in the same scope as arm blocks.
- Qualified ctor instantiation: use variant base id when re-instantiating generic variant returns.
- Ref-return provenance: reuse HIR param binding ids and seed ref-origin for ref params before body typing.
- Builtin string calls: `string_eq` / `string_concat` now typecheck as builtins.
- Emit-package pipeline: include external signatures when lowering so package calls record CallInfo (fixes missing CallInfo for external `mod::fn` calls).
- Captureless lambda function ids include the enclosing function symbol to avoid cross-function collisions; added regression test.
- Package TypeExpr codec now preserves function type `can_throw` (nothrow) across encode/decode.
- Non-`fn` TypeExpr/GenericTypeExpr now normalize `fn_throws` to `False` (invariant), with decode enforcing the same rule.
- `fn` TypeExpr/GenericTypeExpr now require `fn_throws` to be a bool (invalid values raise).
- `resolve_opaque_type` now rejects `fn_throws=None` when explicitly provided.
- Package decoders now reject explicit null throw-mode (`can_throw: null` / `fn_throws: null`) for `fn` types.
- Entry point validation now requires exactly one `main` and enforces `main` be declared `nothrow` when codegen/emit is requested.
- Entry point validation now rejects missing `main` and enforces `main` return type `Int`.
- Entry point restriction now applies only to free functions in dependencies; methods named `main` are allowed.
- Catch event arms now accept unqualified event names (resolved to the current module); grammar + spec updated.

## Out of scope (this branch)
- Method references / bound `self` function values.
- Implicit CallableDyn wrapping for function pointers.
- Full function-type inference without typed context.
- Keyword args for function values.
