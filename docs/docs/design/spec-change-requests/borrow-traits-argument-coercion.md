# Borrow/BorrowMut Traits for Argument Coercion (Spec Change Request)

## Summary

Introduce two standard traits, `Borrow<T>` and `BorrowMut<T>`, to allow **argument-only** coercions to `&T` / `&mut T` without enabling method‑receiver auto‑deref. This provides ergonomic wrapper usage (e.g., `Arc<Mutex<T>>`) while avoiding implicit method lookup rules.

---

## Motivation

Common patterns (e.g., `Arc<Mutex<T>>`) require verbose accessors today:

```drift
var g = conc.lock(e.state.get_mut());
```

We want to allow:

```drift
var g = conc.lock(e.state);
```

without enabling full auto‑deref on method receivers. Argument coercion via explicit traits is a smaller, safer step.

---

## Proposed Traits

In `std.core` (or `std.core.borrow`):

```drift
pub trait Borrow<T> {
	fn borrow(self: &Self) -> &T;
}

pub trait BorrowMut<T> {
	fn borrow_mut(self: &mut Self) -> &mut T;
}
```

---

## Coercion Rules (Argument‑Only)

When a function expects a **reference** parameter:

### 1) Immutable borrow

If a parameter expects `&T` and the argument expression has type `X` (or `&X`), and `X: Borrow<T>`, the compiler may insert:

```
Borrow::borrow(&arg)
```

### 2) Mutable borrow

If a parameter expects `&mut T` and the argument expression has type `&mut X`, and `X: BorrowMut<T>`, the compiler may insert:

```
BorrowMut::borrow_mut(arg)
```

Notes:

- **No by‑value coercion** (`T` by value is not synthesized).
- **No method‑receiver auto‑deref** (receiver lookup stays explicit).
- Standard borrow rules still apply (requires `&mut` for `BorrowMut`).

---

## Example (Arc + Mutex)

Implementations:

```drift
implement<T> Borrow<Mutex<T>> for Arc<Mutex<T>> {
	fn borrow(self: &Arc<Mutex<T>>) -> &Mutex<T> { ... }
}

implement<T> BorrowMut<Mutex<T>> for Arc<Mutex<T>> {
	fn borrow_mut(self: &mut Arc<Mutex<T>>) -> &mut Mutex<T> { ... }
}
```

Usage:

```drift
var g = conc.lock(e.state);
```

`lock` expects `&mut Mutex<T>`, the argument is `&mut Arc<Mutex<T>>`, so the compiler inserts `borrow_mut()`.

---

## Interaction With Future `Deref`

This change **does not** define method‑receiver auto‑deref. If a future `Deref`/`DerefMut` feature is added, it can reuse these traits or coexist with them.

---

## Compiler Notes

- Apply only during **argument coercion** (same place as existing auto‑borrow).
- Keep diagnostics clear: if Borrow/BorrowMut is missing, suggest implementing it.
- Avoid chaining beyond one step (no recursive borrow‑through‑borrow) to keep the rule predictable.

---

## Tests

Positive:

- `BorrowMut` allows `Arc<Mutex<T>>` to pass into `lock(&mut Mutex<T>)`.
- `Borrow` allows `Arc<T>` to pass into `read(&T)`.

Negative:

- No coercion when function expects `T` by value.
- No coercion for method receiver calls.
- No coercion when only `&X` is available for `BorrowMut`.

---

## Status

- Requested: 2026-01-24
- Priority: Post-MVP (optional)
- Owner: TBD
