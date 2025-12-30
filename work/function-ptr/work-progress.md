# Function pointer values (`fn(...) [nothrow] returns T`) — work-progress

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
  - `fn(...) [nothrow] returns T` defaults to `CAN_THROW` when `nothrow` is omitted.
  - `fn(...) [nothrow] returns T` is `NOTHROW` when `nothrow` is present.
- Function type syntax places `nothrow` before `returns`:
  - `fn(P...) [nothrow] returns R`.
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
   - Parse `fn(...) [nothrow] returns T` in type positions.
   - Serialize/deserialize `fn_throws` in type tables.
2) **Type keys + equality**
   - Ensure function types compare by `(params, ret, throw_mode)`.
   - Update any TypeKey or trait/type-id keys to include `throw_mode`.
3) **Function references (values)**
   - Allow `val f: fn(...) [nothrow] returns T = name` with typed-context resolution.
   - Ambiguous overload set without expected type → hard error.
   - Support explicit cast: `cast<T>(expr)` (e.g., `cast<fn(...) [nothrow] returns T>(name)`).
4) **Function value calls**
   - Support call-by-value (HIR/MIR): `f(...)` where `f: fn(...) [nothrow] returns T`.
   - Enforce positional-only args (kwargs error).
   - Validate throw-mode in call lowering and result typing.
   - Lower using `CallTarget` + `CallSig` (no name-based fallback).
   - Cut over Stage2 direct-call lowering to `CallInfo` immediately (remove `_callee_is_can_throw(name)` path).
5) **Throw-mode ABI**
   - `CAN_THROW` function values lower to indirect calls returning `FnResult<T>`.
   - `NOTHROW` function values lower to indirect calls returning `T`.
   - Generate wrappers when coercing `NOTHROW` → `CAN_THROW`.
6) **Closures → function pointer coercion**
   - If lambda captures nothing, allow coercion to `fn(...) [nothrow] returns T`.
   - If lambda captures anything, reject.
7) **Non-retaining analysis + borrow validation**
   - Include `TypeKind.FUNCTION` in callback-like detection.
   - Do **not** apply “borrowed-capture closure” restrictions to function values.
8) **Docs + grammar alignment**
   - Update `docs/design/drift-lang-grammar.md` with `fn(...) [nothrow] returns T`.
   - Update `docs/design/drift-lang-spec.md` to match throw-mode type syntax.
9) **Tests**
   - Stage1 parsing/typing (before MIR/SSA/LLVM):
     - Parse `fn(...) [nothrow] returns T` and validate `fn_throws` on `TypeExpr`.
     - `_pretty_type_name` renders `fn(...) [nothrow] returns T`.
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
   - Parse `fn ... [nothrow] returns T` on definitions (incl. impl methods).
   - Thread `declared_nothrow` into signatures as `declared_can_throw=False`.
   - Enforce: explicit nothrow rejects bodies that may throw.
   - Update spec/grammar + add parser and integration tests.

## Status
- Step 1: **done** (type/core + parser changes landed).
- Step 2: **done** (function type interning + linker key fixed).
- Step 3: **done**
  - ✅ HFnPtrConst/MFnPtrConst IR plumbing (HIR/MIR/LLVM).
  - ✅ Typed-context function reference resolution in type checker.
  - ✅ Basic function reference tests (typed context, ambiguity, exported can-throw).
  - ✅ Stage2 + LLVM tests for FnPtrConst lowering.
  - ✅ Explicit `cast<T>(expr)` for function-reference disambiguation (fn types only).
- Step 4: **done**:
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
- ✅ Grammar + spec aligned with `fn(...) [nothrow] returns T` and `cast<T>(expr)`.
- Step 9: **done**
  - ✅ Stage1 tests: NodeId determinism, NodeId-keyed typed tables, CallInfo for direct calls, CallSig ABI return check.
  - ✅ Stage1 tests: canonical Error TypeId across modules in a single workspace build.
  - ✅ Stage2 tests: missing CallInfo hard-fails; direct call ABI return types verified.
  - ✅ Tests for HInvoke/CallIndirect (stage1 + stage2).
  - ✅ Stage1 tests for function references (typed-context, ambiguity, exported can-throw).
