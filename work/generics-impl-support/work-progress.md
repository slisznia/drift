# Work plan: Generics + impl support

## Status
In progress (feature work paused; refactor milestones active).

## Roadmap (refactor milestones)
Note: pause **feature work** only; keep landing small fixes + tests as safety net.

### Milestone A: LinkedWorld + RequireEnv (combine refactors 2 + 5)
**Goal:** deterministic trait proving + SAT ordering with zero cache invalidation.
- **A1. Define immutable objects.**
  - `LinkedWorld`: merged `TypeTable`, trait defs, impl defs, and all lookup indexes.
  - `RequireEnv`: normalized require ASTs, SAT atom table, trait dependency axioms.
- **A2. Build in one place.**
  - `link_world(modules, imports) -> LinkedWorld` builds and dedupes once.
  - Delete cache invalidation (`_global_trait_world`); if needed short-term, keep it private inside `LinkedWorld`.
- **A3. Convert consumers.**
  - Typechecker takes `LinkedWorld` + `RequireEnv`.
  - SAT ordering uses `RequireEnv` (no re-normalization).
  - Proving uses `LinkedWorld` impl indexes.
- **A4. Tests.**
  - Re-run cross-package trait method instantiation, SAT ordering tests, UFCS e2e.
  - **Exit criteria:** no mutation + no cache invalidation during typecheck.
- **Progress (done).**
  - `LinkedWorld`/`RequireEnv` added and wired into the typechecker entrypoint.
  - `_global_trait_world` cache removed from the typechecker path.
  - Tests updated to use `LinkedWorld` instead of `_global_trait_world`.
  - `LinkedWorld.visible_world` now computes module names once for deterministic merges.
  - `merge_trait_worlds` now dedupes impls and flags conflicting trait/require/impl definitions.
  - Visibility mapping failures emit compiler-bug diagnostics when provenance is provided; missing mappings fall back to registry-derived names.
  - `driftc` now syncs visibility provenance when module ids are added and includes prelude modules in provenance chains.
- RequireEnv now normalizes require expressions, interns SAT atoms, and provides implication checks for ordering.
- SAT-based “most specific” ordering now consumes RequireEnv (no per-call re-normalization).
- Require lookups are routed through RequireEnv (no direct `world.requires_by_*` in the checker).
- Typechecker no longer embeds legacy SAT helpers; implication is RequireEnv-only.
- `driftc` now builds `LinkedWorld`/`RequireEnv` once per package build and threads them into typecheck.
- Test helpers that use traits now pass `LinkedWorld`/`RequireEnv` into the checker.
- Trait enforcement now consumes `LinkedWorld` + `RequireEnv` (no raw `TraitWorld` paths).
- Tests share a single `build_linked_world` helper to avoid linker drift.
- `RequireEnv.requires_by_impl` removed (no ImplKey path yet).
- Milestone C started: `IdRegistry` added and TemplateHIR-v1 import interns `FunctionKey -> FunctionId` (no signature scanning).
- TemplateHIR-v1 export now includes structured `fn_id`, and import no longer parses `fn_symbol` for identity.
- Package signatures now include structured `fn_id`/`wraps_target_fn_id`, and imports no longer parse `fn_symbol`/`wraps_target_symbol`.
- External signature registration now uses structured `fn_id` keys (no `fn_symbol` parsing in callable registry).
- Impl header methods now include structured `fn_id`, and trait/impl metadata import no longer parses `fn_symbol`.
- Trait metadata now includes structured `trait_id`, and import hard-gates on it (with module/name/package checks).
- Struct schema payloads now include structured `type_id`, and type-table import validates against it.
- Impl headers now carry a stable `decl_fingerprint`, and import interns impl keys using `ImplKey(package_id, module, trait, target_head, decl_fingerprint)`.
- Trait/type keys are now package-scoped (`TraitKey`/`TypeKey`/`TypeHeadKey` include `package_id`).
- `IdRegistry` now interns typed keys (`TraitKey`, `TypeKey`, `ImplKey`), and `ImplKey` is defined explicitly.
- Require/SAT normalization now incorporates `package_id` (RequireEnv carries module→package mapping; trait/type normalization uses it consistently).
- Impl headers now include `package_id` in the trait identity and imports hard-gate on it.
- Type-table linker nominal keys now include `package_id` in the canonical key tuples.

### Milestone B: CallInfo is authoritative (finish refactor 4)
**Goal:** stage2 never guesses call targets.
- ctor calls by AST shape only; everything else must have CallInfo/call_resolutions.
- UFCS missing CallInfo → internal error.
- Qualified member indirect CallInfo ignored only for ctors → internal error otherwise.
- **Exit criteria:** stage2 does not scan signatures or infer targets.

