# error/diagnostics & exceptions – work progress

## 0. Decisions (locked)

This document supersedes any earlier error/exception work-plan and aligns all specs and implementation with the *diagnostic-only, string-normalized* Error model in the current language spec. :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1}  

**We have agreed to:**

- Keep **one concrete `Error` type** with:

  - `event: String`
  - `args: Map<String, String>`
  - `ctx_frames: Array<CtxFrame>`
  - `stack: BacktraceHandle` :contentReference[oaicite:2]{index=2}  

- Treat exceptions as **events with diagnostic attributes**, not UI messages or domain error types.
- Normalize **all exception arguments and `^` captured locals** into **strings** stored in `args` / `ctx_frames`, using a dedicated **`Diagnostic` trait**, not `Display` or `Debuggable`.
- Keep **functional exception construction**:

  ```drift
  exception DbError(conn: DbConnection, sql_state: SqlStateCode)

  throw DbError(conn = db_conn, sql_state = db_conn.last_state())
````

* **Do not** expose exception attributes as fields; they are transformed into diagnostics and accessed via the error API.

* Introduce a **`Diagnostic` trait + `DiagnosticCtx`/writer** as the *only* way types end up in exception args / captured locals.

* Drop `Debuggable` in favor of `Diagnostic` as the “format for diagnostics” powerhouse; `Display` is reserved for user-facing text.

* Attribute access:

  * In a **typed catch**:

    ```drift
    catch (e: DbError) {
        val code: String = e[sql_state]   // schema-checked; always present
    }
    ```

  * For **generic `Error`**: no `[]`. Use:

    ```drift
    val maybe_code: Option<String> = e.attr("sql_state")
    ```

* Keep the 64-bit **event code ABI layout** (`kind` + 60-bit payload) as in `drift-abi-exceptions.md`; `Error.code` is `Int64` / `uint64_t` everywhere. 

Everything below is implementation and spec-edit work to realize those decisions.

---

## 1. Spec changes

### 1.1 `drift-lang-spec.md` – traits: replace `Debuggable` with `Diagnostic`

**Goal:** Replace the existing `Debuggable` string-returning trait with a richer `Diagnostic` trait that drives structured diagnostics. 

**Tasks:**

* [ ] In Chapter 5 (traits) where `Debuggable` is defined and used: 

  * Replace the `Debuggable` trait definition with:

    ```drift
    trait Diagnostic {
        fn write_diagnostic(self, ctx: &mut DiagnosticCtx)
    }
    ```

    and define `DiagnosticCtx` conceptually as:

    ```drift
    trait DiagnosticCtx {
        fn emit_current(self, value: String)          // use current key
        fn field(self, name: String, value: String)   // extra fields
        fn field_fmt(self, name: String, value: impl Display)
        fn nested(self, prefix: String, f: fn(&mut DiagnosticCtx))
    }
    ```

    (Exact API naming and placement may live in `lang.core.diagnostic` or similar.)

  * Remove `Debuggable` from all trait lists and examples, or rename example usages to `Diagnostic` where they are clearly about diagnostics rather than UI text.

  * Keep `Display` as a separate trait for user-facing text; clarify that `Display::to_string` is *not* what exceptions use.

* [ ] Introduce a blanket implementation in the spec narrative:

  > For small/simple types, the standard library provides:
  >
  > ```drift
  > implement<T>
  >     Diagnostic for T
  >     require T is Display
  > {
  >     fn write_diagnostic(self, ctx: &mut DiagnosticCtx) {
  >         ctx.emit_current(self.to_string())
  >     }
  > }
  > ```
  >
  > This allows any `Display` type to be used in exceptions / `^` captures by default; large or special types should implement `Diagnostic` explicitly.

* [ ] Clarify in the traits rationale section that:

  * `Diagnostic` is the canonical diagnostic formatting trait.
  * `Display` is for user-visible strings.
  * Exception and context capture are powered by `Diagnostic`, not `Display`. 

---

### 1.2 `drift-lang-spec.md` – Chapter 14 exceptions & error context

**Goal:** Align §14 with the new Diagnostic-based attribute model and the `DbError(conn = x, ...)` functional syntax. 

**Tasks:**

* [ ] §14.2 Error layout:

  * Keep the conceptual `Error` struct exactly as:

    ```drift
    struct Error {
        event: String,
        args: Map<String, String>,
        ctx_frames: Array<CtxFrame>,
        stack: BacktraceHandle
    }
    ```

    but explicitly state that:

    > `args` and `ctx_frames.locals` are built via the `Diagnostic` trait: exception arguments and captured locals are passed through `Diagnostic::write_diagnostic` and flattened into `(key, value)` string pairs.

* [ ] §14.3 exception events: 

  * Keep the **functional throw syntax**:

    ```drift
    exception InvalidOrder(order_id: Int64, code: String)

    throw InvalidOrder(order_id = order.id, code = "order.invalid")
    ```

  * Change the requirement from “each parameter type must implement `Display`” to “must implement `Diagnostic`”.

  * Specify:

    * At throw:

      * For each parameter `field: T` with value `expr`, the compiler:

        * evaluates `expr`,
        * invokes `Diagnostic::write_diagnostic` with the current key set to `"field"`,
        * merges the resulting fields into `Error.args`.
    * Parameter defaults (compile-time resolvable) are allowed and are applied for any omitted fields at the throw-site, so every declared field is always present in the diagnostic record.

* [ ] §14.4 captured locals (`^`): 

  * Replace “must implement Display” with “must implement Diagnostic”.
  * Clarify:

    * The label in `val ^x: T as "label" = expr` becomes the **current key** when capturing; if `as` is omitted, the binding name is used as key.
    * Capturing uses `Diagnostic::write_diagnostic` and writes into `ctx_frames[frame].locals`.

* [ ] §14.5/14.8 try/catch and logging: 

  * Ensure the examples and prose describe `Error` as:

    * **event** name,
    * attribute map stringified via `Diagnostic`,
    * `ctx_frames` built from `^` locals via `Diagnostic`,
    * stack handle.

  * Add a short “typed vs generic access” subsection:

    * In typed catch arms (`catch InvalidOrder(err)` or `catch (err: InvalidOrder)`):

      ```drift
      catch (e: InvalidOrder) {
          val order_id: String = e[order_id]
          val code: String     = e[code]
      }
      ```

      * The identifier inside `[]` must match a declared field name; otherwise it is a compile-time error.
      * The result is a `String` and is guaranteed present (defaults fill any omission).

    * In generic handlers:

      ```drift
      catch (e: Error) {
          val maybe_code: Option<String> = e.attr("code")
      }
      ```

      * `Error` does **not** expose `[]`; only `attr(key: String) -> Option<String>` is available.
      * `attr` performs a dynamic lookup in `Error.args` and returns `None` if the key is absent.

---

### 1.3 `drift-lang-grammar.md` – syntax clarification (no major change)

**Goal:** Ensure the grammar remains in sync with the “functional throw + attribute index” design. 

**Tasks:**

* [ ] Confirm and, if needed, annotate in the grammar commentary that:

  * `ExceptionDef` already uses `(Fields?)` and matches `exception Name(param: Type, ...)`. 
  * Function/constructor calls with named arguments are parsed as `PostfixExpr "(" Args? ")"` with `Args ::= Expr ("," Expr)*`; name binding is handled at the semantic layer (typechecker), not the grammar.
  * Indexing is `PostfixTail ::= "[" Expr "]"`, and `Expr` covers both identifiers and string literals.

    * The **semantic** rule is:

      * When the base expression has an exception type, a bare identifier in `e[ident]` is resolved as an attribute name.
      * For all other cases (maps, arrays, strings), `[]` behaves as normal index/subscript access based on the type of the base.

* [ ] No structural grammar changes are required; just ensure doc comments mention the special semantics for `e[ident]` when `e` has an exception type.

---

### 1.4 `drift-abi-exceptions.md` – event code width & consistency

**Goal:** Reconfirm 64-bit `event_code` everywhere and align nomenclature with `Int64` in the spec/DMIR. 

**Tasks:**

* [ ] Ensure `drift-abi-exceptions.md` explicitly states that the event code is a 64-bit integer, and cross-reference `Error.code: Int64` from the main spec.
* [ ] In `drift-lang-spec.md`, update any remaining mentions of `error_event(err) returns Int` or "word-sized" to explicitly `Int64` for event codes. 
* [ ] Confirm that all compiler/runtime helpers use `uint64_t` / `Int64` for event codes, including:

  * `drift_event_kind`,
  * `drift_event_payload`,
  * `drift_event_code`, and the builtin event constants. 

---

### 1.5 `dmir-spec.md` – Error projections & exceptions metadata

**Goal:** Align DMIR with the string-normalized `Error` model and the exception schema we now rely on. 

**Tasks:**

* [ ] In the “Errors & exceptions” and “Error ABI” sections: 

  * Clarify that DMIR treats `Error` as **opaque** but exposes projection intrinsics equivalent to:

    ```text
    error_event_code(err: Error) -> Int64
    error_event_name(err: Error) -> String
    error_args(err: Error) -> Map<String, String>
    error_ctx_frames(err: Error) -> Array<CtxFrame>
    error_stack(err: Error) -> BacktraceHandle
    ```

  * Replace any residual description that implies “first payload string only” or a richer C-ABI struct as the *canonical* representation. The C struct in DMIR docs should be re-labeled as a *possible* runtime layout, not part of DMIR’s semantic surface, or slimmed to match the `Map<String, String>` view.

* [ ] Add explicit DMIR metadata for exceptions:

  * For each exception:

    * FQN
    * `event_code: Int64`
    * `field_names: Array<String>` in declaration order
    * (optional) original field types for tooling only

  * State that these metadata drive:

    * event-code dispatch in try/catch,
    * schema-checked attribute access in typed catch arms (`e[field]`),
    * linker checks against collisions (same FQN/event_code but different field_names).

---

## 2. Compiler changes

### 2.1 Checker – exception schema & Diagnostic requirements

**Tasks:**

* [ ] Exception declarations:

  * Record, per exception:

    * the ordered list of fields `(name, type, has_default, default_expr)`.

  * Enforce that each field type implements `Diagnostic` (using the trait system).

  * Ensure defaults are **compile-time evaluable**; reject defaults that depend on runtime data or locals.

* [ ] Throw-site checking:

  * For `throw ExcName(f1 = e1, f2 = e2, ...)`:

    * Resolve `ExcName` to an exception type; fetch its schema.
    * Ensure each provided field name exists in the schema; error on typos/unknown names.
    * Type-check `ei` against the declared type of `fi`.
    * Enforce that:

      * all fields without defaults are provided,
      * fields with defaults may be omitted.

  * Canonicalize argument order to the schema order for lowering.

* [ ] Captured locals:

  * Track `^` bindings in each function (with optional `as "label"` alias).
  * Enforce that each `^` variable’s type implements `Diagnostic`.
  * Record (fn_name, labels, types) so unwind-time capture knows what to collect per frame.

---

### 2.2 HIR → DMIR lowering – exception construction

**Tasks:**

* [ ] Lower `throw ExcName(field = expr, ...)` to a DMIR sequence that:

  * Evaluates each `expr` to a value `v_i`.
  * For each `(field_i, v_i)`:

    * Invokes `Diagnostic::write_diagnostic(v_i, ctx)` with a `DiagnosticCtx` whose current key is `"field_i"`.
    * The implementation of `DiagnosticCtx` for exceptions accumulates `(String key, String value)` entries; complex types may add additional derived keys via `field`/`nested`.
  * Emits a DMIR intrinsic or call to a runtime helper such as:

    ```dmir
    let e = error_new_event(
        event_code = <Int64>,
        event_name = "<ExcName FQN>",
        args       = <Array<(String, String)>>
    )
    raise e
    ```

* [ ] For builtin exceptions and dummy/test errors:

  * Keep using the event-code layout from `drift-abi-exceptions.md`. 
  * Adjust the dummy helper to build a full args map (e.g., single `("payload", payload_string)` or just empty) instead of the old “first string only” behavior.

---

### 2.3 Try/catch lowering – event-code dispatch

**Tasks:**

* [ ] Ensure both statement and expression forms of `try/catch` lower to:

  * A call or block that can raise.
  * A dispatch on `error_event_code(err)` (Int64) to select the correct catch arm in source order.
  * A catch-all arm if present; otherwise rethrow.

* [ ] Confirm the SSA builder uses `I64` for event codes and that `_ssa_read_error_event` returns `I64`, consistent with the ABI.  

---

### 2.4 Attribute access – typed vs generic

**Tasks:**

* [ ] Typed access (`e[sql_code]`):

  * When the static type of `e` is a concrete exception type `ExcName`:

    * Resolve the bare identifier inside `[]` as an attribute name in `ExcName`’s schema.
    * If not found → compile-time error.
    * Lower `e[sql_code]` to a projection from `Error.args` via the known string key `"sql_code"`; type is `String`.

* [ ] Generic access (`e.attr("sql_code")`):

  * Add an intrinsic or method on `Error`:

    ```drift
    fn attr(self: &Error, key: String) returns Option<String>
    ```

  * Lower calls to a runtime helper that performs a map lookup in `args`, returning `Some(value)` or `None`.

* [ ] Ensure `[]` is **not** available on the `Error` type in the type system; it only appears on exception types (Drift surface), even though the underlying representation is the same `Error`.

---

### 2.5 Captured locals & unwind

**Tasks:**

* [ ] At each unwind boundary (when a function frame is being exited due to an error):

  * For each `^`-annotated local in that frame:

    * Determine its capture label (explicit `as "label"` or the variable name).
    * Invoke `Diagnostic::write_diagnostic` with `DiagnosticCtx` keyed to that label.
    * Accumulate produced `(key, value)` pairs into a new `CtxFrame.locals` map for this frame.

  * Collect the `fn_name` for the frame and push a new `CtxFrame` into `Error.ctx_frames` in order from innermost to outermost.

* [ ] Ensure this capture happens **once per frame per error**, not at every throw in the same frame.

---

## 3. Runtime / ABI changes

**Goal:** Make the runtime match the DMIR/spec model: `Error` as event + args (string map) + ctx_frames + stack, plus 64-bit event codes.  

**Tasks:**

* [ ] Define/confirm the C-level representation of `Error` used by codegen:

  * It may still be a richer `DriftError` struct as documented in DMIR, but its *observable behavior* via projections must match:

    * `drift_error_event_code(Error*) -> uint64_t`
    * `drift_error_event_name(Error*) -> DriftString`
    * `drift_error_args(Error*, /*out*/ DriftNamedString**, /*out*/ size_t*)`
    * `drift_error_ctx_frames(Error*, ...)`
    * `drift_error_stack(Error*) -> DriftBacktraceHandle`

* [ ] Implement a runtime helper for constructing `Error` from event + args, e.g.:

  ```c
  typedef struct {
      DriftString key;
      DriftString value;
  } DriftNamedString;

  Error* drift_error_new_event_args(uint64_t event_code,
                                    DriftString event_name,
                                    const DriftNamedString* attrs,
                                    size_t attr_count);
  ```

* [ ] Implement a `DiagnosticCtx` in the runtime/lower-level library that:

  * Accumulates `DriftNamedString` entries into a temporary buffer for exception args or ctx_frames.
  * Supports `emit_current`, `field`, `field_fmt`, and `nested` semantics.

* [ ] Ensure `Error` is move-only at the language level; runtime exposes a single `drift_error_free(Error*)` that uses the internal layout/metadata to free attributes, frames, and stack.

---

## 4. DMIR changes

**Tasks:**

* [ ] Extend DMIR’s exception representation to include:

  * `event_code: Int64`
  * ordered `field_names: Array<String>`
  * (optional) `field_types: Array<TypeRef>` for tools.

* [ ] Add explicit DMIR nodes/intrinsics for:

  * `error_event_code` (already hinted in DMIR spec).
  * `error_event_name`.
  * Optionally, a generic `error_to_diagnostic(err: Error) -> ErrorDiagnostic` if DMIR needs a single operation to expose the canonical diagnostic record.

* [ ] Update the DMIR “Errors & exceptions” section to state that:

  * Exception args and captured locals are normalized via `Diagnostic` to strings and stored in maps, not arbitrary typed payloads. 

---

## 5. Tests

**Tasks:**

* [ ] Unit/runtime tests:

  * Throw exceptions with:

    * simple primitive args,
    * args with defaults,
    * complex `Diagnostic` types (e.g., a mock `DbConnection`).
  * Verify:

    * `event_code` matches the exception.
    * `Error.args` contains the expected key/value strings.
    * `ctx_frames` contain captured locals as expected.
    * `attr("key")` returns `Some`/`None` correctly.

* [ ] Checker tests:

  * Exception fields with types lacking `Diagnostic` → compile error.
  * `^` locals with types lacking `Diagnostic` → compile error.
  * Throws that omit required fields (no default) → compile error.
  * Throws with unknown field names → compile error.

* [ ] SSA/DMIR tests:

  * Hand-constructed DMIR/SSA for `throw DbError(...)` and `try/catch DbError` to ensure:

    * `error_event_code` drives dispatch.
    * `e[field]` lowers to a string lookup using the schema.
    * `e.attr("field")` lowers to the dynamic attribute lookup helper.

* [ ] E2E tests:

  * Multi-field exceptions (`DbError`, `InvalidOrder`, etc.) with both local and cross-module throws/catches.
  * Logging helpers that produce JSON matching the spec’s example structure. 

---

## 6. Cleanup & migration

**Tasks:**

* [ ] Remove or rewrite all references to `Debuggable` in specs and code; where they were clearly about error diagnostics, replace them with `Diagnostic`.

* [ ] Remove any code/docs that still assume “single String payload” in Error.

* [ ] Make sure:

  * `drift-lang-spec.md`
  * `drift-abi-exceptions.md`
  * `drift-lang-grammar.md`
  * `dmir-spec.md`

  all consistently describe:

  * `Error.code` as `Int64` event code with the 4+60 layout, 
  * exceptions as events + args + ctx_frames + stack,
  * args/ctx_frames as string maps built from `Diagnostic`,
  * typed attribute access via `e[field]` only on exception types, and
  * generic attribute access via `Error.attr(key: String) -> Option<String>`.

* [ ] Update `work-progress.md` (this file) in the repo to be the single source of truth for this feature’s implementation tasks, and drop/merge any older error-progress docs that conflict. 
