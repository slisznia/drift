Big picture: the refactor is **basically aligned** with the ABI + spec, but right now you only implement:

* event **codes** (correctly shaped for the ABI),
* catch-all **statement** `try` with intra-function unwinding,
* and function-level throw summaries.

What’s **missing** relative to the docs is:

* event-**name-based** matching (`catch MyError(e)`),
* expression `try … catch …`,
* and the pieces that carry full `Error` diagnostic info (`attrs`, `ctx_frames`, stack) into the runtime.

Below is how things line up + what I’d do next.

---

## 1. What the docs say you must support

### 1.1 Exception event codes (ABI doc)

ABI defines the **single source of truth** for event codes:

* Every `Error` has a 64-bit `event code` (`Error.code: I64` in Drift, `uint64_t` in C).

* Layout: top 4 bits = `kind`, low 60 bits = `payload`. 

  ```text
  bits 63..60 : kind
  bits 59..0  : payload60
  ```

* Kinds:

  * `TEST=0`, `USER=1`, `BUILTIN=2`, others reserved. 

* Construction:

  ```c
  uint64_t drift_event_code(uint64_t kind, uint64_t payload60) {
      return (kind << 60) | (payload60 & PAYLOAD_MASK);
  }
  ```

* **User exceptions**: payload = `xxHash64(FQN) & PAYLOAD_MASK`, kind = `USER`. 

* **Builtins**: payload is an explicit table, kind = `BUILTIN`. 

Modules must also export metadata `(FQN, kind, payload60, event_code)` so tools can map codes ↔ names. 

### 1.2. Language-level exception semantics (spec)

Language-level picture:

* Single `Error` type with **event name**, **attrs**, **ctx_frames**, **stack**. 

* `exception Name { fields… }` defines an **event**; `throw Name { … }`:

  * computes a deterministic `event_code`,
  * builds an `Error` with event name, attrs, ctx, stack. 

* Exception fields and `^`-captured locals are converted to `DiagnosticValue` and stored in `attrs` / `ctx_frames`. 

* `try/catch`:

  * **Statement**:

    ```drift
    try { risky() }
    catch MyError(e) { ... }
    catch { ... }        // catch-all
    ```

    *Matches by event name*; event arms first, then catch-all; if nothing matches and no catch-all, error is rethrown. 

  * **Expression**:

    ```drift
    val x = try parse(input) catch BadFormat(e) { 0 } catch { 1 }
    ```

    Sugar over a statement `try` that returns from the block. Attempts must be **calls**. 

* Internally, everything is conceptually `Result<T, Error>`; exported functions always use an error-aware ABI (`{T, Error*}` or `Error*`). 

So the compiler must:

1. Generate ABI-correct **event codes** from exception declarations.
2. Build `Error` values with those codes and the attrs/ctx payload.
3. Implement `try/catch` dispatch based on **event name**, but it can use **codes** under the hood.
4. Treat exported functions as **can-throw entry points** with `Result<T, Error>` calling convention.

---

## 2. Where the current refactor stands vs that picture

### 2.1. Event codes & MIR

Your lang2 pipeline already has the right **shape**:

* `ConstructError(dest, code, payload)` in MIR; `code` is a value that should be the 64-bit event code.
* `_lookup_error_code` in `HIRToMIR` uses `exc_env[dv_type_name]` to supply the code, falling back to `0` if unknown.

That’s compatible with the ABI doc as long as:

* `exc_env` actually stores the `drift_event_code(kind, payload60)` computed per `drift-abi-exceptions.md`. 
* The type checker ensures `code` is `Int64` in the type system.

On the **analysis** side:

* `MirPreAnalysis` tracks `ConstInt` → code literal mapping and uses `code_to_exc[event_code] → "DVName"` to populate `exception_types`.
* `ThrowSummaryBuilder` then gives you per-function:

  * `constructs_error` (any `ConstructError` present),
  * `exception_types` (set of DV names),
  * `may_fail_sites`.

This is exactly how it should plug into the ABI metadata: `code_to_exc` is the “reverse index” supplied from the module metadata you export.

