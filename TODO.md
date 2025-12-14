# TODO

[String]
- Remaining surface/runtime work:
  - Expose/route any user-facing string printing helper once available.
  - Keep expanding test coverage as features land (print, more negative cases).

[Error handling]
- Deferred follow-ups:
  - Captures (`^`): implement unwind-time frame capture (locals per frame + frames list), runtime representation, lowering/codegen, and e2e tests.
  - DiagnosticValue payloads: design/implement a stable ownership/handle model for opaque/object/array payload kinds so they can be stored in `Error.attrs` without ABI/lifetime churn.
  - Try-expression restriction: decide whether to relax “attempt must be a call” beyond call/method-call in v1 (spec + checker + lowering).
