# Method Resolution v1 – Work Progress

## Goal
Implement real method/function resolution per `docs/design/spec-change-requests/drift-method-resolution-v1.md`: resolve calls by receiver/argument types to a concrete signature/method ID (including module), drive auto-borrow from `self_mode`, and annotate typed HIR for the borrow checker.

## Plan / TODO
1) **Method registry**  
   - Build registry entries during symbol collection: `method_id` (fully qualified incl. module), `name`, `impl_target_type_id`, `param_types` (receiver first for methods), `result_type`, `self_mode`, visibility.  
   - Index to allow overloading: `(module, name, impl_target_type_id)` with multiple entries; selection later also considers arg types.

2) **Typed HIR / resolution annotations**  
   - Extend typed call representation (node or side table) to carry: `resolved_callee_id`, `resolved_param_types`, `resolved_result_type`, `self_mode`, `receiver_autoborrow_kind`.  
   - Type checker computes receiver/arg types, then resolves against registry: arity + exact type equality, receiver compatibility with auto-borrow `T -> &T/&mut T` only, no promotions. Errors for no match/ambiguity.

3) **Borrow checker integration**  
   - Consume resolved call metadata (no name-based lookup).  
   - If `self_mode` is `&/&mut`, create temporary receiver loan; if `self` by value, treat as move. Auto-borrow kinds come from `receiver_autoborrow_kind`.

4) **Overloading scope**  
   - If overloading is kept, include arg types in selection; module is part of `method_id`/visibility. No return-type overloading; no inference-based overload picking in v1.

## Status
- Auto-borrow uses signatures for functions/methods, but method resolution is still **name-only** (no registry, no receiver-type key).  
- Borrow checker still guesses method signatures by name; typed HIR has no resolved callee metadata.  
- Type checker produces per-expression types; `ref_mut` plumbed; good foundation for proper resolution.

## Next Steps
- Define the registry data structure and emit entries (incl. module) during symbol collection.  
- Extend TypedFn/typed call info to store resolved method/function IDs and param/return types.  
- Implement resolution in the type checker using receiver/arg types and registry; drop name-only method lookup.  
- Hook borrow checker to resolved call metadata for receiver auto-borrow/moves.  
- Add tests for disambiguation (module/name, receiver type, overloaded args) and for correct auto-borrow based on `self_mode`.
