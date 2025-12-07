## FnSignature/FnInfo enrichment (lang2) — progress

### Current state
- `FnSignature` scaffold now includes placeholders for:
-  - canonical TypeId fields: `param_type_ids`, `return_type_id`, `declared_can_throw`, `loc`, `is_extern`, `is_intrinsic`, `error_type_id`
-  - legacy/raw fields remain (`return_type`, `param_types`, `throws_events`) but are secondary.
- `FnInfo` now owns an optional `signature` and an `inferred_may_throw` flag; legacy fields remain for backward compatibility.
- Checker prefers pre-resolved TypeIds in signatures; falls back to legacy string/tuple resolution only when ids are missing. `signature.declared_can_throw` overrides heuristics; throws_events default `declared_can_throw` to True when present.
- Best-effort “may throw” marking: the checker can walk provided HIR blocks, mark `FnInfo.inferred_may_throw` when it sees throws/throwing calls, and emit a diagnostic if a may-throw function is not declared throws (stub-level, context-insensitive).
- Try-sugar validation now inspects `signature.return_type_id` via TypeTable to decide if an operand is FnResult.
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
