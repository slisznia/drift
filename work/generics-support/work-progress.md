# Generics support — work plan

Goal: add function and nominal-type generics with explicit instantiation and
trait/guard integration, aligned with the updated spec.

## Status (current)
- Spec updated to allow function generics and explicit function type arguments.
- Trait guard/require subjects are type parameters or `Self` only.
- G1 parsing/plumbing landed: function `type_params` parsed and carried through
  AST/HIR/signatures; call-site type args parsed and stored on `Call`/`HCall`.
- Parser coverage added for generic function defs and explicit call type args.
- Angle tokenization uses `TYPE_LT/TYPE_GT` (and `QUAL_TYPE_LT/QUAL_TYPE_GT` for
  pre-`::` qualified members). Call-site `<type ...>` uses `CALL_TYPE_LT`.
- Call-site type arguments use the `type` marker (`id<type Int>(...)`); the
  legacy `id<Int>(...)` form is rejected to avoid comparison ambiguity.

## Phase G0 — Lock MVP scope
- Ship in this order:
  1) Function generics (`fn f<T>(x: T)`)
  2) Explicit instantiation (`f<type Int>(...)`) + minimal inference
  3) Type-param subjects for `require`/trait guards (`T is Trait`)
  4) Struct generics (`struct Box<T>`, `Box<Int>`)
  5) Generic trait impl matching (`implement Debuggable for Box<T> ...`)
- Out of scope: higher-kinded types, specialization, return-type overloading.

## Phase G1 — Syntax + AST/HIR for type parameters
### Parser/AST
- Add type parameter lists on functions (and later structs/traits/impls):
  - `fn f<T, U>(...)`
- Add optional explicit type arguments at call sites:
  - `f<type Int, String>(...)`
- Parsing note: accept `Ident<type TypeArgs>(...)` only in call position to
  avoid `<` ambiguity with comparisons.
- AST nodes:
  - `FunctionDef.type_params: list[str]`
  - `CallExpr.type_args: list[TypeExpr] | None`

### HIR/signatures
- `FnSignature.type_params: list[str]`
- `HCall.type_args: list[TypeId] | None` (or `TypeKey`, once lowered)

## Phase G2 — Type variables + substitution spine
### TypeTable / types
- Add a type variable form:
  - `TypeParamId { owner_fn_id, index }`
  - TypeId for type params points at that id.

### Substitution primitive
- `Subst: dict[TypeParamId, TypeId]`
- `apply(subst, TypeId) -> TypeId` (recursive)
- All generic logic uses this substitution (typecheck, solver, require/guards).

## Phase G3 — Generic function instantiation (explicit first)
Precondition: TypeParamId + substitution spine must exist (avoid stringly-typed params).
### Callable registry changes
- Callable candidates include:
  - `fn_id`, `type_params`, param types (possibly with TypeVars), require expr.

### Resolution pipeline (free functions)
1) Gather candidates by name
2) Arity filter
3) Type-arg handling:
   - explicit: build `Subst` from provided type args
   - implicit (MVP): infer only when param type is exactly `T`
4) Apply `Subst` to param types
5) Exact type match
6) Require filtering (solver)
7) Ambiguity/ranking (same rule as today)

### Instantiation cache
- Key: `(fn_id, tuple(type_arg_type_ids))`
- Used for require enforcement + guard evaluation + (later) mono/codegen cache.

## Phase G4 — Minimal inference (safe MVP)
- Infer `T` only from direct `T` parameters (no nested matching yet).
- Require explicit type args if underconstrained.

## Phase G5 — Type-param subjects for `require` + guards
- `require T is Trait` and `if T is Trait { ... }` are primary forms.
- `x is Trait` is **not** supported in this revision (spec-aligned).
- Trait guard evaluation occurs at instantiation time when `Subst` is concrete.

## Phase G6 — Struct generics
- Add `struct Box<T> { value: T }`
- Allow `Box<Int>` type applications in annotations and constructors.
- Typechecking: substitute struct type params into field types.

## Phase G7 — Generic trait impl matching
- Extend solver matching:
  - impl target contains type params
  - match against concrete type args, bind consistently
- Prove impl `require` under composed substitution.

## Phase G8 — Tests (high-signal)
1) Explicit generic call: `id<type Int>(1)`
2) Simple inference: `id(1)` (if MVP supports)
3) `require T is Trait` enforced
4) Trait guard chooses branch at instantiation
5) Struct generics typecheck (`Box<Int>`)
6) Generic trait impl matching (`Box<T>` with require)

## Phase G9 — Integration + cleanup
- Update work-progress with generic function support + type-param subjects.
- Ensure module qualification + FunctionId identity remain unchanged.
