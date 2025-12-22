# Closures v0 + Borrow v1.5 — work plan

Goal: land usable, non-escaping closures with inferred captures and stronger borrow semantics (NLL-lite), using the existing pipe-style lambda grammar.

## Status (current)
- Lambda syntax + optional `returns Ty` are wired through grammar/parser/AST/HIR and documented.
- Non-escaping enforcement is active (immediate-call + `nonescaping` param), including method-call resolution.
- Capture discovery is implemented (locals/field projections only), with deterministic ordering and overlap diagnostics.
- Lowering emits env + hidden function for immediate-call lambdas; block-bodied lambdas supported; hidden lambdas are collected for later stages.
- Borrow checker treats captured `&/&mut` as call-scoped loans and enforces overlaps; method-call variants (including receiver auto-borrow) are covered.
- Try-sugar (`expr?` / HTryResult) removed from the compiler path and tests; only try/catch remains.
- E2E closure smoke tests added (capture + block body, shadowing, try/catch in lambda).

## Surface decisions (frozen for v0)
- Lambda syntax: **pipe-style with `=>`**, already in grammar: `|params| => expr` and `|params| => { ... }`.
- Avoid Rust-style `|params| expr` (no `=>`) to keep pipeline (`|>`) precedence unambiguous.
- Do not add `fn(...) { ... }` literals now (would require grammar work); keep docs/examples consistent with pipe-lambdas.
- Captures are **inferred**, not explicit lists (spec updated to match).

## Scope fences (non-negotiable for v0)
- Closures are **non-escaping**: cannot be stored, returned, or passed where lifetime outlives the creation site; allowed only in call position or to known synchronous callees.
- Passing closures to callees is gated by a **typed contract**: `nonescaping` parameter annotation.
- Explicit capture kinds only: copy, move, `&`, `&mut`; no implicit autoderef.
- Place model (v0): locals/params, field projections, explicit deref, indexing (treated conservatively as borrowing the base).
- NLL-lite: end borrows at last use via simple CFG awareness (blocks, if/else merges, early returns, per-iteration if possible).

## Milestone steps
1) Parser/AST: ensure `LambdaExpr ::= "|" params? "|" lambda_returns? "=>" (Expr | Block)` is wired; add AST node carrying params + body + optional return type.
2) Capture analysis: compute free vars as **places** (local + field projections only in v0); infer capture kind from usage; enforce non-escaping via validator.
   - Current implementation is conservative: read-only captures are shared borrows until Copy/Move can be inferred from typed data.
3) Lowering: synthesize env struct + hidden fn(env_ptr, args...) -> ret; call sites pass env + args; ABI remains internal.
4) Borrow checker upgrades: apply overlap rules to captured borrows and closure body; treat capture loans as call-scoped across immediate call and `nonescaping` params.
5) Tests (add early, driver-style):
   - Borrowed local captured and used after closure (reject overlap).
   - Borrowed field `&s.f` captured, mutate `s` after (reject).
   - Immutable vs mutable overlap on same place (`&x` captured, later `&mut x` or assignment).
   - Branch-local borrow: borrow only in one branch, use after merge (should pass).
   - Loop body borrow ends per iteration (start conservative, refine later).
   - Move capture vs later borrow of moved value (reject).
   - Temp capture (e.g., `|| &foo()`): define and test rejection until temp lifetime rules are set.
   - Non-escaping enforcement: assign/return closure value -> reject.
6) Docs sync: update spec to reflect pipe-lambda syntax + inferred captures; remove/convert `fn(...) { ... }` inline examples to `|...| => { ... }`.

## Follow-on (after v0 closes)
- Concurrency hook: `spawn(|| ...)` bans borrowed captures (requires capture analysis in place).
- Optional aliasing refinement for indexed borrows (disjoint indices) after core semantics stabilize.
