# Method Resolution v1 – Work Progress

## Goal
Implement real method/function resolution per `docs/design/spec-change-requests/drift-method-resolution-v1.md`: resolve calls by receiver/argument types to a concrete signature/method ID (including module), drive auto-borrow from `self_mode`, and annotate typed HIR for the borrow checker.

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
