# **Work Progress — Outstanding TODOs**

## **1. Make MIR the single source of truth for can-error**

Replace backend inference with strict assertions:

* If a function contains `Throw` but is not marked `can_error` → compile error.
* If a call terminator uses normal/error edges but the callee is not marked `can_error` → compile error.
* Backend no longer adds to `can_error_funcs`; it only verifies.

---

## **2. Add negative tests for incorrect error-edge usage**

Create failing SSA/MIR + e2e tests for:

* Plain call to a can-error function (no error edges).
* Call-with-edges to a non-can-error function.
* `Throw` inside a non-can-error function.

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
