# Cross-package traits work progress

This document tracks the implementation plan for cross-module / cross-package trait method resolution.

## Scope and constraints (locked)

- Trait/method resolution across package boundaries uses **interface metadata only**.
	- No body scanning for impl discovery.
	- Missing or incomplete metadata is a hard error when resolution needs it (see “Missing metadata gating”).
- **Name visibility (traits/types)** is **pub + export**.
	- A symbol is nameable from another module only if it is declared `pub` and included in `export { ... }`.
	- Reexports expose exactly the reexported module’s export set.
	- This gates all cross-module nameability, even within the same package (no “friend” privilege).
- **Impl eligibility** is **module visibility**, not export visibility.
	- Impls are not exported symbols.
	- A candidate impl is considered only if its **defining module** is visible from the caller (via the visible-module set).
- Coherence errors are **use-site errors**.
	- If multiple visible impls match, the call is ambiguous (no implicit tie-break).
- `use trait` is the only **dot-call scope gate**; UFCS does not require `use trait`.
- Keys are **module-id scoped** to prevent cross-package collisions (module ids are globally unique).
- Type matching for candidate selection uses a **canonicalized receiver head** (aliases/reexports normalize to the defining nominal type).
- Dedup is required: trait scope and candidate impl lists dedupe by `TraitKey` / `ImplKey` to avoid false ambiguities.

## Status

- Work-progress doc updated to match spec and pinned decisions.
- Next implementation step: finalize DMIR-PKG interface payload schema (traits + impl headers + method links) and loader indexes.

## Findings (pinned)

- Indexes are global: build from all loaded module interfaces (local + deps). Resolution applies per-call filtering via `VisibleModuleSet(caller)` and `TraitScope(caller)`. Optional: cache per-caller filtered views keyed by hashes (optimization only).
- `VisibleModuleSet(M)` always contains `M`.
- If `VisibilityProvenance` stores a single `ImportChain`, choose a deterministic preferred chain: shortest chain, then lexicographic by canonical `ModuleId` string sequence.
- Any metadata lookup required for resolution is a hard error if missing, including "does scoped trait define method `m`?" and UFCS trait-method lookup. No masking.
- Tests must lock inherent-method precedence over same-named trait methods.

## Definitions

### Package and module identity

- `ModuleId`: globally unique module identity, represented as the canonical `module_id` string (e.g. `std.io`).
	- The compiler/loader may intern `ModuleId` to a small integer, but the canonical identity is the string above.

### Keys

- `TraitKey = (ModuleId, trait_name)`
- `TypeKey = (ModuleId, type_name, type_args...)` (nominal types)
- `TypeHeadKey = (ModuleId, type_name)` (nominal head only)
- `ImplKey = (defining_module_id, local_impl_id)` (or deterministic hash + defining module)
- `MethodKey = (TraitKey, method_name)`

### Visibility

- `VisibleModuleSet(caller_module)`: closure of modules reachable from the caller via imports and reexports, restricted by package “surface entry modules” for cross-package imports (import roots).
	- `VisibleModuleSet(M)` always contains `M`.
- Symbol naming across modules is export-set based (pub + export). This gates **finding a trait/type by name**, not impl eligibility.

### Trait scope (dot calls)

- `TraitScope(caller_module)` is built **only** from `use trait ...` directives in that module.
- A trait can only be placed in scope if its path resolves through export-gated names.

### Canonicalization

- `CanonicalTypeHead(type)` resolves aliases and reexport paths to the defining nominal type head.
- `TypeHeadKey(recv)` is computed from `CanonicalTypeHead(recv)`.

## DMIR-PKG interface payload requirements

When a module is packaged, its interface payload must contain enough information to resolve trait calls without bodies:

### Trait metadata (exported traits only)

For each exported trait:
- `TraitKey`
- generic params
- method list:
	- method name
	- full signature (including receiver form)
	- method generics (if any)
	- method-level constraints (if supported)
	- optional span/def-path for diagnostics

### Impl headers (all impls in the module)

For each impl defined in the module (even though impls are not exported symbols):
- `ImplKey`
- `TraitKey` being implemented
- target type template (receiver type pattern) + generic params
- impl-level constraints
- method linkage:
	- `method_name -> fn_symbol_id` (or equivalent callable identity)
- optional span/def-path for diagnostics

### Loader validation

On load, validate:
- referenced `TraitKey`s exist (or produce a precise missing-trait-meta error when first used)
- method links are complete for required trait methods (or error on use-site)
- duplicate keys are rejected deterministically

## Indexes built by the loader/typechecker

Build these indexes from all loaded module interfaces (local + deps):

- `TraitMetaIndex: TraitKey -> TraitMeta`
- `TraitImplIndex: TraitKey -> [ImplHeader]`
- `ImplCandidatesByHead: (TraitKey, TypeHeadKey) -> [ImplKey]`
	- built from impl headers (head extracted from canonicalized target template)