### Milestone C: IdRegistry at import boundary (start refactor 3)
**Goal:** no string-based identity across package boundaries.
- `IdRegistry`: `FunctionKey -> FunctionId`, `TraitKey -> TraitId`, `TypeKey -> TypeId`, `ImplKey -> ImplId`.
- Package import resolves all external identifiers into stable internal IDs.
- Internal lowering can remain string-based temporarily as long as it maps to keys.
- **Exit criteria:** no string-symbol reconstruction across package boundaries.

### Milestone D: Phase bundles / immutability wrappers (start refactor 1)
**Goal:** make phase boundaries explicit without a full pipeline rewrite.
- Introduce `ModuleLowered { hir, signatures, requires, type_defs, impl_defs }`.
- Stop passing raw dicts/maps between phases; pass bundles instead.
- **Exit criteria:** compiler entrypoints take explicit bundles, not loose maps.
- **Progress (in flight).**
- `ModuleLowered` bundle added (`lang2/driftc/module_lowered.py`) with a `flatten_modules` adapter.
- `ModuleLowered` now carries per-module requires/type defs/impl defs (populated from the trait world and parser).
  - Workspace parsing now returns `dict[module_id, ModuleLowered]` instead of loose maps.
  - `driftc` and codegen e2e runner flatten bundles for existing pipelines.
  - Tests updated to adapt via `flatten_modules` where needed.

## Completed (recent)
- TemplateHIR-v1 export/import keyed by FunctionKey with required `generic_param_layout`.
- Generic method templates included in package payloads (inherent + trait).
- Call-site instantiations recorded for inferred type args (impl + fn) and consumed by monomorphization.
- `impl_type_params`-only methods instantiate correctly once receiver args are known.
- Receiver-mode preference is enforced for method resolution (lvalue/rvalue ordering).
- SAT/implication ordering for `require`-based overload resolution in method candidate sets.
- Trait method generics parse + metadata propagation (TemplateHIR + trait metadata).
- Cross-package instantiation for impl + method generics (method-level type params).
- Trait method inference test for method-level type params (local).
- LinkedWorld/RequireEnv introduced; typechecker no longer depends on `_global_trait_world`.

## What's missing today
- Full stdlib container implementations in userland (still relying on compiler intrinsics).

## End result (user POV)
Users can write generic functions and generic impl blocks, and the compiler monomorphizes them into concrete code.

Examples (expected to work):

```drift
fn id<T>(value: T) returns T {
    return value;
}

fn main() returns Int {
    return id(1);
}
```

```drift
struct Box<T> { value: T }

implement<T> Box<T> {
    fn get(self: &Box<T>) returns &T {
        return &(*self).value;
    }
}
```

```drift
trait Show { fn show(self: &Self) returns String }

implement<T> Show for Box<T> require T is Show {
    fn show(self: &Box<T>) returns String {
        return "Box(" + (*self).value.show() + ")";
    }
}
```

And this should enable stdlib containers to live in userland modules:

```drift
struct Vec<T> { /* fields */ }

implement<T> Vec<T> {
    fn push(self: &mut Vec<T>, value: T) returns Void { /* ... */ }
    fn get(self: &Vec<T>, idx: Int) returns &T { /* ... */ }
}
```

## How we can get there
1. **Surface rules (lock behavior).**
   - Keep type argument inference for generic functions/methods; if underconstrained, emit a hard error.
   - Explicit `<type ...>` arguments remain allowed and override inference.
   - Confirm syntax for generic function definitions and generic `implement<T>` blocks (including trait `require` clauses).
   - **Grammar convergence (hard gate):** make the grammar and spec match the chosen surface forms
     (parenthesized parameter lists, receiver syntax, `<type ...>` type args). Treat mismatches as
     build-breaking CI errors.
   - **Spec alignment:** update the spec to adopt the package-scoped coherence/orphan rule
     (impl allowed only if trait or receiver type head is defined in the current package).
   - **Spec alignment:** update trait-guard semantics to allow guard-scoped dot-call visibility
     (in addition to file-scoped `use trait`) and to add guard assumptions to proof.
   - **UFCS support (hard gate):** define the UFCS surface form for trait method disambiguation,
     parse it, and route it through resolution as a single forced candidate.
     - Proposed form: `TraitName::method(receiver, args...)` (module-qualified trait names allowed).
     - UFCS bypasses `use trait` scope but still respects visibility.
     - HIR stores the resolved FunctionKey/ImplKey on the call node so later passes do not re-resolve.

