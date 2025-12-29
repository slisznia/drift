## 2025-12-28 – Function pointers: thunks + captureless lambdas
- Added NOTHROW→CAN_THROW Ok-wrap thunking for function values with a dedicated FunctionRefKind and a thunk cache; typed-context assignment can insert thunks while `cast<T>` stays strict.
- Added captureless lambda coercion to `fn(...)` pointers with capture rejection and can-throw validation.
- Materialized thunk and lambda synthetic functions in the driver pipeline pre-LLVM (MIR emission is now explicit and stable).
- Added tests for thunk selection, captureless/capturing lambda coercion, and synthetic MIR emission (including unique lambda ids per enclosing function).
- Moved CLI stub-checker enforcement after typecheck with CallInfo so nothrow method-boundary violations are enforced deterministically (no name-based inference); normalized HIR is used for CallInfo alignment.

## 2025-12-26 – Borrow checker statement-level liveness + ref-copy loans
- Refined NLL-lite borrow tracking with per-statement ref liveness inside blocks, while preserving conservative “unused borrow stays live” behavior via lexical-scope caps.
- Propagated loans across ref-to-ref `let`/assignment by cloning loans onto the destination ref with its own region cap.
- Added regression tests for same-block last use, ref-copy liveness, and unused-borrow conservatism (including inner-scope release).
- Borrow checker suite and targeted borrow codegen e2e cases passed.
- Replaced `nonescaping` annotations with internal tri-state `param_nonretaining` metadata, added a conservative non-retaining analysis pass, and wired lambda validation + borrow checking to use it.
- Added strict fallback resolution for direct free-function calls in non-retaining analysis and allowed immediate `.call(...)` invocation on lambda receivers.

## 2025-12-21 – Modules + packages + trust, plus core language additions
- Landed multi-module workspace builds with explicit module roots (`-M/--module-path`) and deterministic module-id inference from directory paths, with strict module header validation (duplicate headers / not-first / mismatch / invalid ids / reserved prefixes).
- Implemented explicit exports (`export { ... }`) and module-only imports (`import m [as x]`) with private-by-default visibility, deterministic star export expansion, and strict conflict rules (import/import + import/local are hard errors; repeated imports idempotent).
- Added re-export authority (values/types/consts): `export { foo }` can re-export imported bindings; re-exported values materialize as trampolines; re-exported consts are materialized into the exporting module’s const table; packages validate that interfaces match payload exports.
- Introduced deterministic package artifacts (DMIR-PKG v0) as an offline container for compiler IR with strong hash verification, plus trust enforcement with sidecar signatures (`pkg.dmp.sig`) and a project-local trust store (revocation supported; driftc is the offline gatekeeper).
- Added `drift` tooling (offline, no compiler internals): `keygen`, `sign`, `trust add-key/list/revoke`, plus local workflow commands `publish`, `fetch`, `vendor` and an authoritative `drift.lock.json` (single version per package id per build pinned).
- Hardened cross-module ABI boundaries: exported functions always use the boundary `FnResult<Ok, Error*>` convention; cross-module calls must target the public wrapper (never `__impl`), with safe unwrap-or-trap in nothrow contexts; strict package interface validation blocks malformed exports/signatures/method exports.
- Expanded core language coverage with passing end-to-end tests:
  - Variants + `match` as an expression with `default` arms, block bodies, and robust binder handling (alpha-renaming + checker-normalized binder field indices; stage2 remains assert-only).
  - Qualified type member access for constructors (`TypeRef::Ctor(...)`) including bounded generic disambiguation (`Optional<Array<String>>::None()`), plus improved constructor diagnostics and a pinned parser diagnostic for duplicate type-arg lists.
  - `const` declarations with compile-time literal evaluation (unary +/-), export/import, module alias access, and package encoding/validation of exported const tables.
  - Float (`double`) end-to-end (literals + formatting via Ryu) and f-strings with typed interpolation.
  - Borrow/move/method/field infrastructure continued to mature (canonical places, materialized rvalue borrows, swap/replace, module-scoped nominal types and methods).

