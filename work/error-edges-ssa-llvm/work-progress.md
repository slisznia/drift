# **Work Progress — Outstanding TODOs**

# **Work Progress — Outstanding TODOs**

## Status

- **1. Make MIR the single source of truth for can-error** — ✔️ done. `driftc._annotate_can_error` seeds `can_error` from MIR bodies and raises on any `Throw` in a non-`can_error` function or call-with-edges to a non-`can_error` callee; `ssa_codegen` only asserts.
- **2. Negative tests for incorrect error-edge usage** — ✔️ done (plain call to can-error, call-with-edges to non-can-error). A separate “Throw in non-can-error” test is redundant because `_annotate_can_error` auto-marks functions containing `Throw` as `can_error`.
- **3. Improve placeholder values for `Throw` in non-Void functions** — ✗ open (still zero/undef fallback).
- **4. Generalize `try/catch` lowering** — ✗ open.

---

## **2. Add negative tests for incorrect error-edge usage**

Create failing SSA/MIR + e2e tests for:

* Plain call to a can-error function (no error edges). **(exists)**
* Call-with-edges to a non-can-error function. **(exists)**
* `Throw` inside a non-can-error function. **(not applicable while can_error is auto-seeded from Throw)**

Each test should assert a compile-time failure.

---

## **3. Improve placeholder values for `Throw` in non-Void functions**

Currently non-Void `{T, Error*}` returns on `Throw` use:

* `0` for integer `T`
* `None` constants for non-integer `T` (llvmlite hack)

Replace with a safer fallback:

* Zero-initialized constant for aggregate types when possible
  **or**
* A canonical opaque placeholder with a clear comment.

(Not required for correctness but improves IR quality.)

---

## **4. Generalize `try/catch` lowering**

After invariants are locked:

* Extend `try` lowering to support more expression forms,
  not only “call as last statement” or simple `try expr else expr`.