2. **Representation in AST/HIR.**
   - Ensure function definitions carry `type_params` and `require` clauses in HIR.
   - Make impl blocks carry `impl_type_params` for inherent and trait impls.
   - Ensure struct/variant type definitions carry type-level `require` (e.g., `struct Box<T> require T is Clonable`).
   - Ensure trait definitions carry `require` (trait dependencies).

3. **Type checking and resolution.**
   - Introduce a type-param scope for functions and impls; create type vars for `T` params.
   - At call sites, instantiate generic signatures using explicit type args or inferred args.
   - Build dot-call candidates using a **trait visibility environment**:
     - base: file-scoped `use trait ...`
     - plus per-branch assumptions from trait guards (`if T is Trait`, etc.)
   - Keep trait bounds for applicability checks (separate from lookup scope).
   - Branch-local trait-guard assumptions feed both dot-call visibility and `prove_expr` in that branch.
   - For method calls, resolve receiver mode first (lvalue prefers `self: &T`, then `self: &mut T`, then `self: T`; rvalues only `self: T`).
   - Match `impl<T>` blocks against the receiver’s concrete type, solve `T` args, and apply trait bounds.
   - Overload resolution: filter by satisfiable `require`, then choose the most specific applicable candidate; else emit ambiguity.
     - **Specificity rule:** A is more specific than B iff `require_A ⇒ require_B` and not vice versa.
       Incomparable requires are an ambiguity error.
     - Implement implication as SAT/unsat over boolean `require` expressions:
       `A ⇒ B` iff `A ∧ ¬B` is UNSAT. If neither implies the other, they are
       incomparable → ambiguity error.
       SAT instance includes trait-dependency axioms (see C2).
   - **Coherence rule:** after `require` filtering, if multiple trait impls match the same concrete
     specialization, emit a hard error with all impl origins. For inherent methods, require uniqueness
     per `(TypeHead, method name, receiver mode, param types)`; if multiple match, error.
   - **Dedup rule:** before coherence/ambiguity checks, dedupe candidates by stable impl identity
     (ImplKey/TraitKey + target specialization) **after** key normalization so re-exports do not
     trigger false conflicts.
   - **Canonicalization rule (global):** all impl/type identity checks use the same canonical form
     (alias-expanded + canonical defining module), including:
     - impl lookup TypeHeadKey
     - receiver matching for `implement<T> Type<...>`
     - coherence uniqueness tuple `(TypeHead, method name, receiver mode, param types)`
     - instantiation key type args
   - **Global coherence policy:** an impl is legal only if the trait is defined in the current
     package **or** the receiver type head is defined in the current package. (No cross-package
     orphan impls by default.)
   - Enforce type-level `require` at type application sites (instantiating `Box<NonClonable>` is ill-formed).
   - When a type is well-formed, its type-level `require` obligations become proof assumptions
     for values of that type (fed into `prove_expr` as implied facts).

4. **Monomorphization and instantiation.**
   - Emit TemplateHIR for generic functions and generic methods (inherent + trait).
   - Instantiate TemplateHIR at each use site into concrete HIR/MIR based on resolved type args.
   - Deduplicate generated symbols via the existing instantiation key + ODR policy.
   - Dedup boundary: package build artifact-level. Identity is `(FunctionKey, canonical type_args...)`.
     Linkonce/ODR folding is a safety net only, not the primary dedup mechanism.

5. **Packages and cross-module use.**
   - Export generic templates for functions and impl methods in package payloads (DMIR template bodies, not just signatures).
   - Import templates from dependencies and instantiate via a **package-build–wide queue**
     (across all CUs/modules), emitting one canonical set of monomorphized symbols.
   - Ensure module interface metadata is sufficient to instantiate generics without source.
   - **Template identity stability:** exported templates must use a stable FunctionKey
     (package id + canonical module path + declared name + stable disambiguator).
     Do not export ordinal-based identity as the canonical key.
   - **Disambiguator definition:** `decl_fingerprint = hash(kind + canonical module + declared name +
     arity + canonical param types + receiver mode + trait key + impl receiver head key +
     generic_param_layout_hash + require_fingerprint)`, where `generic_param_layout_hash` is the hash
     of the canonical `generic_param_layout` list and `require_fingerprint` is a hash of the
     normalized `require` AST using canonical atom keys (sentinel for "no require").
     Canonical atoms use `TyVar(scope=impl|fn|trait_self, index)` for type variables.
   - **Orphan rule gate:** update spec text (and add a spec example + error code) before shipping
     the package-scoped coherence policy.