## 2025-12-15 – Exceptions: constructor-only throw syntax + schema-validated args
- Switched exception throwing to constructor-call form only: `throw E(...)` (parens required even for zero-field events via `throw E()`); removed brace-based and shorthand throw forms across parser/AST/HIR/checker/lowering and tests.
- Added shared exception ctor argument resolver (`lang2/driftc/core/exception_ctor_args.py`) to map positional/keyword args to declared exception fields (schema order), with diagnostics for missing/unknown/duplicate fields.
- Extended parser/stage0/HIR kwarg nodes to carry name spans for precise diagnostics; `HExceptionInit` now carries `pos_args` and `kw_args` with spans; try-result rewrite preserves the new shape.
- Updated checker (stub + type checker) and HIR→MIR lowering to validate/resolve ctor args against `TypeTable.exception_schemas` and attach attrs deterministically; e2e + unit tests updated accordingly; full suite passes (`just`).

## 2025-12-09 – Borrow checker Phase 2 (coarse loans) + borrow HIR
- Added HBorrow HIR node and parser lowering for `&` / `&mut`; exported via stage1 API.
- Extended borrow checker to track active loans (shared vs mut) in CFG/dataflow state, enforcing lvalue-only borrows, moved/uninit rejects, conflict rules (whole-place overlap), and moves-blocked-while-borrowed. Assignments drop overlapping loans; temporary borrows in expr/conds are dropped after use; Loan carries region_id for upcoming NLL work. Optional shared auto-borrow flag scaffolded with call-scoped temporary loans.
- Added borrow-specific tests (rvalue/moved borrow errors, shared allowed, shared+mut and mut+mut conflicts, move under loan, temp-borrow NLL approx) alongside existing move/CFG tests.
- Updated progress tracking for Phase 2 and documented the new scaffolding; borrow checker docstrings now cover loans. Tests: `PYTHONPATH=. .venv/bin/pytest lang2/borrow_checker/tests`.

## 2025-12-09 – Borrow checker scaffolding (places + CFG/dataflow)
- Implemented hashable place identity (`PlaceBase` with kinds/ids) and projection-aware places; added `PlaceState` + `merge_place_state` lattice for dataflow joins.
- Added Phase-1 borrow_checker_pass: builds a CFG from HIR, runs forward dataflow to track UNINIT/VALID/MOVED, walks all HIR expressions to record moves, and emits use-after-move diagnostics with stable names.
- Improved tests and tooling: branch/loop CFG move tests, expanded move-tracking and place-builder coverage, Justfile target `lang2-borrow-test` included in `lang2-test`; diagnostics reset per run.
- All borrow checker suites passing: `PYTHONPATH=. .venv/bin/pytest lang2/borrow_checker/tests`.