So: **event codes and exception-type propagation are aligned** with the ABI doc, structurally.

### 2.2. ErrorEvent & try/catch

You now have:

* `ErrorEvent(dest, error)` in MIR → project the event code from an `Error`. That’s the IR hook for `drift_event_kind`/`drift_event_payload`-style access. 
* `HTry` lowering:

  * `throw` constructs an `Error` via `ConstructError` and, under a try, routes the error into the catch binder local then jumps into `try_catch`.
  * At the top of `try_catch`, you already emit:

    ```mir
    LoadLocal(err_val, catch_name)
    ErrorEvent(code_val, err_val)
    ```

So your MIR has all the **raw data** that the spec expects:

* For each caught error, you have the `Error` value,
* and its `event_code` via `ErrorEvent`.

From here, **event-name matching** is just “compare `code_val` against constants for each exception arm,” which matches the idea that the integer encoding is an implementation detail. 

The gaps:

* HIR/AST only models **single catch-all** right now; the spec allows `catch Name(e)` and multiple catch arms. 
* There’s no dispatch chain yet — you always go to one catch block per try, not per-arm blocks with comparisons + rethrow.

### 2.3. Error payload: attrs, ctx_frames, stack

The spec’s `Error` struct has `event: String`, `attrs`, `ctx_frames`, `stack`. 

Your current pipeline:

* Treats `payload` in `ConstructError(code, payload)` as “whatever runtime needs to build a full `Error`”. You’re not yet:

  * projecting `event` name,
  * building `attrs` from exception fields via `Diagnostic.to_diag()`,
  * or capturing `ctx_frames` / `^` locals.

That’s fine *for now* — these are runtime + later lowering concerns — but we need to be sure the IR doesn’t make any wrong assumptions:

* As long as `ConstructError` stays generic (“code + opaque payload for the runtime”), you haven’t locked yourself out of matching the spec.

You’ll eventually need:

* A clear, agreed meaning for `payload`: likely some internal representation of `{event_fqn, args_as_DiagnosticValue}`, or a pointer/handle constructed by the runtime helper that knows how to fill `Error.attrs` and `Error.event`.

But that’s a **separate** refactor; nothing in current lang2 contradicts it.

### 2.4. Result model & exported functions

Spec says:

* Conceptual model: every function is `Result<T, Error>`. 
* Exported functions **always** use the `Result<T, Error>` ABI encoding (`{T, Error*}` or `Error*`). 

Your lang2 design:

* Internally: functions that can throw return `FnResult<R, Error>`; `throw` lowers to `ConstructResultErr` + `Return`. That matches the conceptual `Result<T, Error>` model.
* You now have `ThrowSummary` and `MirPreAnalysis` to tell you which functions **actually construct** errors and what types.

What you haven’t wired yet, but the ABI/spec expect:

* Checker/SSA must use `ThrowSummary` + type info to enforce:

  * “No `construct_error` in functions that don’t return `FnResult<_, Error>`.”
  * “Every exported function uses the error-aware calling convention, regardless of whether it actually throws.”

Again, the current refactor is **compatible** with this; you just haven’t turned on those checks.

---

## 3. Concrete next step that aligns with both docs

Given all of that, the most important next step — and one that directly ties the refactor to the spec/ABI — is:

> **Implement multi-arm, event-based try/catch lowering in MIR, using event codes from exception declarations.**

That means:

### 3.1. Extend HIR/AST to match the spec’s catch forms

You need HIR nodes (and AST lowering) that can represent:

* `catch { … }` — unnamed catch-all.
* `catch e { … }` — catch-all with `Error` binder.
* `catch EventName(e) { … }` — event-specific catch.
* Multiple arms in order. 

Right now you only have a single `HTry` with `catch_name` and `catch_block`. That needs to become:

```python
@dataclass
class HTry(HStmt):
    body: HBlock
    catches: list[HCatchArm]

@dataclass
class HCatchArm:
    event_name: Optional[str]  # None for catch-all
    binder: Optional[str]      # None when no binder
    block: HBlock
```

