## Work progress

### Interfaces (dynamic dispatch)
- Fixed iface e2e failures by preferring declared type in HLet lowering (enables iface coercion and avoids CallIndirect on iface values).
- MIR iface init validator now treats iface-producing instructions as initialized (ConstructIface*, CallIface/Call*).
- Method-call lowering now consults typed expr types when receiver inference is missing (keeps iface calls on CallIface path).
- LLVM size/align modeling now treats TypeKind.INTERFACE as full iface layout (prevents under-allocation for env structs holding interface values).
- Interface inline flag is now a bitfield (bit0 inline, bit1 owns heap); runtime uses bit0 and iface drop frees only when owns-heap is set.

### Compiler infra (invariants plan)
- Added explicit plan to enforce MIR invariants at a single boundary: no unresolved types, no missing call metadata, and no by-value use of non-Copy locals without MoveOut.
- Next steps: add MIR validator for by-value non-Copy call args and centralize interface layout rules to avoid runtime/layout drift.
- Implemented MIR validator enforcing MoveOut for non-Copy by-value call args; added driver test `test_mir_invariants.py` to assert MoveOut is used when calling `take(String)`.
- Moved MIR validators into `lang2/driftc/mir_validate.py` and updated stage2 tests to import `validate_mir_*` helpers from the new module.
- Stage2 call lowering now uses `_lower_call_arg` for direct calls and method receivers/args to enforce MoveOut for non-Copy by-value parameters.

### Concurrency (FutureGroup)
- Resolved `FutureGroup.join_all` codegen failure by substituting impl type args in MIR lowering (stage2 now resolves declared types using impl target type args).
- Array literal lowering now falls back to impl-type substitution when element type is forward-nominal.

### MIR invariants / coverage
- Added MIR validation for unresolved layout types (TypeVar/ForwardNominal/Unknown) across array/rawbuffer/ptr/struct/variant/iface/typed ops.
- Added e2e `generic_impl_array_literal` to exercise generic impl + array literal lowering with concrete instantiations.
- Added driver fuzz-style test `test_generic_impl_array_literal_fuzz_fixed_seed` to catch forward-nominal leakage in generic impls.

### Concurrency (callback inference)
- Fixed `std.core.callbackN` inference for lambdas without expected type by allowing return type inference (prevents forward-nominal fallback in spawn tests).
- `spawn_cb` call paths now move non-Copy locals when passed by value (prevents callback env double-free/use-after-free).
- Updated eventfd reactor e2e to capture fd by copy (move capture zeroed fd, preventing wakeup).
- Added a timeout option to the codegen e2e runner and ensured `concurrent_reactor_timerfd_unpark` registers a deadline before parking (prevents hangs).

### Concurrency (test sweep)
- Removed explicit local type annotations in concurrency/future e2e tests (kept behavior by improving match inference in checker).

### MIR invariants
- Fixed PtrWrite validation to avoid requiring ptr_ty (PtrWrite only carries elem_ty); unblocked cell_counter_fn0 e2e.
- Wrapping-u64 validator now resolves existing scalar TypeIds (avoids creating fresh Uint64/Int/etc. ids); fixes false failures in wrapping_u64_ops/hash_wrap_overflow.

### Containers (e2e cleanup)
- Removed explicit local type annotations in treemap/hashmap/treeset e2e cases (match results + literals), kept interface coercion types intact.

### E2E inference sweep (Int/Bool)
- Removed explicit `: Int` / `: Bool` local annotations across many e2e cases (interfaces/fnptr/iter/try/etc.) to push inference; kept coercion-critical types.

### E2E inference sweep (strings/iter/methods)
- Removed explicit `Optional<&Int>` / `String` / `Array<String>` / local `Point` annotations where inference is clear (iterator, string, and method call e2e cases).

### Concurrency (join_timeout/cancel)
- Ensured join_timeout checks cancellation before zero-timeout to return Cancelled when appropriate.
- Added e2e `concurrent_future_join_timeout_nonzero_ok` to cover non-zero timeout success for Future.
- Runtime cancel/drop now drops callback env without executing user code when not started.

### Call resolution (module alias)
- Added regression test to ensure `module_alias.fn()` resolves as a free call (not a method call on a value).

### Call resolver refactor (CallIntent)
- Introduced a minimal `CallIntent` and propagated expected arg types for method calls after resolution (first step toward explicit expected-type plumbing).
- Extended expected-type propagation to free/UFCS calls in `resolve_call_expr` and added driver regression `test_expected_type_propagation_method_arg.py`.
- Added deferred-arg typing for nested calls: initial arg calls may return Unknown without diagnostic, then retyped with expected parameter types after candidate selection.
- Inference now ignores incompatible expected-return shapes (but preserves nominal base matches and bare typevars), fixing nested expected-return inference (e.g., spawn_future inside add).
- UFCS trait calls on concrete receivers now resolve to direct impl targets (avoids trait call targets in typed mode).
- Deferred local lambda inference from call sites: untyped lambda bindings are typed on first call with arg-driven param types, inferred return type, and inferred can-throw (used to allow `val fp = |x| => x + 1; fp(3)` without annotation).

### Traits (enforce_fn_requires)
- Fixed lambda-based generic inference for Fn0 bounds in trait enforcement (binds type params from TypeExpr args like `Fn0<T>`).
- Fixed UFCS trait resolution for direct impls: resolve candidates by trait + receiver base (non-struct types included), enforce visibility and `require` predicates, and improve requirement diagnostics to include the expected trait label.
- UFCS trait impl visibility now treats pub as globally visible (private only within defining module) to allow generic stdlib calls to resolve user impls.

### Concurrency (Void result)
- Added MIR/LLVM support for Void values so `VirtualThread<Void>` can store and return Void safely (ConstVoid + zero-value handling).

### Concurrency (executor plumbing)
- Added `exec_create` runtime hook and `build_executor` API; default executor is lazily created with single-thread policy; `Executor`/`ExecutorPolicy` are `Copy`.
