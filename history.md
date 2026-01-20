## 2025-12-29 – Core trust enforcement (reserved namespaces)
- Made the core trust store mandatory for reserved namespaces; removed fallback to project/user trust for `lang.*`, `std.*`, and `drift.*`.
- Added dev-only override via `--dev --dev-core-trust-store` (non-normative), and documented the exception in the spec.
- Core-key revocations now consult only the core trust store; user/project revocations cannot disable toolchain keys.
- Added a toolchain core trust file with the required format header and updated tests accordingly.
- Prevented instantiation signatures from re-serializing template type exprs (clears `param_types`/`return_type`), fixing cross-package instantiation dedup.
- Cleaned match statement grammar (removed duplicate `match_stmt_arm_body`) and added a negative test to reject value-style arms in statement-form match.
- Updated trait-bound test harness to pass full `trait_worlds` into `enforce_fn_requires`.
- Made `enforce_fn_requires` merge use-site visible modules deterministically and preserved module-less builtins in trait requirement normalization; added driver coverage for use-site require visibility.

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
## 2026-01-02 – Callsite IDs, CallInfo authority, and generics pipeline hardening
- Enforced callsite-id as the sole call-identity: TypedFn now stores call info and instantiations keyed by callsite_id only; node-id maps and adapters removed with guard tests.
- Checker is FunctionId-only; removed legacy name-based adapters and signature-object identity recovery; CallInfo is required in typed mode.
- Split base vs derived signatures (immutable base, derived synthesis only), centralized synthesized signature registration, and made stage2 read-only for signatures.
- Hidden lambdas now typecheck as separate functions with their own callsite maps; capture binding IDs are remapped to fresh function-local IDs; captures are PlaceKind.CAPTURE; capture order is deterministic.
- CallInfo/MIR invariants tightened: every M.Call has explicit can_throw; stage2 rejects call_resolutions in typed mode.
- TemplateHIR-v0 import path removed in CLI (hard error); import boundary is structured IDs only.
- byte_length now takes &String with lvalue auto-borrow; rvalue borrow rejected; entrypoint main remains nothrow Int.
## 2026-01-03 – Return arrow + Fn types migration
- Replaced `returns` with `->` across the surface language (parser, docs, examples, and tests) and adopted `Fn(...) -> T` for function types, including lambda return annotations.
- Updated parser/token handling to recognize `Fn` type constructors and `->` return signatures, with type-mode heuristics adjusted accordingly.
- Modernized the legacy grammar to use `move` and `->` member-through-ref; removed the old `->` as move operator.
- Added regression tests for `->` member access inside function bodies and lambda return annotations.
- Added a deterministic function-type throw-mode identity test and aligned pretty-printers/diagnostic strings with the new syntax.
- Tightened function-type construction APIs (`ensure_function`/`new_function`) to avoid string-typed constructor names and updated all call sites.
- Aligned the legacy grammar with `Fn` types, `nothrow` returns, and the `|>` pipeline token.

## 2026-01-04 – MVP polish: generics codegen stability + typed lowering
- Added stable, argument-sensitive type keys (with hashed LLVM names) for struct/variant caching and FnResult keying to avoid cross-instantiation collisions.
- Fixed struct constructor lowering to pass expected field types and record constructed struct types; tightened typed-mode rules (strict vs recover) and gated strict mode on error-free typechecking.
- Hard-stopped codegen on typecheck errors to avoid partial MIR/SSA emission.
- Added codegen e2e coverage for two instantiations of the same generic struct in one module.

## 2026-01-06 – Optional consolidation + module/diagnostic policy alignment
- Consolidated `Optional<T>` as a canonical variant (`None=0`, `Some(T)=1`), removed Optional-specific MIR ops/ABIs, and enforced generic variant copy/dup/drop invariants (including `Optional<Bool>` storage decoding).
- Pivoted DiagnosticValue optional ABI to out-params + `bool` return, removed `DriftOptional*` runtime structs, and aligned DV ctor/lookup ABI with isize/i8.
- Tightened type system and IR correctness: forward nominals (no scalar placeholders), reserved builtin names, Byte as a seeded builtin, generic-arg validation, and deterministic variant instantiation caching.
- Hardened array/iterator semantics (CopyValue insertion, auto-borrow for `iter()`, place-only `next()`, Uint-index compare), and made struct/variant layout deterministic for instantiated types.
- Enforced module identity from `module <id>` (one file per module), removed multi-file module merges, and switched trait scope/aliasing to module scope only.
- Removed filesystem paths from diagnostics/DMIR metadata using source labels (`<source>`, `<module>`), updated parsing order for determinism, and clarified spec text for type prelude, catch resolution, and script-only implicit `main`.

