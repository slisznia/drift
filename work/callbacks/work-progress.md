# Work Progress (Callbacks)

## Status summary (2026-01-24)

Completed
- Static callback traits: Fn0/Fn1/Fn2 in std.core.
- Dynamic callback interfaces: Callback0/1/2 in std.core.
- Explicit bridge: callback0/1/2 intrinsics (owned-only MVP) with vtable-backed iface values.
- Interface values lowered as `%DriftIface = { i8* data_ptr, i8* vtable_ptr }` and vtable slot-0 dispatch in LLVM v1.
- Callback e2e coverage: indirect call, stored in struct, param passing; IR asserts vtable slot-0 load and no direct call.
- Arc/Mutex MVP stubs in std.concurrency (single-threaded semantics) + callback example e2e.
- Borrow/BorrowMut traits in std.core (nothrow) and impls for Arc<T>/MutexGuard<T>.
- Argument coercion via Borrow/BorrowMut; inference now uses Borrow/BorrowMut trait args to infer generic T in free calls.
- Spec: Borrow/BorrowMut coercion and inference documented; nothrow aligned.
- E2E: callback_arc_mutex_full_mutation uses coercion (`conc.lock(e.state)`), plus combo tests for Borrow/BorrowMut selection and rejection.
- Owned callbacks now accept capturing lambdas (capture-by-move for callback context); env is heap-allocated with drop thunk in vtable.
- E2E: effective_drift_emitter_example mirrors the book pattern with multiple handlers and shared Arc<Mutex<...>> state.
- Fix: method-call boundary upgrade now uses package identity; unknown packages no longer force can-throw (prevents std.* nothrow from being upgraded).
- Fix: method-boundary visibility uses module_packages and ignores std.* / lang.core; debug assert catches nothrow call marked can-throw without boundary.
- Regression: Callback1.call nothrow ABI asserted via call_info.can_throw == false.
- Regression: std.* method call remains nothrow in stubbed runs (no boundary upgrade).
- Update: cross_module_method_requires_try e2e now expects success in stubbed-package context.
- Tests: driver helpers now install explicit module package ids for boundary tests; parser accepts overrides in test_build_only.
- Tests: callback dynamic dispatch test now resolves main as qualified name; for-loop default borrow test updated for non-Copy elements.
- Fix: for-loop UFCS calls now record instantiations for Iterable::iter/SinglePassIterator::next; codegen no longer sees typevars.
- Tests: for-loop borrow semantics updated to deref items or use `move` where iteration consumes.
- Fix: callback env drop thunks now call `drift_cb_env_free` (paired runtime API) instead of hard-wiring `drift_free_array`.

In progress / open
- None.

Post-MVP / future
- Borrowed callback objects (CallbackRef) require a lifetime/region model.
- Capture-by-reference into owned Callback should remain rejected until lifetimes exist.
- Optional vtable expansion (size/align/clone) if moving toward SBO or non-heap callbacks.
- ReentrantMutex (name) requested; track in todo.md.
