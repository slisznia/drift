# Try-expression attempt generalization — work progress

## Goal
Allow `try` expressions to accept any value-producing expression as the attempt,
not just calls/method calls (e.g., `try (a + b) catch { 0 }`).

## Current constraint
The AST already models `TryCatchExpr.attempt` as a general expression, but the
type checker enforces a call-only restriction. Lowering already accepts any
expression attempt.

## Plan
1) **Spec alignment**
   - Search the spec for any wording that implies the try attempt must be a
     call/method call.
   - Replace with: `try <expr> catch { <expr> }` where `<expr>` is any
     value-producing expression.
2) **Type checker**
   - Remove the "attempt must be a function call" restriction.
   - Require the attempt to be **may-throw**; if it is provably `nothrow`,
     emit an error (catch is unreachable).
   - Keep the "attempt must produce a value (not Void)" rule.
   - Preserve catch-arm restrictions (no control-flow statements in
     try-expression catch blocks).
   - Ensure the result type is still the join/unify of attempt type and catch
     expression type.
3) **HIR / lowering**
   - No changes expected; confirm `HTryExpr` lowering already handles arbitrary
     expressions.
4) **Diagnostics**
   - Update any error messages/tests that mention "call-only".
   - The remaining invalid-attempt diagnostic should be about `Void`, not
     "not a call".
5) **Tests**
   - Stage1/type-check tests:
   - `try (may_fail(1) + 2) catch { 0 }` is valid (non-call attempt that may throw).
   - `try (void_fn()) catch { 0 }` rejects (attempt is `Void`).
   - `try (1 + 2) catch { 0 }` rejects (attempt is `nothrow`).
   - `try (cond ? may_fail(1) : 2) catch { 0 }` is valid; `try (cond ? 1 : 2) catch { 0 }`
     rejects as provably nothrow.
   - `try arr[0] catch { 0 }` is valid (indexing can throw `IndexError`).
   - Parser coverage:
     - `try 1 + 2 catch { 0 }` binds as expected without parentheses (and is
       rejected as nothrow).

## Notes / risks
- Grammar impact is minimal: try-expression already accepts an expression.
- Main behavioral change is typing/diagnostics; runtime and lowering are already
  compatible.