- `TraitMethodsByName: (TraitKey, method_name) -> MethodSig`
- `VisibilityProvenance: (caller_module, visible_module) -> ImportChain`
	- used for diagnostics (“how did this module become visible?”)
	- deterministic preferred chain: shortest chain, then lexicographic by canonical `ModuleId` string sequence

All candidate lists must be deduped by `ImplKey` before ambiguity checks.

Indexes are global (all loaded module interfaces). Per-call filtering uses `VisibleModuleSet(caller)` and `TraitScope(caller)`. Optional per-caller filtered views keyed by hashes are an optimization only.

## Resolution algorithms

### Dot-call: `recv.m(args)`

1. Try inherent methods on `recv` type.
2. Otherwise:
	- Collect traits in `TraitScope(current_module)` that define method `m`.
	- If trait metadata is needed to answer "does it define `m`?", missing metadata is a hard error (do not treat as "trait does not define `m`").
3. For each such trait:
	- Candidate impls = `ImplCandidatesByHead[(TraitKey, TypeHeadKey(CanonicalTypeHead(recv)))]`
	- Filter candidates:
		- impl’s defining module ∈ `VisibleModuleSet(current_module)`
		- unification: `recv` matches impl target template
		- constraints satisfied
4. Aggregate successful matches across all scoped traits:
	- 0 matches: “no method found” (include hint if trait exists but is not in scope, when known)
	- 1 match: select it
	- >1 match: ambiguity error listing candidates deterministically

### UFCS: `TraitPath::m(recv, args)`

1. Resolve `TraitPath -> TraitKey` using export-gated naming (pub + export).
2. Run the same candidate selection and filtering as dot-call.
3. UFCS does **not** bypass impl visibility: impls still must be in the visible-module set.

## Missing metadata gating

Hard errors for missing trait/impl metadata must trigger at first attempted cross-package trait resolution use-site, not at import time.

Trigger examples:
- A dot-call attempts trait fallback and one or more candidate traits/modules are external, requiring trait/impl metadata lookup.
- A UFCS call resolves to an external trait and requires impl candidate lookup.
- Any trait-method lookup needed to decide whether a scoped trait defines `m`.
- Any UFCS trait-method lookup needed to decide whether the resolved trait defines `m`.
- Any operation that queries external `TraitMetaIndex` or external impl headers for resolution.
No masking of missing metadata is allowed.

Non-triggers:
- Importing a package/module whose trait metadata is missing, if no trait resolution consults it in this compilation unit.

No fallback to scanning bodies is allowed.

## Diagnostics requirements

Ambiguity errors must include:
- the trait (TraitKey / path)
- each candidate impl’s defining module and def-path/span if available
- the import/reexport chain that made each candidate module visible (from `VisibilityProvenance`)
- suggested fixes:
	- use UFCS with the intended trait
	- remove or narrow a `use trait` directive (dot-call)
	- remove or narrow an import/reexport that makes a conflicting impl visible (if supported)

## Tests

Add/keep these tests (deterministic outcomes required):

1. Local trait call (same module) remains unchanged.
2. Cross-module same-package trait call via exported trait + visible module impl.
3. Cross-package UFCS call succeeds without `use trait`.
4. Dot-call requires `use trait`; without it, method is not found.
5. Inherent-method precedence:
	- inherent `Type.m` exists; scoped trait also defines `m`; dot-call resolves to inherent method without consulting traits.
6. Diamond visibility (module visible through two paths) does not duplicate impls.
7. Overlap ambiguity:
	- `impl<T> Trait for Vec<T>` and `impl Trait for Vec<Int>` visible => use-site ambiguity.
8. Reexport pathing:
	- trait defined in internal module, reexported via api module => `use trait api::T` works.
9. Missing metadata gating:
	- importing a package with missing trait metadata is OK if no trait resolution consults it;
	- first use-site that consults it errors with the precise code.
10. Trait scope dedupe:
	- same trait brought into scope via multiple reexports / imports => no duplicates, no false ambiguity.
11. Candidate impl dedupe:
	- same impl visible via two paths => candidate list contains it once.

## Phased implementation plan

### Phase 0: finalize identities and keys
- Lock `ModuleId` and all key definitions above.
- Implement canonicalization for receiver type heads.

### Phase 1: emit interface payloads
- Extend DMIR-PKG interface to include:
	- exported trait metadata
	- all impl headers + method links for each module
- Implement payload validation.

### Phase 2: loader and indexes
- Build `VisibleModuleSet` and `VisibilityProvenance`.
- Build `TraitScope` from `use trait`.
- Build the trait/impl indexes from all loaded interfaces, including `(TraitKey, TypeHeadKey)` candidate lookup.

### Phase 3: typechecker integration
- Implement dot-call + UFCS algorithms using the indexes.
- Enforce impl-module visibility gating.

### Phase 4: diagnostics polish
- Deterministic ordering of candidates.
- Provenance output and fix-it hints.

### Phase 5: test suite
- Add the test cases listed above.
- Ensure no regressions in local-only resolution.