6. **Tests (MVP coverage).**
   - Generic free function calls with explicit type args.
   - Generic inherent methods on generic types.
   - Generic trait impls with `require` bounds.
   - Cross-module generic method resolution + instantiation.
   - End-to-end codegen for a small userland container (e.g., `Vec<T>`).

## Implementation details (current code path + concrete changes)

### A) Package templates: encode/decode flow
**Current state (today):**
- Export: `lang2/driftc/packages/provisional_dmir_v0.py` `encode_generic_templates(...)`
  - Emits `generic_templates` payload entries with:
    - `template_id` `{module, name, ordinal}`
    - `signature` (encoded FnSignature)
    - `require` (encoded trait expr if any)
    - `ir_kind = "TemplateHIR-v0"`
    - `ir` (HIR block)
- Import: `lang2/driftc/driftc.py` `decode_generic_templates(...)`
  - Decodes TemplateHIR, stores in:
    - `external_template_hirs_by_id[FunctionId]`
    - `external_template_requires_by_id[FunctionId]`

**Target state (stable contract):**
- Payload uses `template_id` as a stable FunctionKey:
  - `FunctionKey = (package_id, canonical_module_path, declared_name, decl_fingerprint)`
  - `decl_fingerprint` includes `require_fingerprint` (normalized `require` AST, canonical atoms).
- Template payload includes **generic parameter layout**:
  - `generic_param_layout = [(scope=impl|fn, index), ...]` (required canonical form).
  - `impl_type_param_count` + `fn_type_param_count` may be derived, but are not the authoritative form.
- `ir_kind = "TemplateHIR-v1"`.
- Import stores templates in maps keyed by FunctionKey:
  - `external_template_hirs_by_key[FunctionKey]`
  - `external_template_requires_by_key[FunctionKey]`
  - `external_template_layout_by_key[FunctionKey]`
- If an internal FunctionId is needed, derive it from FunctionKey (never the reverse).
- **Versioning:** `TemplateHIR-v1` is required for new artifacts; `TemplateHIR-v0` is legacy/import-only.
- Trait requirement metadata is keyed by FunctionKey; if the trait world needs FunctionId,
  map deterministically from FunctionKey.

**Delta (concrete todo):**
- Replace serialized `template_id` with FunctionKey; keep ordinals internal-only.
- Key external template maps by FunctionKey, not ordinal-derived ids.
- Emit and consume the generic parameter layout in template payloads.
- Bump `ir_kind` to `TemplateHIR-v1` and keep `TemplateHIR-v0` only for legacy imports.
- Ensure methods from `implement<T>` blocks are included in `per_module_hir` so
  `encode_generic_templates(...)` emits templates for generic methods, not just
  free functions.
- Keep template bodies in package payloads (DMIR) as the canonical export for
  downstream monomorphization; signatures alone are insufficient.
  - **Milestone gate:** “generic method templates exported/imported end-to-end” is required
    before generics are considered usable in stdlib packages.

Pseudo-flow (export/import):

```text
// export (package build)
generic_templates = encode_generic_templates(module_id, signatures, hir_blocks, requires_by_symbol)
payload["generic_templates"] = generic_templates

// import (consumer build)
for entry in decode_generic_templates(payload["generic_templates"]):
    if entry.ir_kind == "TemplateHIR-v1":
        template_hirs_by_key[function_key] = normalize_hir(entry.ir)
        requires_by_key[function_key] = entry.require
        layout_by_key[function_key] = entry.generic_param_layout
```

### B) Instantiation in `compile_stubbed_funcs` (driftc.py)
Current behavior:
- Builds `template_hirs_by_key` from:
  - external templates, and
  - local signatures with `type_params`/`impl_type_params`.
- Requests instantiations only for calls that **spell explicit type args**
  (via `_collect_typearg_calls` scanning `HCall`/`HMethodCall` with `type_args`).
- Instantiates by cloning the template HIR, substituting into the signature,
  then re-typechecking the instantiation; rewrites call targets to the
  instantiated symbol.

Core logic (simplified from `lang2/driftc/driftc.py`):

```text
template_hirs_by_key = external_templates + local_generic_templates

for typed_fn in typed_fns:
    for call in _collect_typearg_calls(typed_fn.body):
        if sig.type_params:
            request_instantiation(target_key, explicit_type_args)

while inst_queue:
    handle = inst_queue.pop()
    inst_sig = apply_subst(sig, type_args)
    inst_hir = normalize_hir(template_hir)
    typecheck(inst_fn_id, inst_hir, inst_sig)
    enqueue nested instantiations from inst_hir
    rewrite call_info targets to inst_fn_id
```

Concrete todo:
- Replace `_collect_typearg_calls` as the sole trigger. We need a new source of
  truth that includes **inferred** type arguments.
