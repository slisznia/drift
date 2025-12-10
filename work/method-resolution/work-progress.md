# Method Resolution v1 – Work Progress

## Goal
Implement real method/function resolution per `docs/design/spec-change-requests/drift-method-resolution-v1.md`: resolve calls by receiver/argument types to a concrete signature/method ID (including module), drive auto-borrow from `self_mode`, and annotate typed HIR for the borrow checker.

## Plan / TODO
2) **Typed HIR / resolution annotations**  
   - Extend typed call representation (node or side table) to carry: `resolved_callee_id`, `resolved_param_types`, `resolved_result_type`, `self_mode`, `receiver_autoborrow_kind`.
   - Type checker computes receiver/arg types, then resolves against registry: arity + exact type equality, receiver compatibility with auto-borrow `T -> &T/&mut T` only, no promotions. Errors for no match/ambiguity.

3) **Borrow checker integration**  
   - Consume resolved call metadata (no name-based lookup).  
   - If `self_mode` is `&/&mut`, create temporary receiver loan; if `self` by value, treat as move. Auto-borrow kinds come from `receiver_autoborrow_kind`.

4) **Overloading scope**  
   - If overloading is kept, include arg types in selection; module is part of `method_id`/visibility. No return-type overloading; no inference-based overload picking in v1.

## Status
- Parser/AST/HIR support `implement Type { ... }` blocks; methods carry `is_method/self_mode/impl_target_type_id`, symbol names (`Type::method`), and display `method_name`.  
- Per-type duplicate method checks enforced; free-vs-method name collisions are rejected.  
- Type resolver builds signatures keyed by symbol; method names are preserved for registry display.  
- Callable registry + resolver drive type checker call resolution for both functions and methods; typed HIR stores resolved callees.  
- Borrow checker consumes resolved callees for auto-borrow; name-based method heuristics are only a legacy fallback.
- Method registry buckets methods per module `(module_id -> (impl_target_type_id, name) -> decls)`, supporting same-name methods across types/modules with visibility filtering.  
- Module IDs are threaded from parser signatures into the registry/driver and used for resolution visibility.

## Next Steps
- Harden method resolution tests: shared method names across types, visibility/module filtering, ambiguity errors, receiver by-value cases.  
- Expand method-resolution tests for ambiguity/visibility and receiver by-value cases.
