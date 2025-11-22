# Drift TODO / Next Steps

## Runtime and semantics
- Implement `try / catch` and the inline `try expr else fallback` shorthand in the interpreter.
- Wire `^` capture so unwinding records per-frame locals and backtrace handles in `Error`.
- Add bounds checks for arrays that throw `IndexError(container = "Array", index = i)`.
- Support `source_location()` intrinsic returning `SourceLocation` (file, line).

## Frontend and IR
- Define a minimal typed IR (ownership, moves, error edges) with a verifier.
- Lower the current AST/typechecker output into the IR; add golden tests for the lowering.
- Prototype simple IR passes (dead code, copy elision/move tightening).

## Tooling
- Expand the linter/just recipes to cover new syntax (try/catch, inline try-else) once implemented.
- Add tests for the new error-handling features (inline catch-all, event-specific catches).

## Docs
- Keep `docs/history.md` updated as features land.
- Add short “how to read IR” note once the IR spec is drafted.
