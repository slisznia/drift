# Methods and Fields — Work Progress

This tracker covers method-body ergonomics and member access rules needed to support idiomatic code like:

```drift
struct Point(x: Int, y: Int)

implement Point {
    fn move_by(self: &mut Point, dx: Int, dy: Int) returns Void {
        x += dx
        y += dy
    }
}
```

It is scoped to the `lang2/` compiler implementation, but the language rules are specified in `docs/design/drift-lang-spec.md`.

## Decisions (pinned)

- `->` is the surface operator for **member-through-reference** access (`ptr->field`) and is already part of the grammar.
- Method calls use `.` at the surface (receiver auto-deref is handled by method resolution rules; this keeps call syntax uniform).
- **Implicit `self` member lookup** is a language rule (spec-first):
  - Inside method bodies, unknown identifiers may resolve to members of `self`.
  - Desugars to `self.name` for owned receivers and `self->name` for borrowed receivers.
  - Applies in both value contexts and place contexts (assignment/borrow/move).

## Done

- Spec updated with §3.9 “Implicit `self` member lookup (method bodies)”.
- Added `+=` (augmented assignment) end-to-end:
  - Parser/AST/stage0 node `AugAssignStmt`
  - HIR node `HAugAssign` + normalization support
  - Type checker + borrow checker handling
  - HIR→MIR lowering as read-modify-write
- Implemented implicit `self` member lookup in stage1 lowering (method bodies):
  - Unknown identifiers that match receiver fields lower to `HPlaceExpr(self, Deref?, Field)`
  - Unqualified calls to known methods lower to `HMethodCall(self, name, ...)` when not shadowed by locals or free functions
- Fixed parser implement-body builder: `implement` blocks now collect `implement_func` items as methods.
- LLVM codegen now quotes non-identifier function symbols (e.g. `@"Point::move_by"`) so scoped method symbols are valid IR.
- Added e2e coverage:
  - `lang2/codegen/tests/e2e/method_move_by_implicit_self`
  - `lang2/codegen/tests/e2e/method_implicit_self_shadowing`

## Next

- Parser/AST/Stage0:
  - Ensure `->` is represented explicitly in the surface AST (already via `Attr(op="->")`).
  - Ensure augmented assignment (`+=`) is supported in the statement grammar and AST.

- Stage1/HIR:
  - Implement implicit `self` member lookup during name resolution in method bodies.
  - Ensure member lookup works in both expression and place contexts (so `x += 1` becomes a place update on the member).

- Type checking:
  - Validate that implicit member resolution follows the exact precedence in the spec (locals/params → module scope → self members).
  - Ensure ambiguous names require explicit `self...` access.

- Lowering/codegen:
  - Lower `self->field` to canonical place projections (deref + field GEP) and allow it as an lvalue.
  - Extend augmented assignment beyond `+=` when needed (`-=`, `*=`, etc.) with the same RMW semantics.

- Tests:
  - Add an e2e test for `Point.move_by` that uses `x += dx` / `y += dy` inside the method body (implicit `self` lookup).
  - Add negative e2e tests:
    - local variable shadowing a member name (local wins; member requires `self->x` / `self.x`).
    - invalid `+=` target (non-place) produces a typecheck diagnostic with span.
