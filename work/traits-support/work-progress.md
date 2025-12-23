# Traits support — work plan

Goal: implement static, compile-time traits per spec (no trait objects, no runtime polymorphism).

## Status (current)
- Phase 2/3 registry + solver scaffolding wired; tests cover world + solver.
- Phase 4: struct/function `require` enforcement wired (HIR-used types + per-instantiation).
- Phase 4: trait guards resolved at typecheck for concrete subjects.
- Phase 4: require-based filtering wired into free-function resolution (overload
  ranking logic present; require-only overloads are rejected, true overloads are
  supported but still expanding coverage across workspace/module cases).
- Overload sets refactor in progress: FunctionId plumbed through parser + signatures,
  CLI/typechecker use FunctionId keys and registry entries, tests updated to resolve
  via `fn_ids_by_name`.
- Entry symbol resolution fixed for workspace/e2e runs (qualified `::main` handled).
- Stub pipeline preserves shared `TypeTable` (const table survives signature resolution).
- Full `just` suite passes.
- Require-only overloads are rejected; overloads must differ by arity or param types.
- Driver/workspace overload coverage added for multi-file module resolution.
- Multi-module overload resolution test added (qualified calls across modules).

## Next steps
- Lift the remaining duplicate-function restrictions in single-module parse paths so
  overload sets are allowed within a file/module.
- Update call resolution to handle true overload sets end-to-end (arity/type match,
  require filtering, ranking, ambiguity diagnostics).
- Add overload-focused tests (arity/type disambiguation, require ranking, ambiguity).
  Keep require as a filter, not a signature identity.

## Phase 0 — Lock invariants (non-negotiable)
- No trait objects: no `dyn Trait`, no vtables, no fat pointers.
- Traits are **not** types; they cannot appear in type positions.
- Runtime polymorphism uses **interfaces** only (already vtable-based).

## Phase 1 — Parse + HIR: represent traits as items + constraints
### 1.1 Required AST/HIR nodes
- `trait TraitName { fn ... }`
- `implement TraitName for Type { fn ... }`
- `require` clauses on:
  - structs: `struct X<T> require ... { ... }`
  - impl blocks: `implement Trait for Box<T> require ... { ... }`
  - functions: `fn f<T> require ... (..) returns .. { .. }`
- trait guard expression: `if T is TraitExpr { ... } else { ... }`

Trait expressions:
- atoms: `T is TraitName`, `Self is TraitName`
- boolean ops: `and`, `or`, `not`, parentheses

### 1.2 Canonical internal model
- `TraitId`, `TraitDecl(method_sigs, require_self_expr?)`
- `ImplId`, `ImplDecl(trait_id, for_type, require_expr?, method_bodies)`
- `RequirementExpr` boolean AST over `IsTrait(type, trait)` + `and/or/not`
- `GenericParam` and a uniform type-variable representation (`T`, `Self`)

No associated types/consts in this phase.

## Phase 2 — Global collection + indexing
Whole-program view is required (impls are injectable from any module).

Indexes:
- `trait_methods[(TraitId, name)] -> MethodSig`
- `impls_by_trait[TraitId] -> [ImplId]`
- `impls_by_type[NominalTypeId] -> [ImplId]` (optional accel)
- `required_by_type[TypeId] -> RequirementExpr` for `struct ... require ...`

### 2.2 Implementation identity and overlap
Coherence (MVP):
- For any `(TraitId, ConcreteType)` in the build graph, **at most one** applicable impl.
- If multiple could apply after substitution, error with both spans.

## Phase 3 — Trait solver (obligations + boolean exprs)
### 3.1 Obligation model
- `Obligation = (Type, TraitId)`
- `Goal = RequirementExpr` (boolean structure over obligations)

### 3.2 Prove a trait obligation
To prove `(Ty, Trait)`:
- find impls where `for_type` unifies with `Ty`
- prove impl `require` under substitution
- exactly one applicable → success
- none → failure
- multiple → ambiguity error

### 3.3 Evaluate boolean trait expressions
Use tri-state: `Yes / No / Unknown` (reject if Unknown where certainty required).
- `A and B` → both must be Yes
- `A or B` → at least one Yes (ambiguity if both and it affects overloads)
- `not A` → must prove No (not just "not proven")

