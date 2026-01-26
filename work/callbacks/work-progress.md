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
- Fix: interface call lowering now permits can-throw; thunk pointer type accounts for FnResult return when can_throw is true.
- Interfaces now support parent lists; schema stores parent base ids and validates duplicates/cycles.
- Interface vtables use per-interface segments with slot-0 drop; deterministic linearization with diamond dedupe.
- Interface upcast lowers to vtable_ptr retarget (segment offset) via `IfaceUpcast` in MIR.
- Dynamic interface values now supported (non-callback): boxed iface values + `CallIface` slot lookup; drop uses slot-0.
- ABI doc updated with interface value layout, segment rules, and upcast semantics.
- E2E: dynamic interface nothrow/throw calls (`interface_dynamic_call_nothrow`, `interface_dynamic_call_throw`).
- E2E: interface parent/upcast/diamond/slot ordering (`interface_parent_method_via_child`, `interface_upcast_parent`, `interface_diamond_upcast`, `interface_method_slot_order`).
- Fix: interface coercion is now validated for interface→interface assignments (parent upcast allowed, mismatched interface rejected), both in typed checker and stubbed checker.
- Fix: restored callsite CallInfo emission after indentation regression in type checker/stub checker.
- Fix: stub checker now infers HQualifiedMember calls via CallInfo when available (keeps for-loop UFCS/trait calls typed).
- Fix: stub match validator skips scrutinee-type errors when binder_field_indices are already present (avoids false errors on normalized matches).
- Fix: stub checker now walks statements even when on_stmt hooks are set, so void/array/match validators run for let-bound expressions.
- Fix: CallIface lowering now uses FnResult carrier for can-throw interface calls; empty struct construction supported in LLVM v1.
- Update: ABI now defines interface inline storage (`INLINE_BYTES = pointer_width * 4`), and codegen supports inline storage for ConstructIfaceValue with an `is_inline` flag.
- Update: ABI fingerprint emitted in package manifest and enforced as hard-fail on mismatch across packages and vs toolchain target.
- Tests: package ABI fingerprint mismatch rejection; manifest asserts `iface_inline_bytes = pointer_width * 4`; updated strict-mode package test to include abi_fingerprint in manual manifest.
- Update: callback0/1/2 intrinsic signatures now mark param 0 as retaining (param_nonretaining=False) to reject borrowed captures at boxing.
- E2E: borrowed_capture_interface_coercion_rejected compile-fail added (borrowed capture to CallbackN rejected).
- Stage1: borrowed capture allowed when passed to a non-retaining param (lambda validation test).
- Cleanup: boundary decisions now require package ids (no std/lang.core string exemptions); parser assigns package ids consistently (std.* local for workspace builds, lang.core pinned) and asserts on missing module_packages.
- Package linking: prevent duplicate lang.core Optional during type-table import; packages no longer claim lang.core nominals in provided_nominals.
- Cleanup: stdlib ownership now derived from stdlib_root path (not module name); added regression test that a workspace module named std.fake stays in the local package.
- Cleanup: qualified-member ctor resolution now relies on resolve_opaque_type (no hard-coded lang.core/std.core fallbacks in call_resolver).
- Cleanup: centralized module_packages guard added at driftc entry; compile_stubbed_funcs auto-populates module_packages for known modules, driftc main fails fast if entries are missing.
- Tests: driver guard verifies driftc workspace module_packages are present; stage2 stubbed compile fills module_packages for ad-hoc tests.
- MIR: added pre-codegen call-type invariant to reject unresolved TypeVar signatures on concrete calls (skips generic defs; enforces on CallIndirect/CallIface and concrete Call).
- Guardrail: stage2 callback lowering now asserts that owned callback envs never include borrowed captures (REF/REF_MUT).
- For-loop: added stage1 regression ensuring borrowed temporary iterables are bound to a hidden local before iteration.

In progress / open
- None.

Post-MVP / future
- Borrowed callback objects (CallbackRef) require a lifetime/region model.
- Capture-by-reference into owned Callback should remain rejected until lifetimes exist.
- Optional vtable expansion (size/align/clone) if moving toward SBO or non-heap callbacks.
- ReentrantMutex (name) requested; track in todo.md.