## 2026-01-06 – Optional consolidation detailed log
- Created Optional consolidation work-progress and recorded the full plan.
- Added the Optional layout contract and determinism guardrails (fixed `None=0`, `Some=1` tag order).
- Completed an inventory of Optional-specific logic across TypeTable, resolver, parser injection, MIR, stage2, ARC, LLVM, runtime, and tests.
- Enforced Optional arm order in prelude injection and removed MIR OptionalIsSome/OptionalValue ops and references.
- Pivoted DV Optional ABI to out-params + bool return; removed DriftOptional* runtime structs; updated DV lowering/tests; aligned DV ctor ABI; removed duplicate @dataclass.
- Fixed FnResult ok-zero defaults for Uint/Uint64/Float; corrected struct CopyValue/ZeroValue for Bool storage types; fixed instantiated struct size/align; seeded Byte; fixed 32-bit StringCmp cast; removed redundant pointer-null bitcasts; enforced fnptr signature metadata; restored ZeroValue pointer SSA emission; fixed ArrayLit insertvalue emission and ArrayLit CopyValue for Copy-but-not-bitcopy elements; added Array<String> literal retain IR checks; stored FnResult Bool ok as i8 with conversions; asserted Array<ZST> in codegen.
- Added stage2 Optional base seeding on demand; unified Optional instantiation in stage2 and type checker; removed Optional caches and TypeTable.new_optional; added optional mechanical tests and Optional<Bool> IR golden; documented Optional as standard variant in spec; added deterministic variant instantiation test.
- Updated spec for named variant ctor args (no mixing, source-order evaluation); added stage2 source-order evaluation test.
- Added forward nominal kind and upgraded ensure_named/declare_struct/declare_variant to reuse forward TypeIds; reserved builtin names; improved generic arg validation; added reserved names for exceptions.
- Removed multi-file module merge; enforced one-file-per-module; removed module id inference from paths; switched trait scopes/aliases to module scope; removed file-scoped trait scope param; updated driver/tests for module headers and module-scoped use-trait; updated e2e fixtures to micro-modules and merge-module patterns; refreshed expected diagnostics for new module rules.
- Removed filesystem paths from diagnostics/DMIR; introduced SourceLabel relabeling; updated parse order for determinism; removed string path scrubbing; added no-path-leak tests with absolute-path regex detection; updated CLI/spec for module discovery and script-only implicit main.
- Updated e2e fixtures: added exports for m_a/m_b; removed duplicate module headers; added explicit Maybe ctor type args/annotations; updated qualified ctor duplicate-type-args expected line/column.
- Fixed driver test workspace parsing to always pass module roots; repaired accidental module_paths insertion typos in trait tests.
- Updated method resolution e2e diagnostic test to include module/Point and assert the “no matching method” message via JSON.
- Added module headers to borrow checker lambda capture overlap tests; re-instated variant substitution via base instantiation when instances are missing.
- Clarified spec: Float is target-native (per-target ABI); fixed-width floats remain reserved in v1.
- Renamed module_root_mismatch e2e to module_root_unrelated_ok to reflect allowed behavior.
## 2026-01-06 – Optional-as-variant consolidation + package/link determinism hardening
- Consolidated Optional into regular variants (None=0/Some=1), removed Optional-specific MIR/LLVM/runtime paths, and added mechanical tests to ensure Optional ops/kinds are gone.
- Standardized variant lowering: deterministic arm order, non-bitcopy variants, zero-initialized variant construction, and stable copy/drop behavior (including Optional<Bool> storage handling).
- Package type tables and linker: mandatory provided_nominals, semantic TYPEVAR identity, struct schemas carry type exprs + base_id, struct/variant instantiation support (template vs concrete), and strict module-id ownership checks.
- Enforced module ownership determinism: module_ids globally unique, linker populates host.module_packages (lang.core seeded), type_key_string requires provider mapping for imports.
- Added template instantiation caching, deep has_typevar, module-scoped scalar nominals, and multiple regression tests to lock invariants.
- LLVM backend updates: float width support, export wrapper Bool ABI coercion, array drop helper SSA fix + verifier test, and variant payload alignment guards.
## 2026-01-13 – Iterators, move semantics, and exception payload plumbing
- Pinned iterator trait surfaces (`std.iter`) and `for` UFCS lowering with deterministic diagnostics; added driver/e2e coverage for shadowing, function-returned iterables, and capability gating.
- Established `std.core.Copy`/`std.core.Diagnostic` traits and centralized Copy checks in the compiler; added `E_USE_AFTER_MOVE` diagnostics and consuming-position move tracking in the borrow checker.
- Implemented non-Copy array mutation via move-out/tombstone semantics (String/Array/Struct/Variant with `@tombstone` arm), plus required schema validation.
- Added `std.err:IndexError` and `std.err:IteratorInvalidated` exception events; wired bounds checks and iterator invalidation to throw with structured attrs.
- Made array OOB catchable in MIR (`ArrayIndexLoadUnchecked`) and removed runtime bounds-check abort path.
- Centralized Array container_id (`std.containers:Array`) in compiler constants and pinned `IteratorOpId` numeric ABI mapping via `to_diag`.
- Added Copy-only array literal enforcement in typecheck and e2e coverage; kept codegen as internal backstop.
## 2026-01-15 – ArrayRange invalidation + borrow-check fixes
- Fixed ArrayRangeMut swap receiver to use `self.arr.swap(...)` (avoids non-lvalue deref receiver in MIR lowering).
- Updated MIR expr typing to prefer local binding types for `HVar` (stabilizes struct field access in stdlib lowering).
- Allowed mutable borrow for receivers typed as `&mut T` in type checker (removes false “mutable Array receiver” diagnostics).
- Added driver borrow-check tests for array element borrow conflicts/disjoint indices.
## 2026-01-16 – UFCS uniform call resolution
- Added `CallTargetKind.CONSTRUCTOR` to carry variant ctor metadata in CallInfo and lower constructor calls via CallInfo.
- Removed HQualifiedMember special-case lowering in MIR; qualified calls now route through uniform call resolution.
- Allowed trait UFCS calls on non-lvalue reference receivers (e.g., `Comparable::cmp(&T, &T)`).
## 2026-01-17 – Array header layout + LLVM test alignment
- Updated LLVM array header layout to include `gen` and fixed nested array drop helper extract indices.
- Updated LLVM array header tests for the new layout and skipped LLVM-verify test when llvmlite is unavailable.
- Synced runtime Array header layout for argv helpers and initialized gen in argv construction.
- Pinned gen semantics to “actual structural change” and added reserve no-op vs growth invalidation e2e.
## 2026-01-18 – Binary search in std.algo
- Implemented `std.algo.binary_search` on `BinarySearchable + Comparable`.
- Added e2e tests for basic/duplicate binary_search and driver diagnostics tests for missing Comparable and key-type mismatch.
## 2026-01-19 – Trait UFCS fixes for type-parameter receivers
- Fixed UFCS trait method resolution for type-param receivers by honoring require-bound type args; unblocked `BinarySearchable::compare_key` in std.algo and swap e2e coverage.
## 2026-01-20 – Diagnostic codes stabilization
- Added deterministic auto-codes for diagnostics without explicit codes (prefix-detected or hashed), ensuring stable `Diagnostic.code` values across phases.
## 2026-02-01 – Deque container + non-Array payload tests
- Added `Deque` container with `DequeRange`/`DequeRangeMut` and `DEQUE_CONTAINER_ID` in stdlib.
- Added non-Array OOB payload e2e test (`deque_index_error_payload_oob`).
- Added non-Array range invalidation e2e tests for `compare_at`/`swap` (`deque_range_compare_at_invalidated`, `deque_range_swap_invalidated`).
## 2026-02-02 – Module-qualified calls + struct-field gen access
- Module-qualified free calls now resolve via a global module-name map from signatures/registry, fixing `std.err.throw_iterator_invalidated` resolution in stdlib.
- HField len/cap/gen sugar now yields struct fields when present, allowing `Deque.gen` access without bogus `len(x)` errors.
## 2026-01-21 – Sort requirement simplification
- Removed the `Comparable` requirement from `std.algo.sort_in_place`; ordering is defined by `compare_at` on RandomAccess ranges.
## 2026-01-22 – Iterator work-progress cleanup
- Trimmed iterator work-progress to outstanding items only (no functional changes).
## 2026-01-23 – UFCS receiver fixes for std.algo sort_in_place
- Adjusted `sort_in_place` UFCS calls to use `r` (removed `&*r`) and allowed `&mut T` receivers to satisfy `&T` in UFCS compatibility checks.
- Relaxed trait impl visibility blocking so UFCS trait calls resolve against non-local impls.
- Updated driver tests for `sort_in_place` to allow can-throw entrypoints.
## 2026-01-14 – Mutable iteration + Optional<&mut> borrow tracking
- Added `ArrayBorrowMutIter` and `Iterable<&mut Array<T>, &mut T>` in stdlib; exported mut iterator type for use in signatures.
- Borrow checker now treats Optional<&T>/Optional<&mut T> bindings as ref bindings and tracks borrows through explicit `&/&mut` call arguments.
- Added driver coverage for `for x in &mut xs`, `next()` re-entrancy errors, and safe `next()` after borrow scope ends.
## 2026-01-24 – Trait method resolution for instantiations + guard scoping
- Resolved trait-method dot calls in instantiated generic bodies to direct impls (avoids missing CallInfo in std.algo).
- Deferred diagnostics for ambiguous generic trait guards (OR/NOT), restoring guard scoping behavior.
## 2026-01-25 – Type checker method-call refactor
- Extracted `HMethodCall` handling into `_type_method_call` helper to reduce nesting and stabilize indentation in `type_checker.py`.
- Removed the unreachable post-method-call expr handling block from the helper (kept in `type_expr`).
## 2026-01-12 – Qualified-member call consolidation cleanup
- Prioritized trait UFCS resolution for `HCall` qualified members before variant constructor resolution, preventing false `E-QMEM-NONVARIANT` errors for `Trait::method(...)` (e.g., `cmp.Comparable::cmp`).
- Removed legacy qualified-member ctor resolution inside method-call handling that could leave `ctor_sig` uninitialized and reintroduce duplicate inference paths.
- Restored `for` AST → MIR CFG test by ensuring all stdlib UFCS calls produce CallInfo in typed mode.
## 2026-01-26 – Trait impl visibility + require-arg substitution for method calls
- Trait method resolution for type-parameter receivers now injects trait type arguments from `require` into method signatures in the fallback trait-resolution path.
- Public trait impls are now visible across modules for method resolution (removed module visibility gate for trait impl candidates).
## 2026-01-27 – Ref-mut preference + trait guard diagnostics alignment
- Method resolution now prefers `&mut` over shared `&` when both receivers match, fixing `Iterable::iter(&mut xs)` to resolve the mut iterator impl.
- Updated trait-guard scoping tests to expect missing-require diagnostics for OR/NOT guards.
- Trait dot-call tests now avoid `nothrow` so can-throw trait methods are accepted in MVP.
## 2026-01-28 – Trait method resolution for instantiations
- Relaxed trait impl visibility filtering during generic instantiations so std.algo method calls resolve against caller-provided impls.
## 2026-01-29 – test-build-only annotations
- Added @test_build_only annotation (grammar+parser) and compiler flag --test-build-only; non-test builds ignore annotated items.
- Filtered test-only items and exports during parse, and wired e2e runner to enable test-build-only.
## 2026-01-30 – Preserve marker trait impls under test-build-only filtering
- Kept empty `implement` blocks during @test_build_only filtering so marker traits (e.g., `Copy`) remain available; restored Copy query behavior in typed pipelines.
## 2026-01-30 – Constructor resolution consolidation
- Routed struct constructor argument mapping through call_resolver to reduce duplicate ctor resolution paths in the type checker.
## 2026-01-17 – Generic signature resolution + ctor inference fixes
- Signature normalization now resolves param/return TypeIds with impl/type param maps for generic signatures (prevents generic return types from collapsing to concrete bases).
- Instantiation substitution now maps impl/type params directly to impl_args/fn_args (ensures instantiated return types are concrete).
- Struct ctor resolution now prefers expected-type struct instances when base matches, fixing ArrayMoveIter ctor inference in return positions and restoring typed CallInfo in stdlib.