- ✅ Wrapper/impl selection test for cross-module exported function references.
- ✅ Wrapper selection test for cross-module method calls (CallInfo targets wrapper FunctionId).
- ✅ Wrapper selection test for cross-package method calls (driver test uses package signatures + impl headers).
  - ✅ Stage1 tests: nothrow→can-throw thunk selection + captureless/capturing lambda coercion.
  - ✅ Stage2 tests: synthetic thunk + captureless lambda functions emitted in MIR.
  - ✅ Codegen e2e tests for fnptr refs/cast/thunks/lambdas/cross-module wrappers (runtime + diagnostics).
  - ✅ Codegen e2e tests for nothrow defs + boundary-call handling (direct throw, throwing call, try/catch ok, same-module pub ok, can-throw→nothrow fnptr reject).
  - ✅ Cross-module method boundary enforcement e2e re-enabled (stub checker now uses CallInfo from typecheck).
- Step 10: **done**
  - ✅ Parse `nothrow` on function definitions and propagate to signatures.
  - ✅ Enforce explicit nothrow on throwing bodies.
  - ✅ Parser + integration tests for nothrow definitions.
- Tri-state `fn_throws` refactor:
  - ✅ Phase 1: added `can_throw()` helpers and migrated logic to use them (raw tri-state preserved for serialization).
  - ✅ Phase 2: switched storage to 2-state (`fn_throws: bool`), updated constructors/decoders, and refreshed tests.

## Recent fixes (test stabilization)
- Prelude call resolution: register unqualified `lang.core` aliases in `CallableRegistry` for `print/println/eprintln`.
- Prelude injection now keys on `FunctionId` instead of short-name collisions, so explicit `import lang.core` works even if user code defines `println`.
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
- Prelude flag support: `--no-prelude` disables implicit `lang.core` import but explicit `import lang.core` still works (prelude exports injected for import resolution, auto-visibility remains gated).
- CLI now runs stub checker **after** typecheck with CallInfo so nothrow method-boundary violations are enforced (no name-based inference); stubbed pipeline checks normalized HIR for CallInfo alignment.
- Driver package test verifies fn-typed method params survive package encode/decode and resolve in a consumer.
- Core trust enforcement: core trust is mandatory, dev override requires `--dev --dev-core-trust-store`, and core keys cannot be revoked via user/project trust.
- InstantiationKey now derives module identity from `generic_def_id.module` (no separate module_id field), and key strings are based on `function_symbol(...)`.
- Instantiation signatures clear `param_types`/`return_type` so package decode can’t reintroduce `TypeVar` payloads (fixes cross-package instantiation dedup).
- Match statement cleanup: removed duplicate `match_stmt_arm_body` grammar alternative and added a negative test that rejects value-style arms in statement-form match.
- Trait-bound test harness now passes `trait_worlds` into `enforce_fn_requires` (fixes TypeChecker type-param bounds test).
- `enforce_fn_requires` now merges use-site visible modules in deterministic order; builtin type keys remain module-less during normalization; added driver tests for use-site `require` visibility.

## Out of scope (this branch)
- Method references / bound `self` function values.
- Implicit CallableDyn wrapping for function pointers.
- Full function-type inference without typed context.
- Keyword args for function values.

## Method boundary enforcement (completed)
- Provider-emitted Ok-wrap wrappers are injected at package build time for
  public/visible NOTHROW methods and recorded in exported signatures
  (`is_wrapper` + `wraps_target_symbol`).
- Wrapper signature preserves receiver ABI and generic params/constraints; the
  wrapper returns `FnResult<Ret, Error>` and `Ok(impl(...))`.
- Cross-module visible method calls select the wrapper FunctionId and force
  `CallSig.can_throw = True`; CAN_THROW methods force can-throw at the call site.
- Stub checker uses CallInfo for HMethodCall; missing entries hard-error during
  nothrow analysis.
- Stage2/LLVM continue using MIR `Call.can_throw` (no name-based inference).
- Tests:
  - `cross_module_method_requires_try` re-enabled and `cross_module_method_try_catch_ok`
    added.
  - `same_module_method_no_try_ok` guards same-module calls.
  - Driver tests assert wrapper selection for cross-module and cross-package
    method calls.
## Fn-typed params in signatures (completed)
Goal: support function-typed params end-to-end so method boundary wrappers can
cover methods with fnptr params.

Pinned requirements:
- Package/type-table plumbing must already support `TypeKind.FUNCTION` in
  param/return positions before lifting wrapper hard errors (prove with a
  driver test).
