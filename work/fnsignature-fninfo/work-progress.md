## FnSignature/FnInfo enrichment (lang2) — progress

### Current state
- `FnSignature` scaffold now includes placeholders for:
  - `name`, `return_type`, `throws_events`
  - optional `param_types` (raw shapes), `param_type_ids` (resolved via TypeTable)
  - `declared_can_throw` flag, `loc`, `is_extern`, `is_intrinsic`
  - resolved `return_type_id` / `error_type_id`
- `FnInfo` now owns an optional `signature` and an `inferred_may_throw` flag; legacy fields remain for backward compatibility.
- Checker respects `signature.declared_can_throw` when provided, resolves return/param types via TypeTable, and threads the signature into `FnInfo`.
- Best-effort “may throw” marking: the checker can walk provided HIR blocks, mark `FnInfo.inferred_may_throw` when it sees throws/throwing calls, and emit a diagnostic if a may-throw function is not declared throws (stub-level, context-insensitive).
- Tests remain green (`just lang2-test`).

### Pending/next steps
- Build real `FnSignature` from the type checker:
  - Populate `param_type_ids` and `return_type_id` from actual type resolution.
  - Set `declared_can_throw` from parsed `throws` clauses; include params/loc/is_extern/intrinsic as needed.
- Use signatures for call/type checks:
  - Arity/param type checking and call result typing should consult `FnSignature`.
  - Introduce a consistent `call_may_throw` helper based on callee `FnInfo` and use it at call sites.
- Centralize throw diagnostics:
  - Compute `inferred_may_throw` once per function (walk body) with basic try/throw/call awareness.
  - At function finalization, emit “must be declared throws” when `inferred_may_throw && !declared_can_throw`; optional warn on “declared throws but no throw”.
- Gradually phase out legacy shims (`declared_can_throw` map, raw return_type strings) once real signatures flow from the front end.
