# Iterator Feature Work Progress

## Goal
Define iterator traits and MVP constraints for collections/algorithms, aligned with Drift's compile-time traits.

## Outstanding

### Phase 3: Uninitialized storage primitives (RawBuffer/MaybeUninit) and container rebuild
- (done) Added `std.mem.RawBuffer<T>` (ptr+cap) with intrinsic-backed ops: alloc_uninit/dealloc/ptr_at/write/read; `capacity()` implemented in std.mem.
- (done) Added RawBuffer intrinsics to type checker, MIR, and LLVM codegen; lowered to drift_alloc_array/free_array plus pointer arithmetic.
- (done) Rebuilt Deque ring buffer on RawBuffer (head/len/gen, wrap mapping, gen bump only on actual structural change).
- (done) Deque wraparound/sort/binary_search e2e tests pass under RawBuffer.
- (done) RawBuffer read/write/ptr_at use typed GEP with distinct temporaries (no SSA redefinition); added rawbuffer_read_write e2e to lock element indexing + Bool conversions.
- (done) Stage2 array literal lowering now uses expected Array<T> type for empty literals; added array_pop_move_out_non_copy and array_sort_binary_search_after_growth e2e tests.
- (done) Added std.mem.MaybeUninit<T> (trusted/internal only; not exposed to user code yet).
- (done) Rebuilt Array<T> on RawBuffer semantics in compiler lowering: header remains {len, cap, gen, ptr}; array ops move only initialized prefix; vacated slots become uninit via ArrayElemTake; bounds checks stay centralized. Added array_pop_move_out_non_copy + array_sort_binary_search_after_growth e2e canaries and enabled empty literal typing via declared Array<T>.
- (done) Array header stays flattened as `len, cap, gen, ptr` (RawBuffer embedded) in LLVM; argv wrapper now forwards `gen` and uses `i8*` ptr; keep `ArrayCap` MIR op mapped to header cap field.
- (done) Spec updated: Array layout includes `len, cap, gen, ptr` with RawBuffer semantics; growth algorithm uses ptr; ABI flattened note added.
- (done) Added Array regression tests: reserve no-op vs growth invalidation (`array_range_reserve_noop_invalidates`), range invalidation (`array_range_len_invalidated`/`array_range_compare_at_invalidated`), and sort/binary_search over Array ranges (`algo_sort_*`, `algo_binary_search_*`).
- (done) Added move-out correctness e2e for Array<String> pop (array_pop_move_out_string).

### Phase 2: Algorithms
- (done) Implemented `binary_search` using `BinarySearchable.compare_key` + tests (capability gating + return semantics).
- (done) Implemented `sort_in_place` (heapsort) with test matrix (sorted/reverse/dups/random) + swap-does-not-invalidate check.

### Closed in this batch
- Added `Deque` container + Deque ranges (`DequeRange`, `DequeRangeMut`) with `DEQUE_CONTAINER_ID`.
- Added non-Array OOB payload test (`deque_index_error_payload_oob`).
- Added non-Array range invalidation tests for `compare_at`/`swap` (`deque_range_compare_at_invalidated`, `deque_range_swap_invalidated`).

### Payload tests
- New tests should assert ID fields only (`container_id` / `op_id`), not display strings.
- Iterator error payload string assertions are deferred until ID-based access is the only supported path.