- Support `impl_type_params`-only methods (e.g., `implement<T> Box<T> { ... }`)
  by treating receiver-matched impl arguments as instantiation inputs even when
  the method itself has no `type_params`.

Suggested data plumbing:

```text
// in type_checker: record resolved type args per call node
typed_fn.instantiations[call_site_id] = {
    target_key,
    type_args: [impl_args..., fn_args...],
}

// in compile_stubbed_funcs: request instantiation from that map
for (call_site_id, req) in typed_fn.instantiations:
    _request_instantiation(req.target_key, req.type_args)
```

### C) Type checker: inference + instantiation hooks
Current behavior:
- Inference exists (`_instantiate_sig_with_subst`); it returns `InferResult`
  including `subst` and `inst_params`/`inst_return`.
- The resolved substitution is **not persisted** on call sites; it is used to
  type-check and then discarded.

Concrete todo:
- Persist the resolved type args (from `InferResult.subst`) in a call-site map.
- For method calls, also persist impl substitutions from `_match_impl_type_args`.
- Define a deterministic ordering for instantiation keys:
  - `type_args = impl_type_args + fn_type_args` is the simplest.
  - Use that ordering consistently in `build_instantiation_key(...)`.

Pseudo-code sketch for call typing:

```text
inst_res = _instantiate_sig_with_subst(sig, arg_types, expected_type, explicit_type_args, allow_infer)
if inst_res.ok:
    resolved_fn_args = inst_res.subst.args if inst_res.subst else []
    resolved_impl_args = impl_subst.args if impl_subst else []
    typed_fn.instantiations[call_site_id] = (target_key, resolved_impl_args + resolved_fn_args)
```

### D) Receiver preference + trait lookup scope
Current behavior:
- `method_resolver.py` treats multiple viable candidates as ambiguous; no
  receiver-mode preference is applied.
- `type_checker.py` already gates trait dot-call candidates by
  `trait_scope_by_module` (the `use trait ...` set), but this behavior is not
  reflected in the plan.

Concrete todo:
- Implement receiver-mode preference in the method resolver or in the
  type-checker selection step:
  - lvalue receiver: prefer `self: &T`, then `self: &mut T`, then `self: T`
  - rvalue receiver: allow only `self: T`
- If `self: T` is selected for an lvalue receiver, bind by copy if `T is Copy`,
  otherwise move and mark the lvalue as moved (unusable after the call).
- Keep trait lookup scope separate from `require` proof:
  - `use trait` controls candidate visibility.
  - `require` controls candidate applicability.

### E) Overload resolution with `require` + inference
Current behavior:
- `type_checker.py` uses `prove_expr` to validate `require` after instantiation,
  but candidate ordering is still ambiguous when multiple apply.

Concrete todo:
- Establish the explicit resolution pipeline:
  1) build candidate set (visible + receiver compatible),
  2) instantiate + infer (or fail),
  3) filter by `require`,
  4) pick most-specific using C2 implication ordering; no other tie-breakers.
### C1) Call-site identity stability
Current risk: using raw `node_id` for instantiation requests only works if IDs are
stable across normalization, cloning, and re-typechecking.

Concrete todo:
- Introduce a dedicated `CallSiteId` (or `ExprId`) assigned at parse/HIR build.
- Preserve it through normalization and template cloning; cloned call-sites get
  new deterministic IDs.
- Use `CallSiteId` as the key for instantiation requests.
- When template cloning creates new call nodes, assign fresh deterministic CallSiteIds.

### C2) “Most specific” as logical implication
Implement implication over the full boolean `require` language (`and`/`or`/`not`/parentheses)
as propositional SAT over canonical atoms (no trait-solver semantics):

```text
// more-specific check
more_specific(A, B) := implies(require_A, require_B) && !implies(require_B, require_A)
```

```text
implies(A, B) iff (A ∧ ¬B) is UNSAT
```

Atoms are canonicalized before SAT encoding:
- `AtomKey = (TraitKey, CanonicalTypeTuple)`
- Types in atoms use alias-expansion + canonical defining module, same as impl matching.
- Type variables are encoded canonically as `TyVar(scope=impl|fn|trait_self, index)`;
  `Self` uses `scope=trait_self`.

Implication runs over these boolean atoms **plus** axioms from the trait dependency graph:
for each trait `X` with requirement expression `ReqX(Self)`, add the axiom
`Atom(Self is X) ⇒ ReqX(Self)` (with `ReqX` normalized), transitively.
Trait proving is **separate** and only used to filter applicability; implication is for ordering
among already-applicable candidates and is always decidable at this level.