- ABI lowering for function types in signatures must be **pointer-only** (raw
  function pointers), not by-value function types.
- By-value function types in signatures are forbidden; lower as fn-ptr and
  keep calling convention consistent with existing fnptr values.
- Wrapper identity stays `method_wrapper_id(target_fn_id)`; overloads are
  disambiguated by `FunctionId` ordinal (no extra wrapper keying).

Deliverable order:
1) ✅ Driver test: emit a package exporting a method with a `fn(...)` param,
   import it, and resolve the signature (proves encode/decode/link + keys).
2) ✅ LLVM lowering: support fn-typed params in function headers (pointer ABI).
3) ✅ IR/header tests: nothrow + can-throw fnptr params lower to correct LLVM
4) ✅ Unquarantined `fnptr_overload_throwmode` and
   `fnptr_generic_throwmode_instantiation`.

## Plan: generic instantiation phase (TemplateHIR + monomorphic DMIR)
Goal: keep DMIR/MIR strictly monomorphic while enabling cross-package generics
using TemplateHIR shipped in package payloads.

Pinned invariants:
- No `TypeKind.TYPEVAR` may reach DMIR/MIR/SSA/LLVM.
- Generic templates live in package payload `generic_templates` and are not DMIR.
- Instantiation is per compilation unit; emitted symbols are linkonce/ODR-foldable
  and named by `InstantiationKey` (module/def id + canonical args + ABI flags).
- Module ids are globally unique within a build; duplicate ModuleIds across
  packages are a hard error (locked by driver test).

Package payload shape:
- Top-level key: `generic_templates`.
- Each entry includes `ir_kind: "TemplateHIR-v0"` and an `ir` object, plus:
  - generic params + constraints
  - signature template (TypeVars allowed)
  - template identity (`GenericDefId` / FunctionId)

Instantiation phase (new):
- Discover required instantiations from typed call sites (explicit args first).
- Load TemplateHIR from local sources or imported packages.
- Substitute TypeVars -> concrete types in signature + template body.

### Status (generic instantiation)
- ✅ Step 1 payload: `generic_templates` now includes `template_id` and `require`
  (nullable) and round-trips non-null require clauses.
- ✅ Step 2 skeleton: instantiation identity is keyed by canonical type keys +
  throw-mode, CallInfo is rewritten to instantiated CallSig, and the
  “no TypeVar in codegen” guard is recursive (nested param types).
- Emit concrete MIR only; reject if any TypeVar remains.
- Rewrite call targets to instantiated FunctionIds.
- ✅ InstantiationKey finalized (ModuleId + GenericDefId + canonical args + ABI flags),
  using the shared trait-resolution normalization helper.
- ✅ Instantiation cache + job queue dedup with pending/emitted handles; duplicate
  emission is a hard error.
- ✅ `--emit-instantiation-index` dumps deterministic key/symbol/ABI records.

### Definition of Done (instantiation phase)
- Single `InstantiationKey` helper used by all instantiation requests.
- Instantiation cache + job queue dedup; duplicate emission is a hard error.
- `--emit-instantiation-index` emits deterministic key+symbol+ABI records.
- ✅ COMDAT/linkonce emission for instantiations.
- Cross-package instantiation tests (constraint failure, dedup, missing template,
  ABI split) are green.

Docs alignment:
- `docs/design/dmir-spec.md` remains strict: DMIR/MIR monomorphic only.
- `docs/design/spec-change-requests/drift-monomorphization-odr.md` documents
  per-CU instantiation + linkonce/ODR folding with TemplateHIR payload.

Status:
- ✅ Step 1: `generic_templates` payload emitted per module (TemplateHIR-v0)
  with `template_id` (module/name/ordinal), signature templates, and an explicit
  `require` field (nullable). Package test added
  (`lang2/tests/packages/test_package_generic_templates.py`).
- ✅ Step 2: instantiation skeleton for explicit type args:
  - TemplateHIR lookup from local + package templates.
  - Concrete signatures emitted + call targets rewritten to instantiated FunctionIds.
  - Template bodies dropped from MIR lowering.
  - Hard “no TypeVar in codegen” invariant enforced before MIR/SSA/LLVM.
  - TypeVar bypass removed from stage4 throw checks.

## Current backend limitation (tracked)
- None at this time.