## Recent updates
- Extracted `HMethodCall` handling into `_type_method_call` helper inside `type_checker.py` to reduce nesting and stabilize indentation.
- std.algo `sort_in_place` now calls `RandomAccessReadable::len/compare_at` with `r` (no `&*r`).
- UFCS receiver compatibility allows `&mut T` to satisfy `&T` (shared) receivers.
- Trait impl visibility filtering restored for non-pub impls across modules.
- Driver tests for `sort_in_place` now allow can-throw `main` (no `nothrow` constraint).
- Method-call resolution now resolves trait methods in instantiation contexts via direct impl candidates (avoids missing CallInfo in std.algo).
- Trait guard ambiguous branches now defer diagnostics for generic guards (OR/NOT), restoring guard scoping tests.
- Added `ArrayBorrowMutIter` with `Iterable<&mut Array<T>, &mut T>` and `SinglePassIterator<&mut T>`.
- Borrow checker now tracks Optional<&T>/Optional<&mut T> bindings and borrows through explicit `&/&mut` call args.
- Added/updated borrowcheck tests for `&mut` iteration: `for x in &mut xs` and `next()` re-entrancy checks.
- Added borrowcheck coverage for same-index writes after `&xs[i]` and for `&mut` iterator borrow lifetime via helper call.
- Borrow checker now initializes match-arm binders, fixing `for` loop binder use-after-uninit.
- Trait method resolution requires explicit require for type params; restored impl visibility filtering for non-pub impls.
- Added driver coverage for trait method dot-calls on type params (use-trait required).
- Added borrow-check test ensuring `for x in &arr {}` does not consume `arr`.
- Added e2e range invalidation test for `swap` (ArrayRangeMut).
- Deque `pop_back` now bumps `gen` only on actual removal; added no-op pop range invalidation e2e.
- Array indexing spec clarified as place expression: `arr[i]` Copy-only in value context; `&arr[i]` / `&mut arr[i]` permitted.
- Deque internals switched to ring buffer layout with head/len/gen and Array<Optional<T>> storage.
- Added Deque ring buffer e2e tests: wraparound, no-op pop_front invalidation, realloc invalidation, and sort/binary_search under wrap.
- LLVM array header now uses `i8*` data ptr; element access/drop bitcasts to `T*`.
- argv wrapper uses `i8*` ptr and forwards `gen` from runtime header.
- argv entry wrapper now uses canonical Array LLVM type (i8* ptr) to avoid `%DriftString*` mismatch in `main(argv)` tests.
- Spec note added: v1 container allocation lowers to `drift_alloc_array/free_array`; `lang.abi` remains the long-term surface.
- Fixed method-resolution scaffolding: initialize `traits_in_scope` before use in all branches.
- Qualified member ctor inference now emits `E-QMEM-CANNOT-INFER` when no expected type and no args/type args.
- HTypeApp qualified-member references return function types without requiring `args/kwargs`.
- Borrow checker now resolves binding ids for `&x` operands before place checks (fixes `borrow_types`).
- Consolidated qualified-member variant ctor resolution for `HCall` through a shared resolver (reduces duplicate logic).
- Qualified-member UFCS calls now skip variant ctor resolution when the base is a trait (prevents `E-QMEM-NONVARIANT` for `cmp.Comparable::cmp`).
- Removed legacy qualified-member ctor resolution inside method-call handling (eliminates `ctor_sig` UnboundLocal and duplicate paths).
- HTypeApp value references remain allowed in typed HIR while call-resolution consolidation continues (typed invariant check no longer errors on HTypeApp nodes).
- Fixed HTypeApp callable references: qualified member refs now resolve to function types; function-value type args are rejected.
- Fixed prequalified variant ctor references (e.g., `Optional<Int>::None`) by normalizing to variant base and instantiating with base type args.
- Trait method resolution for type-param receivers now injects trait type args from `require` into method signatures and skips impl-visibility filtering; public trait impls are now visible across modules (module visibility gate removed).
- Method resolution now prefers `&mut` receivers over shared `&` when both match; UFCS `Iterable::iter(&mut xs)` now resolves to `ArrayBorrowMutIter`.
- Trait guard scoping tests updated to expect missing-require diagnostics (OR/NOT guards do not add scope).
- Trait dot-call tests no longer require `nothrow` for `len` (can throw via invalidation).
- Method resolution now bypasses trait impl visibility checks during instantiations so std.algo generic bodies resolve trait methods against caller impls.
- Added ArrayRangeMut test helper `__test_invalidate` (reserve-based) and updated array_range_swap_invalidated e2e to avoid private field access.
- Added @test_build_only annotation (parser+compiler flag) and wired e2e runner to include test-only stdlib helpers.
- Fixed @test_build_only filtering to keep empty `implement` blocks (marker traits like `Copy`), restoring Copy query behavior in typed pipelines.
- Routed struct constructor argument mapping through call_resolver (shared ctor normalization), reducing duplicate ctor resolution paths in type_checker.
- Fixed immediate lambda call typing: lambdas now always bind params, return a function type when not coerced, and HCall with HLambda records CallInfo (fixes hidden lambda MIR collection).
- For `for` lowering without stdlib, `std.iter` UFCS calls now emit `E-NOT-ITERABLE`/`E-ITER-RESULT-NOT-ITERATOR` instead of qualified-member errors.
- Trait UFCS candidate filtering now enforces `impl require` clauses and reports requirement failures (unblocks `Copy`-gated owned iteration).
- Trait UFCS concrete receiver instantiation now records impl type args for calls, so instantiation rewrites call targets and avoids TypeVar leakage in codegen.
- Typecheck borrow/move diagnostics updated: &mut of move expr, deref &mut requires mut ref, &mut while borrowed message, move-from-ref rejection, and `copy` now always enforces Copy.
- Tests: `.venv/bin/python -m pytest lang2/tests/type_checker -q`
- Call resolver now derives ctor type args from qualified base type args, and ctor inference errors include “underconstrained” in message; match nonexhaustive error now includes `E-MATCH-NONEXHAUSTIVE`; pattern unknown-field message updated to “in constructor pattern”.
- Module-qualified free calls now resolve via a global module-name map from signatures/registry, fixing `std.err.throw_iterator_invalidated` resolution in stdlib.
- HField len/cap/gen sugar now yields struct fields when present (allows `Deque.gen` access and removes bogus `len(x)` errors).
- Deque `pop_back`/`pop_front` now move from `var` bindings (fixes stdlib borrowcheck “move requires var”).
- ArrayMoveIter now binds `v` as `var` before returning (prevents borrowcheck move-from-val in Copy-only iterator).
- Stage2 HField lowering now prefers struct fields for len/cap/gen before array sugar (fixes Deque range gen access in IR).
- std.algo `binary_search` no longer redundantly requires `RandomAccessReadable` (covered by `BinarySearchable`).
- TypeChecker now builds require env from linked trait worlds when missing and `_require_for_fn` falls back to FunctionId field matches to recover `require` clauses in generic bodies.
- Added type-checker unit test to ensure require-env fallback uses linked world when require_env=None (prevents trait-dot resolution regressions in generic bodies).
- Added type-checker unit test to ensure trait-dot calls on type-param receivers use require type args for method signature instantiation.
- Expanded type-param receiver method resolution to honor trait requires (e.g., BinarySearchable -> RandomAccessReadable) by propagating trait type args from require env.
- TypeChecker now passes `type_param_map` into `resolve_opaque_type` for explicit type args (fixes RawBuffer<T> instantiations resolving to forward nominal `T`).
- TypeChecker now passes `type_param_map` into `resolve_opaque_type` for struct ctor type args, free-call type args, and qualified member base args.
- Added RawBuffer capacity intrinsic and fixed RawBuffer alloc LLVM lowering to avoid invalid IR assignment.
- Added call_resolver.resolve_qualified_member_call and routed qualified ctor resolution through it; base type detection now falls back to lang.core variant/struct bases so Optional::Some resolves in stdlib.
- Unqualified variant ctor calls now resolve against expected variant type and emit constructor CallInfo (fixes Optional::Some/None unqualified inference in package tests).
- Restored instantiation recording in call_resolver (free and method calls) so missing template bodies report `E_MISSING_TEMPLATE_BODY` before codegen.
- Signature resolution now re-resolves param/return TypeIds with type param maps when generic signatures are present (prevents ArrayMoveIter<T> return types from collapsing to concrete base ids).
- Instantiation substitution now maps impl/type params directly to impl_args/fn_args in addition to impl_target_type_args (fixes generic method return types in instantiations).
- Struct ctor resolution now prefers expected-type struct instances (matching base) to drive field types, fixing ArrayMoveIter ctor inference in return position.
- Qualified member ctor resolution now rejects struct bases with `E-QMEM-NONVARIANT` (e.g., `Point::Some`).
- RawBuffer element-type inference for std.mem intrinsics now uses `struct_base_and_args` (handles `RawBuffer<T>` instances correctly).
- Borrow checker now treats `HPlaceExpr` rooted in `&mut` as mutable borrowable (fixes RawBuffer `replace` inside `&mut self`).
- std.mem `swap`/`replace` now take `&mut` arguments; resolver/borrow checker/MIR lowering updated and stage1 place-canonicalization no longer rewrites them to `HPlaceExpr`.
- std.mem `capacity()` is now a normal stdlib function (no intrinsic fast-path); RAW_CAPACITY lowering/validation removed, trusted-module restriction still applies.
- Split `ptr_at_ref`/`ptr_at_mut` into distinct intrinsics (`RAW_PTR_AT_REF`/`RAW_PTR_AT_MUT`) to preserve mutability through MIR/codegen.
- Added raw pointer kind `Ptr<T>` in the type system and std.mem Copy impl; resolver maps `std.mem.Ptr<T>` to the pointer type and codegen lowers it as a raw pointer.
- e2e runner now passes `--stdlib-root` when using driftc --json, fixing stdlib-based diagnostic cases.
- Unqualified variant ctor calls now emit `E-CTOR-EXPECTED-TYPE` when no expected variant type and ctor name matches a variant arm in scope.
- std.mem intrinsics are now restricted to toolchain-trusted modules (std./lang./drift.*) to prevent unsafe user access.
- Checker call validation now flags `CallTargetKind.TRAIT` on method calls in typed mode; added a regression unit test to lock this invariant.
- Unsafe gating now relies only on toolchain-trusted module list (no std.* prefix trust).
- Centralized toolchain trust check in type checker via `_is_toolchain_trusted_module` and reused for unsafe/rawbuffer gating.
- Typed HIR validator now rejects TRAIT CallTargets in MIR-bound functions for all call forms.
- `_candidate_visible` now takes explicit `current_module_id: int | None` to avoid visibility drift.
- Centralized unsafe gating in checker/unsafe_gate.py; resolver and typed validator call the shared gate.

## Open Questions
- Exact algorithm signatures in Drift syntax (defer until implementation).

## Planned Work (Pinned)
- Introduce std.mem RawBuffer<T> (trusted-only) with uninitialized capacity primitives: alloc_uninit, dealloc, ptr_at_ref/ptr_at_mut, read, write (and optional drop_in_place later). Keep RawBuffer as raw allocation only, no bounds checks inside runtime.
- Rebuild Deque on RawBuffer with ring-buffer layout (buf, head, len, gen) and phys(i) mapping; push/pop front/back use read/write on RawBuffer; growth uses alloc_uninit + move loop + dealloc; gen increments only on real structural changes and growth.
- Add Deque tests for wraparound order, growth under wrap, range invalidation (no-op pop does not invalidate; growth does), and sort/binary_search correctness on wrapped ranges.
- After Deque is stable, refactor Array to use RawBuffer with len/gen and uninitialized capacity slots; keep arr[i] Copy-only, &arr[i]/&mut arr[i] as place borrows.
