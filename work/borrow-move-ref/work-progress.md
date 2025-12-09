## 1. Target semantics (what “full-grade” means for Drift)

From the spec:

* `x->` is the only way to move; values are move-only by default, `Copy` is opt-in.
* `&v` / `&mut v` borrow **lvalues only**; borrowing temporaries/rvalues is illegal.
* Call-site auto-borrow:

  * If parameter is `&T`, passing an lvalue `v: T` behaves as `&v`.
  * If parameter is `&mut T`, passing an lvalue `v: T` behaves as `&mut v`.
* Methods/receivers:

  * `self: T` (by value) vs `self: &T` vs `self: &mut T`.
  * Call on an lvalue prefers borrowed receivers (`&self`, `&mut self`) before value (`self`); call on rvalue only binds to `self: T`.
* Pipelines and mutators/transformers/finalizers piggyback on the same ownership modes.
* Slices / `ref_at` / `ref_mut_at` and friends are just APIs over the same borrow semantics.

A “full” borrow checker therefore has to:

1. Track **moves vs validity** of every place (local, field, array element, slice).
2. Track **loans** (shared `&` vs exclusive `&mut`) for each place and region.
3. Enforce:

   * No move from a place while it has an active loan.
   * No new `&mut` while any `&` or `&mut` on the same place (or overlapping place) is active.
   * No new `&` while an `&mut` is active.
   * No borrow from rvalues or moved values (including auto-borrows).
4. Handle **escaping refs**: parameters, return types, fields, variants, slices, interface/trait methods.
5. Respect **lexical scopes** and non-lexical lifetimes (NLL-style): reference lifetimes are bounded by *last use*, not just textual scope.

That’s exactly the Rust problem domain, but with a simpler surface: no raw pointers, no lifetime syntax, clear “moves by default”.

---

## Status / progress

- [x] Spec review: drift-lang-spec.md is the canonical source for move/borrow semantics.
- [x] Implementation Phase 1 (places + move tracking).
  - Place representation finalized (PlaceBase + projections) with hashable IndexKind/IndexProj.
  - BorrowChecker runs as CFG-based forward dataflow; tracks UNINIT/VALID/MOVED; emits use-after-move diagnostics.
  - Expression visitor walks all HIR forms; Copy=scalar, everything else move-only; diagnostics reset per run.
  - Tests: move tracking (straight-line), branch/loop CFG cases, place builder coverage.
- [ ] Implementation Phase 2 (basic loans + lvalue-only borrows, no regions).
  - Coarse loans implemented: HBorrow (&/&mut) nodes lower to borrow checker; shared-vs-mut conflicts enforced with whole-place overlap; borrow-from-rvalue/moved rejected.
  - Temporary borrows in expr/cond are dropped after use (coarse NLL); assignments drop overlapping loans; moves are blocked while borrowed.
  - Optional `enable_auto_borrow` flag (shared only) scaffolded with call-scoped temporary loans; still need signature-driven auto-borrow.
  - TODO: real regions (kill after last use), auto-borrow at call sites/receivers with mut/shared selection, overlap precision (field/slice), diagnostics with spans.
- [ ] Implementation Phase 3 (regions/NLL + auto-borrow integration).
- [ ] Implementation Phase 4 (escapes/struct fields/returns with refs).

---

## Next steps (near-term)

1. Introduce regions/NLL:
   * Add RegionId to loans with per-ref live ranges; kill loans after last use instead of union-of-function.
   * Refine overlap precision if needed (field/slice).
2. Auto-borrow at call sites/receivers (using signatures to pick shared vs mut); reuse borrow rules; reject rvalues/moved.
3. Wire borrow checker into pipeline behind a flag; add CLI/runner coverage and spans in diagnostics.
4. Consider CFG cleanup for loop terminators if it simplifies region flow.

---

---

## 2. Architectural decision: where the borrow checker lives

You want a **dedicated BorrowChecker pass** that runs after:

* HIR is built and fully typed (all `TypeId`s resolved).
* You have a CFG / SSA form available (or at least a block graph with basic SSA).

Design:

* Run on a **per-function** basis.
* Input: typed HIR or SSA (whichever you consider “stage4”), plus symbol table / type table.
* Output:

  * Diagnostics (borrow errors, move-after-move, use-after-move).
  * No panics or assertion failures; everything is a proper diagnostic with spans.

That keeps borrow logic contained and makes it a very strong refactor regression test: if the checker pass can see types, CFG, and ownership states clearly, the pipeline decomposition is probably sane.

---

## 3. Core data structures

### 3.1. Places

You need a normalized representation of “where a value lives”:

* `PlaceId` representing:

  * Local var: `x`
  * Projection: `x.field`, `x[i]`, `*p`, etc.
* For aliasing, treat a `Place` as `(base_local, projection_path)` so you can ask:

  * “Does this new loan overlap that existing loan?” (field granularity vs whole-object is a design choice; I’d start with **whole-object** except for clear slice APIs.)

