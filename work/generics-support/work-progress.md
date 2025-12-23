# Generics support — work progress

Goal: add function generics with explicit instantiation and a stable, ID-based substitution spine (TypeParamId/TypeVar) that later phases can build on.

## G2 invariants (locked)
- Type params are identified by ID after parsing; names exist only for diagnostics and pretty-printing.
- Every TypeVar carries its owner (function/signature) to prevent accidental capture across functions/modules.
- Substitution is explicit and total per instantiation in G2 (no partial substitution or inference in this phase).
- Type param names live in the *type namespace* (do not collide with value identifiers).

## Phase G2 — TypeParamId + TypeVar + substitution spine

### G2.1 Data model
- Add `TypeParamId` (owner + index) and `TypeVar(TypeParamId)` as a `TypeId`/`TypeKind` variant.
  - Recommended shape: `TypeParamId { owner: FnId (or SigId), index: u16 }`.
- Change `FnSignature.type_params` from `List[str]` into:
  - `TypeParam { id: TypeParamId, name: InternedStr, span: Span }`.
  - Preserve `name`/`span` strictly for diagnostics.

### G2.2 Lowering: parser → HIR → TypeIds
- When building a function signature, allocate TypeParamIds in order and build a signature-local `name -> TypeParamId` map.
- When resolving types inside the signature (param types / return type / requirement subjects), lower matching names to:
  - `TypeVar(TypeParamId)` (not a nominal type lookup).
- Scope rule: signature type params are in scope across the whole signature, including requirements/guards.

### G2.3 Substitution spine
- Define `Subst { owner: FnId, args: Vec<TypeId> }` and enforce owner equality on apply/instantiate.
  - (Fast path is vector indexed by `TypeParamId.index`; no HashMap needed in G2.)
- Implement `apply(type_id, subst) -> TypeId`:
  - `TypeVar(id)` → `subst.args[id.index]`
  - recurse through all composite types you already represent (arrays, tuples, optionals, refs/ptrs, fn types, etc.).
  - Keep pure (no mutation); optional memoization later if you intern types and want speed.
- Add `instantiate_fn_sig(sig, subst)` to substitute param + return types (and later requirements if needed).

### G2.4 Explicit instantiation
- In call checking, build `Subst` from `call.type_args`:
  - if arg count != `sig.type_params.len()` → diagnostic (new code; span should highlight the call type-arg list).
  - otherwise instantiate callee parameter/return types *before* checking arguments.
- Ensure qualified members follow the same instantiation rule:
  - `Type::Ctor<type T>(...)` uses the same substitution mechanism (no special casing beyond callee selection).

### G2.5 Trait requirement subjects (data correctness)
- Store `T is Trait` with subject lowered to `TypeVar(TypeParamId)` (never stringly).
- Checking “satisfies trait” can be deferred, but the representation must be correct now.

## Tests (G2)
- Same name, different owners: `f<T>` vs `g<T>` remain isolated (no cross-capture).
- Substitution through nesting: `Array<T>` → `Array<Int>` and deeper nests.
- Requirements are ID-based: `where T is Hashable` stores `TypeVar` subject.
- Length mismatch diagnostic for explicit `<type ...>` call args.

## Exit criteria
- Signatures carry `TypeParamId` and types can contain `TypeVar`.
- Explicit `<type ...>` instantiation substitutes parameter/return types via `Subst`.
- Trait requirements store `TypeVar` subjects (not strings).