## 2025-12-08 – String params & array helper decls
- Fixed LLVM backend to type arguments using function signatures (Int → i64, String → %DriftString) and emit typed call sites; function headers now preload param types into value_types.
- Moved array runtime helper declarations to module scope (emit once per module), preventing invalid IR from function-local declares.
- Added LLVM IR tests for typed params: Int+Int headers/calls and mixed Int/String param plus String return; added String literal pass-through call test.
- Updated docs/comments: compile_to_llvm_ir_for_tests now mentions Int/String/FnResult returns; string work-progress reflects param support; TODO trimmed.
- All tests green (PYTHONPATH=.. ../.venv/bin/pytest).
## 2025-12-08 – String ops in LLVM
- Added String-aware binary op lowering: `==` calls `drift_string_eq`, `+` calls `drift_string_concat`, and String `len` reuses ArrayLen lowering to extract the length field.
- Module builder now emits `drift_string_eq`/`drift_string_concat` declares once when needed; array helper declares remain module-level.
- Added LLVM IR tests for string len on a String operand and for string eq/concat; existing literal/pass-through tests remain green.
- All tests passing: PYTHONPATH=.. ../.venv/bin/pytest.
## 2025-12-08 – String ops via MIR, e2e len/eq/concat
- HIR→MIR now emits explicit `StringLen`, `StringEq`, and `StringConcat` for `len(s)`, `s == t`, `s + t` on strings; BinaryOpInstr no longer handles string operands.
- LLVM lowers these MIR ops: string len via `extractvalue %DriftString, 0`; eq/concat via runtime calls with module-level declares for `drift_string_eq` / `drift_string_concat`.
- E2E runner links string_runtime; added e2e cases for string len (literal/roundtrip), concat len, and eq; all passing. Added negative LLVM test for unsupported string binops.
- Array helper declares remain module-level; all tests green.
## 2025-12-09 – String hex escapes, Uint alignment, bitwise enforcement
- Parser now accepts `\xHH` hex escapes in string literals; added e2e `string_utf8_escape_eq` comparing a UTF-8 literal to its escaped form (equal at runtime) and adjusted UTF-8 multibyte e2e to check byte_length. Literal escaper continues to produce correct UTF-8 globals.
- Checker maps opaque/declared `Uint` to the canonical Uint TypeId (len/cap return types); bitwise ops are enforced as Uint-only with a clear op set. `String.EMPTY` handling in HVar inference simplified.
- `%drift.size` alias reinstated in IR (Uint carrier); string/array IR tests updated to expect `%drift.size` in `%DriftString`. ArrayLen lowering comment cleaned up (strings use StringLen MIR).
- All suites green after changes: just lang2-codegen-test, lang2-test, parser/checker/core/stage tests.
## 2025-12-09 – Parser diagnostics & shared typing cleanup
- Parser adapter now reports duplicate functions as diagnostics (with spans) instead of raising; parse_drift_to_hir returns diagnostics. E2E runner supports phase-aware diagnostic cases and matches stderr/exit for parser/checker failures; added duplicate_main e2e case.
- Added lang2/driftc.py `--json` flag to emit structured diagnostics (phase/message/severity/file/line/column) for parser failures; CLI bootstraps sys.path for venv usage.
- Checker refactor: introduced shared _TypingContext + _walk_hir; array/bool validators share locals/diagnostics, and new tests cover param-indexed arrays and param-based if conditions.
- Parser now builds signatures and HIR from the same non-duplicate function set so duplicates can’t desync signature vs. body; parser tests updated and pass.
- All updated parser/checker/e2e tests passing (PYTHONPATH=. pytest ...; runner duplicate_main ok).
## 2025-12-25 – Generics, traits, visibility, and NLL-lite borrow polish
- Adopted **`<type …>` call-site generics** with hard `type` keyword, explicit type application in calls and callable refs, and parser guards against duplicate type-app suffixes; added UFCS calls (`Trait::method(...)`) and `use trait` directives for explicit trait scope.
- Introduced **TypeParamId/TypeVar** spine, explicit instantiation + inference via `InferContext/InferResult`, and centralized inference diagnostics with structured failure notes and new tests.
- Added **struct generics + impl matching** (including nested generic templates), impl requires and struct requires enforcement, and trait bounds as ambient assumptions with call-site proofing.
- Implemented **workspace-wide impl index + method resolution across modules**, method visibility (`pub` gating), and link-time duplicate inherent method checks with deterministic ambiguity diagnostics.
- Completed **visibility model** in code: `pub` eligibility + explicit exports, `export { module.* }` re-exports, module-only imports, and package payload export surfaces with trait exports/reexports and validation.
- NLL-lite borrow checker upgrades: per-ref live-region analysis, join/loop witness notes on conflicts, ref rebinding kills old loans, const-folded index disjointness, and `i != j` branch facts for disjoint indices (with new e2e tests).
## 2025-12-28 – Function type throw-mode hardening and entrypoint rule
- Enforced strict `fn` throw-mode handling: `fn_throws` is now a 2-state bool, rejects explicit nulls, and package codecs preserve `can_throw` with backwards-compatible defaults.
- Cross-module exported/extern calls now force can-throw at the boundary; LLVM trap fallback removed in favor of a hard compiler error for mis-lowered nothrow calls.
- Added entrypoint rules: exactly one `main`, it must return `Int`, and it must be declared `nothrow`; new e2e diagnostics cover missing/duplicate main cases.
- Updated tests to reflect strict throw-mode decoding and entrypoint enforcement.
- Catch event arms now accept unqualified event names (resolved to the current module) with spec updates.
- Added nothrow e2e coverage (throwing calls, try/catch ok, cross-module method requires try, same-module pub ok, can-throw→nothrow fnptr reject).
- Provider-emitted method boundary wrappers now exist for public NOTHROW methods, exported in package signatures and selected at cross-module call sites; cross-module method boundary e2e re-enabled with new try/catch and same-module guard cases.