### 3.2. Lifetimes / regions

You won’t expose lifetimes in syntax, but internally you need **region ids**:

* `RegionId` per:

  * Each reference-typed local.
  * Each ref-typed parameter.
  * Each ref-typed field in a local aggregate.
* For each `RegionId`, you track a **set of CFG points** where it is alive (NLL style).

### 3.3. Loans

A loan is:

```text
Loan {
    id: LoanId,
    kind: Shared | Mutable,
    place: PlaceId,      // what is being borrowed
    region: RegionId,    // how long this loan must be valid
}
```

At each program point, you maintain:

* `place_state[place] = Valid | Moved | Uninitialized`
* Active `loans: Set<Loan>` filtered by “region still alive here”.

Loans are created at:

* `&v` / `&mut v`.
* Auto-borrows at call sites and method calls (inferred form of `&v`/`&mut v`).
* APIs like `ref_at`, `ref_mut_at`, slices, etc.

Loans are killed when:

* The borrow’s region ends (no more uses of that ref).

---

## 4. Algorithm sketch (per function)

### Step 0 – prerequisites

Before the borrow checker runs, ensure:

* Every expression is typed (`TypeId`s everywhere).
* Move vs Copy classification exists per type (`is_copy(T)`).
* CFG is built and liveness of locals is either already available or cheaply computable.

### Step 1 – classify expressions: rvalue vs lvalue

You need an **lvalue/rvalue classifier** on HIR:

* Lvalues:

  * Locals, parameters.
  * Field access `x.f` where `x` is lvalue.
  * Indexing `arr[i]` where `arr` is lvalue.
  * Deref of ref/ptr where that is supported.
* Rvalues:

  * Literals, function calls, array literals, `x + y`, temporaries.

Spec rule: `&v`/`&mut v` only accept lvalues. Auto-borrow uses this same classification.

Any attempt to borrow an rvalue yields a **borrow-from-temporary** diagnostic.

### Step 2 – build region graph

For each **reference-typed** local/parameter/field:

* Compute its **lifetime region** using NLL-style analysis:

  * Start from the `let`/param entry.
  * Collect all uses of that reference.
  * Region is *the union of CFG spans from definition to last use*.

This gives you the `RegionId -> {CFG points}` mapping.

For parameters/returns, you introduce **abstract regions**:

* For `fn f(x: &T) returns &T`, treat `x`’s region as `'a`, return region as `'b`.
* Add constraints `'b <= 'a` (return ref may not outlive param ref).
* For now you can avoid full Rust-style generic region inference by:

  * Treating each ref-typed parameter as an abstract “input region”.
  * For each returned ref, check that it’s ultimately derived from some input region or a global; if it’s derived from a **local non-ref**, error “returning reference to local”.

That’s enough to enforce “no return &local” and “no store &local in longer-lived struct” in v1.

### Step 3 – compute use-sites of reference values

For each reference value (`&T` / `&mut T`):

* Collect all its uses:

  * Direct use (field access, deref, passing to function, etc.).
* Associate use points with its `RegionId`.

This is what lets you know when a loan can be dropped: after the last use of the ref, the underlying loan constraints can be lifted.

### Step 4 – borrow checking dataflow

Perform a forward dataflow over the CFG:

State at each program point:

* `place_state[place]` (Valid / Moved / Uninit).
* `active_loans: Set<Loan>` where `loan.region` contains this point.

At each statement/expression:

1. **Moves and copies**

   * For `x->`:

     * Require `place_state[x] == Valid`.
     * Require no active loan whose `place` overlaps `x`.
     * Set `place_state[x] = Moved`.
   * For by-value use of `x` where `!is_copy(type(x))`:

     * Treat as implicit move.
   * For `copy x` or arguments of `Copy` type:

     * Just duplicate, no state change.

2. **Borrow expressions (`&v` / `&mut v`)**

   * Require `v` is lvalue, `place_state[v] == Valid`.
   * Before creating new loan:

     * For `&v`:

       * Disallow any active `Mutable` loan whose `place` overlaps `v`.
     * For `&mut v`:

       * Disallow any active loan (`Shared` or `Mutable`) whose place overlaps `v`.
   * Create `Loan {kind, place=v, region=<region-of-this-ref>}`.
   * Add to `active_loans`.

3. **Auto-borrow at call sites**

   * For each argument `arg` passed to param type:

     * If param type is `&T`/`&mut T` and `arg` type is `T`, and `arg` is lvalue:

       * Synthesize an internal borrow op (`&arg` or `&mut arg`) and process as above.
       * Enforce “no borrow from rvalue/moved value” here too.
   * For receiver calls (`obj.method()`):

     * Use method resolution rules:

       * On lvalues, prefer `&T` receiver, then `&mut T`, then `T`.
       * On rvalues, only `T`.
     * When a borrowed receiver is picked, same as auto-borrow.

