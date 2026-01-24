# Callbacks, lambdas, and dispatch in Drift

## Purpose

This document explains the proposed design for callbacks and lambdas in Drift, with a focus on:

* Maximizing optimization opportunities (static dispatch, inlining, monomorphization)
* Supporting runtime dispatch where necessary
* Avoiding fragile or heuristic-based language features
* Learning from the long-term consequences seen in other languages (Rust, Java, Go, C#)

The goal is to establish **one clear, intentional model** rather than accumulating ad-hoc rules.

---

## Problem statement

Modern languages need two distinct capabilities when dealing with “callable things”:

1. **Static callbacks**
   Used in algorithms (`map`, `filter`, `sort`, etc.) where:

   * The callable is known at compile time
   * The optimizer should inline and specialize
   * There is no need for runtime polymorphism

2. **Dynamic callbacks**
   Used in event systems, registries, plugin hooks, GUI handlers, etc., where:

   * Callables are stored, mixed, or passed across module boundaries
   * Dispatch must happen at runtime
   * Some overhead is acceptable and expected

Many languages conflate these two cases, which leads to either:

* Lost optimization opportunities (Go, Java-style function values), or
* Overly complex and fragile rules (Java SAM interfaces).

Drift explicitly separates these two worlds.

---

## Design overview

Drift distinguishes **two callable abstractions**:

### 1. Trait-based callables (compile-time)

These represent *capability* and are arity-specific.

```drift
trait Fn1<A, R> {
    fn call(a: A) returns R
}
```

Characteristics:

* Used as **trait bounds** in generic code
* Resolved at compile time
* Fully monomorphized
* Statically dispatched
* Inlinable
* Zero runtime overhead beyond normal calls

Lambdas and named functions are desugared into concrete types that implement `FnN` (and optionally `FnMutN` / `FnOnceN` as those are introduced) depending on capture/mutation.

If we mirror Rust’s split, reserve:

* `FnN` (read-only captures)
* `FnMutN` (mutating captures)
* `FnOnceN` (consuming captures)

This is directly analogous to Rust’s `Fn` traits.

---

### 2. Interface-based callbacks (runtime)

These represent *objects*.

```drift
interface Callback1<A, R> {
    fn call(self: &Self, a: A) returns R
}
```

Characteristics:

* Have a concrete runtime representation (environment pointer + vtable)
* Can be stored in fields, arrays, maps, etc.
* Support heterogeneous collections
* Dispatched dynamically
* May require allocation or boxing

These are the only callable objects intended for runtime polymorphism.

---

## Lambdas in Drift

A lambda expression:

```drift
x => x + 1
```

is not a function pointer and not an interface implementation.

Instead, it desugars to:

* A **fresh, anonymous concrete type**
* With fields for captured variables (if any)
* Implementing the appropriate `FnN` trait

Example (conceptual):

```drift
struct __Closure_42 {
    fn call(x: Int) returns Int { x + 1 }
}

__Closure_42 implements Fn1<Int, Int>
```

Important consequences:

* Lambdas **are real values**
* They can be passed, returned, and stored **as long as their concrete type is known**
* They participate naturally in generic code via `F: FnN<…>`

---

## The single allowed bridge: `FnN → CallbackN` (explicit, owned-only in MVP)

Drift defines **exactly one coercion path** from the static world to the dynamic world:

> Any value of a type `F` that implements `FnN<A… ,R>` (or `FnMutN`/`FnOnceN`) may be wrapped into a `CallbackN<A… ,R>` interface object.
> In MVP this bridge is **explicit** and produces an **owned** callback object.

This coercion (MVP):

* Allocates or boxes as needed
* Produces a runtime object with dynamic dispatch
* Is **explicit** in the type system (no implicit coercion in MVP)
* Captures are **by value only** (borrowed captures are rejected)

Example:

```drift
struct Button {
    on_click: Callback0<Void>
}

button.on_click = () => print("clicked")
```

Here:

```
lambda → concrete closure type → Fn0<Void> → Callback0<Void>
```

This is the **only** place where lambdas become runtime-dispatched objects.

---

## MVP constraints (owned-only callbacks)

To avoid reference-escape and lifetime issues, MVP supports **owned** callbacks only:

* No `callback_ref` or borrowed callback objects in MVP.
* Owned callbacks capture by value only (borrowed captures are rejected).
* If borrowed callback views are desired later, they require a proper lifetime/region story.

---

## Why not Java-style “functional interfaces”?

Java allows lambdas to implement *any* interface with a single abstract method (SAM).

This design is intentionally **rejected** in Drift.

### Problems with SAM-style rules

1. **Structural magic**

   * Whether a lambda is accepted depends on the *shape* of an interface
   * The language must inspect method counts, defaults, inheritance, etc.

2. **Brittle APIs**

   * Adding a second abstract method to an interface silently breaks all lambdas
   * Interface evolution becomes dangerous

3. **Unclear intent**

   * Some single-method interfaces are conceptually callbacks
   * Others are not, but get treated as such accidentally

4. **Specification and tooling complexity**

   * Harder error messages
   * More special cases in type inference
   * More compiler complexity for little semantic gain

Java chose this route for historical reasons. Drift does not need to.

---

## Why restrict lambda-to-interface coercion?

The restriction is not arbitrary. It enforces **clarity of intent** and **compiler simplicity**.

### One explicit boundary

Drift has a clean mental model:

| Concept                | Purpose                          |
| ---------------------- | -------------------------------- |
| `FnN` traits           | Compile-time callable capability |
| `CallbackN` interfaces | Runtime callable objects         |

There is **one** boundary crossing between them.

This makes it obvious:

* Where boxing happens
* Where dynamic dispatch begins
* Where optimization stops

---

### Explicit “this is a callback” signal

If an API designer wants lambdas to be accepted dynamically, they must say so:

```drift
interface OnClick: Callback0<Void> {}
```

This is deliberate. It answers the question:

> “Is this interface meant to be a callback?”

No guessing. No heuristics.

---

### No loss of expressive power

Despite the restriction:

* Generic algorithms remain fully expressive and optimizable
* Runtime systems still support flexible callback registration
* Domain-specific callback interfaces are still easy to define

What is disallowed is only *implicit*, shape-based magic.

---

## Comparison with other languages

### Rust

* Uses `Fn`/`FnMut`/`FnOnce` traits for static dispatch (analogous to Drift’s `FnN`/`FnMutN`/`FnOnceN`)
* Uses `dyn Fn` for runtime dispatch
* Very close to Drift’s proposed model

### Go

* Everything is a runtime function value
* Simpler, but fewer optimization opportunities
* Drift explicitly avoids this tradeoff

### Java / C#

* Lambdas compile to objects or call sites
* Heavy reliance on runtime mechanisms
* SAM rules create long-term fragility

Drift aligns most closely with Rust’s philosophy, adapted to its own type system.

---

## Design principles summarized

1. **Traits express callable capability**
2. **Interfaces express runtime objects**
3. **Lambdas are concrete types, not magic**
4. **There is exactly one static → dynamic bridge**
5. **No structural or heuristic-based rules**
6. **Optimization boundaries are explicit**

---

## Implementation guidance

For compiler and tooling work (MVP-tightened):

* Treat `FnN` traits like any other trait: monomorphized, inlinable
* Represent all interface values as `(data_ptr, vtable_ptr)` (including `CallbackN`)
* Vtable includes `call`, `drop`, `size`, `align` for owned callback objects
* Implement a single, explicit coercion path `FnN → CallbackN`
* Reject lambda → arbitrary interface conversions early with clear diagnostics
* Reject borrowed captures when erasing into owned `CallbackN`

---

## Conclusion

This design intentionally prioritizes:

* Long-term maintainability
* Predictable performance
* Clear mental models
* Minimal special cases

By resisting the temptation to add Java-style convenience magic, Drift keeps its core clean while still offering all the ergonomics needed for real-world use.

If we later want more syntax sugar, it can be layered **on top of this model**, not baked into the type system itself.