AST→HIR just fills this from the surface syntax as described in the spec.

### 3.2. Lower that HTry to MIR using ErrorEvent + event codes

In `HIRToMIR`:

* Keep the **try-body** lowering & `_try_stack` behavior exactly as-is: `throw` still routes into a single **dispatch** block, not directly to a final catch.

* Change the catch lowering to:

  1. Build one **dispatch block** per `try`:

     * Entry: has the `Error` value in `catch_error_local` (from the try stack).
     * Emit `LoadLocal(err_val, catch_error_local)` + `ErrorEvent(code_val, err_val)`.

  2. For each **event arm** `catch EventName(binder) { … }`:

     * Look up its event code via the same exception-metadata table used in `_lookup_error_code`.

     * Emit:

       ```mir
       ConstInt(dest=code_k, value=EVENT_CODE_FOR_EventName)
       BinaryOp(dest=tmp, op=EQ, lhs=code_val, rhs=code_k)
       If(cond=tmp, then_block=catch_k, else_block=next_check_or_fallback)
       ```

     * In `catch_k`:

       * If there is a binder:

         * `StoreLocal(binder, err_val)` (or copy to binder).
       * Lower the catch block body.
       * Fallthrough to the shared `try_cont` block if not terminated.

  3. Handle **catch-all**:

     * If there’s a catch-all arm (with or without binder), the final “else” of the dispatch chain jumps directly to its block.
     * If there’s **no catch-all**, final “else” must `rethrow`: just `throw` the same `Error` again:

       * You can lower this as either:

         * Another `throw` HIR node you synthesize, or
         * Directly `ConstructResultErr(err_val)` + `Return` if you’re at the function boundary.
       * For intra-function unwinding, if there’s an outer `try`, you can reuse `_try_stack` to bubble to its dispatch, exactly like the old lang/ design.

This matches the spec’s semantics:

* Event arms tested in source order, then catch-all, then rethrow if nothing matches. 
* Matching is by event **name** at the spec level, even though you implement it via event **codes** (ABI).

And it lines up exactly with the ABI doc: all decisions are based on the 64-bit code produced per `drift-abi-exceptions.md`. 

### 3.3. Wire exception metadata consistently

To keep everything coherent:

* Use a single source for exception metadata:

  * For `_lookup_error_code` in HIR→MIR (throw sites).
  * For `code_to_exc` in pre-analysis + ThrowSummary (analysis).
  * For `EventName` → event code in try/catch lowering.

* That metadata must be computed according to `drift-abi-exceptions`:

  * `kind = USER` for user exceptions, `payload60 = xxHash64(fqn) & PAYLOAD_MASK`. 
  * Builtins use the catalog’s explicit payload60s and kind=BUILTIN. 

Once that’s in place, you have:

* A compiler that respects the ABI’s event-code layout and hashing.
* A try/catch lowering that respects the spec’s matching semantics, but uses codes internally — as allowed.
* An analysis layer that can report, per function, “these are the actual exception kinds this function can produce.”

---

## 4. After that

Once multi-arm event-based try/catch is in:

* Use `ThrowSummary` + type info to enforce the **can-throw** invariants the spec assumes (exported functions are always error-aware, non-`FnResult` functions don’t construct errors).
* Plan a separate pass to hook in `^` captures and attrs:

  * Ensure that whatever you pass as `payload` into `ConstructError` is enough for the runtime to fill `Error.attrs` and `ctx_frames` as described. 

But the *immediate* thing that ties the current refactor tightly to both documents is: **multi-arm, event-code-driven try/catch lowering** with metadata supplied from the ABI exception catalog.

---

## 5. Runtime diagnostic layer (diagnostic_runtime.c/h)

The existing `diagnostic_runtime.{c,h}` from the original `lang/` implementation is still a good fit for the exception model in `drift-lang-spec.md` and the ABI described in `drift-abi-exceptions.md`. It already provides a compact, well‑typed representation of diagnostic payloads and helpers that line up with how `Error.attrs` and `Error.ctx_frames` are supposed to work.

### 5.1 What diagnostic_runtime provides