4. **Killing loans**

   * At each program point, remove any loan whose `region` no longer includes this point.
   * Removing the loan re-allows moves / other borrows on that place.

5. **Assignments and reinitialization**

   * Assigning to `x` sets `place_state[x] = Valid` and kills any loans whose `place` is `x` or a subplace of `x`.
   * This models overwriting storage and invalidating previous borrows.

6. **Aggregates with refs (structs/variants/arrays)**

   * For a ref-typed field `s.f: &T`:

     * Its region is that of the ref stored in it.
     * When you assign `s.f = &x`, you’re effectively:

       * Creating a loan for `x` whose region is the lifetime of `s` (or of `s.f`’s actual use, if you do NLL for fields).
     * Borrow checker must ensure: region of `&x` used for this assignment does not outlive `x`’s own lifetime.
   * Implementation trick: treat each field with a ref type as its own “binding” `s.f` in the region solver.

---

## 5. Handling escapes and API boundaries

### 5.1. Returns

For any function that returns a reference:

* Track, for each `return` site, which **place** the reference originates from (parameter, global, local, structure field, etc.).
* Enforce:

  * If the place is:

    * A **local** created in this function: error (“returning reference to local”).
    * A **field of a local**: same as above unless the local itself is returned/moved out (then the reference is owned by caller via the returned aggregate).
    * A **parameter** or a **global/static**: OK, as long as type-level constraints (`'out <= 'in`) hold.

You don’t need explicit `'a` syntax; you just track origin and its lifetime.

### 5.2. Structs and variants with `&T` fields

When typing a struct:

* Conceptually attach **implicit region parameters** for each ref-typed field.
* Borrow checker rule:

  * A struct `S` with a field `f: &T` can be constructed only if the referenced value outlives `S`’s region of use.
  * In practice:

    * When assigning to `s.f` in a local, you check that the region of `&x` is at least as long as `s`’s living region.
    * When passing `S` by value to a function, you propagate those region constraints into callee.

You can start with a simpler model and still be “full-grade” for 99% use cases: treat `S`’s lifetime as “lifetime of the binding” and ensure refs assigned into it don’t outlive that. That already supports ASTs like `Expr::Add(lhs: &Expr, rhs: &Expr)` in the spec.

### 5.3. Traits/interfaces and references

* Trait methods with `self: &T` / `&mut T` are just another form of borrowed receiver.
* Interface methods use fat pointers but their Drift surface still uses `&T` / `&mut T` in signatures; borrow checker works the same.
* `Send`/`Sync`:

  * Checker must ensure:

    * Values moved to another thread implement `Send`.
    * Shared refs crossing threads (`&T`) require `T: Sync`.
  * That’s orthogonal to borrow checking, but they share region/state tracking.

---

## 6. Interactions with closures and “not yet supported” captures

Spec explicitly says `&x`/`&mut x` captures in closures are “not yet supported” until borrow checker exists.

You can leverage that:

* **Now**: keep closure captures `move x` / `copy x` only. All captures are by value; the borrow checker sees nothing special.
* When you later add `&x`/`&mut x` captures:

  * They’re just loans whose region is “closure environment lifetime”.
  * Your existing region/loan machinery will handle that; you just add a new source of loans.

So you still build the **real** borrow checker now, and closures naturally slot into it later.

---

## 7. Concrete implementation phases (all toward full semantics)

This is “how to eat the elephant” without compromising the model:

### Phase 1 – Moves and place tracking

* Implement `Place` representation and `place_state` (Valid/Moved/Uninit).
* Enforce:

  * Use-after-move.
  * Move from `val` disallowed.
  * Implicit moves for non-`Copy` values.
* Start at typed HIR (pre-SSA) to keep the first pass simple; SSA integration can come later.
* Initial scaffolding: `lang2.borrow_checker.Place` + lvalue detection helpers (`place_from_expr`, `is_lvalue`) to identify borrowable/moveable places across HVar/field/index expressions.

### Phase 2 – Basic loans + no temporaries

* Add `&v` / `&mut v` and lvalue/rvalue classifier.
* Implement loans, but only for locals/fields (no full region solver yet).
* Enforce:

  * No borrowing from temporaries/moved values.
  * Shared vs unique borrow conflict rules.

### Phase 3 – Region inference and NLL

* Introduce `RegionId`s and compute usage spans of each ref.
* Wire loans to regions and kill them after last use.
* Integrate auto-borrow at call sites and method receiver resolution.

### Phase 4 – Escapes (returns, fields, variants)

* Implement origin tracking for returned refs.
* Forbid returning refs to locals / too-short fields.
* Extend region checks to structs/variants with `&T` fields.

At the end of Phase 4 you effectively have “Rust-grade” intra-module borrow checking for Drift’s model.

After that, you’re in polishing territory:

* Borrow patterns in pattern matching (when added).
* Borrow-aware diagnostics (good error messages).
* Optional optimizations (e.g., partial-field loans instead of whole-object).

---