## Phase 4 — Enforce `require` where spec says
### 4.1 Type completeness (`struct ... require ...`)
- MVP: enforce on **HIR-used types** (collector function) to avoid waiting on mono.
- Keep enforcement wired to a single `collect_used_types()` output so we can swap to
  monomorphized instantiations later without touching enforcement.
- Diagnostics: `E-REQUIRE-SELF` / `E-REQUIRE-T` (per spec intent).

### 4.2 Function requirements (`fn ... require ...`)
- Typecheck body assuming requirements hold.
- Enforce **per-instantiation** (per `(fn, subst)`), discovered via call sites now;
  move trigger to mono later without changing the enforcement function.

### 4.3 Impl requirements (`implement Trait for X<T> require ...`)
- Treat `require` as a filter: impl participates only when requirement proves true.

Current limitation (Phase 4):
- TraitExpr subjects are **value identifiers** (e.g., `x is Debuggable`) resolved
  from the local scope to a concrete type at typecheck time. **Type-parameter
  subjects (`T is Debuggable`) are not supported yet** and will be added once
  function generics are in the surface language.
- Trait guards are decidable only when the subject value has a concrete type;
  otherwise the guard is undecidable and is a compile error.

## Phase 5 — Trait guards (`if T is TraitExpr`)
Compile-time branching only.

Typecheck rules:
- Then-branch: assume guard is true.
- Else-branch: assume `not guard` only if provable; otherwise no added assumption.

Monomorphization rules:
- Guard provable true → lower only then-branch.
- Provable false → lower only else-branch.
- Neither → error **only when concrete**. Allow Unknown in generic defs.
  Rule: trait guard must be decidable for the current substitution environment.

## Phase 6 — Overload resolution by requirements
Algorithm:
1) Collect candidates by name/arity.
2) Type inference / unification.
3) Prove `require` under substitution.
4) Keep applicable candidates.
5) Pick most specific:
   - "more specific" if `requires(A)` implies `requires(B)` and not vice-versa.
   - MVP: only rank `and`-only positive trait atoms.
     If `or`/`not` appears in an applicable candidate, it is not rankable; require
     explicit disambiguation or report ambiguity.
6) Tie → ambiguity error.

## Phase 7 — Trait-driven semantics hooks (must be correct)
### 7.1 Destructible (RAII)
- Call `destroy(self)` exactly once on scope exit.
- `destroy(self)` must be non-throwing (checker enforces).
- Consuming `self` prevents double-destroy.

### 7.2 Copy (move/copy rules)
- Pass-by-value defaults to move; copy only if type implements `Copy`.
- `copy expr` only valid when operand is `Copy`.
- Tuple `Copy` is componentwise (trait query, no runtime).

### 7.3 Const safety
- For `val` fields as type-level constants: disallow types that implement `Destructible`.

### 7.4 Send/Sync
- Pure marker traits, enforced only by stdlib/concurrency API signatures.

## Phase 8 — Closures + callable traits
Callable traits are **traits** (`Callable`, `CallableMut`, `CallableOnce`).
- Closure lowering emits a unique closure type.
- Closure type gets implicit impls for callable traits based on capture analysis.
- `require F is Callable<...>` becomes a normal trait obligation.
- Non-escaping is enforced separately (closure/lifetime rule), not via traits.

## Phase 9 — Tests
Minimum buckets:
1) Requirement enforcement:
   - Missing `Self is Trait` on struct → error.
   - Missing `T is Trait` on instantiation → error.
   - Impl `require` filter honored.
2) Trait guards:
   - Only active branch typechecks for concrete `T`.
   - Inside guard, trait methods are available.
   - `and/or/not` behaves as specified.
3) Overload-by-require:
   - Picks constrained overload when applicable.
   - Falls back when not.
   - Ambiguity when incomparable.
4) RAII:
   - `destroy(self)` invoked on scope exit.
   - `destroy` cannot throw.
5) Closure callables:
   - Closure implements `Callable*` based on capture behavior.
   - Generic `require F is Callable...` works end-to-end.

## Non-negotiable design decisions
- Traits never appear as value types.
- All trait queries resolved at compile time from known impls.
- Trait guards do not generate runtime branching.
- Any erasure story is **interfaces**, not traits.