At a high level, the runtime exposes:

* A tagged union `DriftDiagnosticValue` with a small set of tags (missing, null, bool, int, float, string, array, object).
* Helper structs:
  * `DriftDiagnosticArray` (pointer + length).
  * `DriftDiagnosticField` (string key + pointer to value).
  * `DriftDiagnosticObject` (array of fields).
* A family of constructors:
  * `drift_dv_missing`, `drift_dv_null`, `drift_dv_bool`, `drift_dv_int`, `drift_dv_float`, `drift_dv_string`.
  * `drift_dv_array`, `drift_dv_object` for aggregating values into arrays/objects.
* Accessors:
  * `drift_dv_get(dv, field)` for object field lookup.
  * `drift_dv_index(dv, idx)` for array indexing.
  * `drift_dv_kind(dv)` and `drift_dv_as_int` / `_as_bool` / `_as_float` / `_as_string` to project back into primitive optionals.
* “To‑diag” helpers:
  * `drift_diag_from_bool/int/float/string` and their optional variants, which are exactly the runtime equivalents of the `Diagnostic.to_diag` helpers in the spec.

This matches the spec’s requirement that exception fields and `^`‑captured locals are converted into a uniform `DiagnosticValue` representation before being attached to an `Error` as `attrs` or `ctx_frames`. The current lang2 pipeline treats the `ConstructError` payload as opaque, which is compatible with using `DriftDiagnosticValue` as that payload.

### 5.2 How this should hook into the lang2 exception backend

To keep the refactor aligned with the existing runtime:

* **SSA/LLVM backend contract**
  * When lowering a `throw` of an exception with fields, SSA should:
    * Materialize each field value as a `DriftDiagnosticValue` via the appropriate `drift_diag_from_*` helper, or by building arrays/objects with `drift_dv_array` / `drift_dv_object`.
    * Package those diagnostics (and any `^`‑captured locals) into the payload that is passed to `ConstructError` in MIR.
  * The eventual C runtime helper that turns a `(event_code, payload)` pair into a full `Error` value should be built on top of `DriftDiagnosticValue` and the helpers in `diagnostic_runtime.c`.

* **No changes required to DiagnosticValue itself**
  * The `DriftDiagnosticValue` layout and API are already minimal and ABI‑friendly (fixed size, explicit alignment checks, plain C structs).
  * Nothing in the new exception design conflicts with this; we should treat `diagnostic_runtime.{c,h}` as the canonical implementation of the spec’s `DiagnosticValue` semantics and reuse it unchanged where possible.

* **Implication for ConstructError**
  * In lang2 MIR, `ConstructError(code, payload)` should be documented as:
    * `code` is the 64‑bit event code computed per `drift-abi-exceptions.md`.
    * `payload` is a runtime‑defined blob that, in the default implementation, is constructed from one or more `DriftDiagnosticValue` instances describing exception fields and context.
  * This keeps the IR generic while ensuring that the existing diagnostic runtime remains a drop‑in implementation of the spec’s `Error.attrs` and `Error.ctx_frames` behavior.

### 5.3 Recommended follow‑ups

To fully leverage the existing diagnostic runtime in the lang2 pipeline:

1. **Specify the payload shape in the spec / ABI notes**
   * Add a short note that for the default runtime, `ConstructError`’s payload corresponds to a `DriftDiagnosticValue` (or a small fixed struct containing multiple `DriftDiagnosticValue` roots for `attrs` and `ctx_frames`).
2. **Plan SSA‑level lowering rules**
   * Define, in the SSA backend design, how each exception field type and each `^`‑capture maps to calls into `diagnostic_runtime` helpers.
3. **Keep diagnostic_runtime as a separate, stable unit**
   * Treat `diagnostic_runtime.{c,h}` as a small, self‑contained library that can be reused across compiler versions and host runtimes, instead of re‑inventing diagnostic handling in lang2.

With those constraints written down, the current lang2 refactor (event codes, try/throw lowering, and throw summaries) stays aligned with both the high‑level language spec and the concrete runtime implementation you already have.

