## Rough edges / potential bugs

- Type inference logic is duplicated across _infer_hir_expr_type, _validate_array_exprs, and _validate_bool_conditions; they each
  maintain their own locals maps. This is brittle (now less urgent since params are seeded, but still a refactor target).
- Error reporting: duplicate-function rejection uses a thrown ValueError instead of a diagnostic; also span info is generally None in
  checker diags (known limitation, but worth noting).

  ## Proposed cleanup plan

1. Centralize expression typing helper
    - Factor out a single _infer_hir_expr_type-style helper that both array validation and bool-condition validation can use, seeded
      with the same locals. Avoid maintaining separate locals maps per pass.
2. Change duplicate-function handling to a diagnostic
    - Instead of raising ValueError in the parser adapter, surface a structured diagnostic (with a span when available).
3. Add/adjust tests after cleanup
    - Add a checker test where a function param xs: Array<String> is indexed; expect correct type and diagnostics on misuse.
    - Add a checker test for an if condition using a param of the wrong type; ensure the Bool check fires.

### Additional spec alignment tasks
- DONE: Spec now says mixed-type array literals are rejected at compile/type-check time (not parse-time).
- DONE: Removed duplicate “Optional API (minimal)” subsection from the spec.
- DONE: Parser adapter tests now use `fn main()` (canonical entry); drift_main is treated as a normal fn only.
