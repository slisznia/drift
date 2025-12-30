# TODO

## MVP

[String]
- Remaining surface/runtime work:
  - Expose/route any user-facing string printing helper once available.
  - Keep expanding test coverage as features land (print, more negative cases).

[FFI / ABI]
- Document “current ABI intent” now; freeze later:
  - Variant layout intent (tag width rules, payload alignment, field order) and what is stable vs internal.
  - Calling convention assumptions at ABI boundaries and current string/array/buffer representations.
  - Add an explicit NOT YET STABLE banner + checklist for freezing.

## Post MVP

[Error handling]
  - Captures (`^`): implement unwind-time frame capture (locals per frame + frames list), runtime representation, lowering/codegen, and e2e tests.
  - DiagnosticValue payloads: design/implement a stable ownership/handle model for opaque/object/array payload kinds so they can be stored in `Error.attrs` without ABI/lifetime churn.
  - Try-expression restriction: decide whether to relax “attempt must be a call” beyond call/method-call in v1 (spec + checker + lowering).

[Closures]
- Capture discovery is field-projection only; index/deref projections still error. Example:
  ```
  let a = [1, 2];
  let f = || a[0];
  ```
- Explicit capture list follow-ups:
  - Allow projections in `captures(...)` with renaming (e.g., `p = &x.field`).
  - Support explicit/implicit mixing or capture-list overrides (if desired).
  - Gate `copy` via a real `Copy` trait post-typecheck.
  - Add lifetime-tracked closure types so borrowed-capture closures can escape.
  - Refine escape analysis beyond conservative "unknown call site" handling.

[Borrow / references]
  - Escape sink #3 (closures/unknown contexts): once closures exist, enforce “borrowing closures are non-escaping only” and reject passing `&`/`&mut` captures (or ref-typed params) to unknown call sites; add e2e negatives.
  - Place model expansion: extend `HPlaceExpr.base` beyond locals/params once globals/captures land (so borrow/move/assign can target them).
  - NLL-lite: replace lexical borrow lifetimes with loan liveness ending at last use (CFG-based), so “borrow then write after last use” stops being rejected.
  - Autoref/autoderef: decide whether to introduce limited autoderef for method calls / operators (currently explicit `*p` / `(*p).field`).
  - Extra overlap tests as syntax grows: deepen projection overlap coverage once new projection forms are added.

[Variants]
  - Module-qualified constructor syntax: consider `Optional.Some(...)` ergonomics once namespacing rules are pinned (keep current `TypeRef::Ctor(...)`).
  - Variant pattern ergonomics: consider rest/wildcard patterns and richer exhaustiveness diagnostics (named-field construction + named binders are implemented in MVP).
  - Variant external ABI: freeze and document a stable ABI in `docs/design/drift-lang-abi.md` once FFI/packages demand it (currently compiler-private).

[Iteration]
  - Trait-based iteration: replace iterator intrinsics with a real `Iterator` trait + library implementation once module support lands (no dynamic dispatch in MVP).
  - Dynamic dispatch and trait bounds: pin surface syntax and type rules for trait bounds / trait objects.
  - Generic functions and generic `implement<T>` blocks: extend generics beyond nominal types.
  - Replace iterator intrinsics with real modules/traits: migrate `Array<T>.iter()` / `__ArrayIter_<T>.next()` from compiler intrinsics to a real `Iterator` trait + library implementation when module support lands.

[Tooling / Packages]
- Phase 5 polish (highest leverage):
  - Lockfile authoritative by default: `drift build` honors `drift.lock.json`; only `drift update` changes resolution.
  - Multi-source deterministic selection rules (stable source ordering + tie-break + precedence) so identical inputs resolve identically.
  - Sharper index/identity mismatch errors (print claimed vs observed identity, signer, source id, mismatch axis).
  - `drift doctor` (sources, index sanity, trust graph, lock/cache consistency, toolchain compatibility).
  - `drift fetch --json` (machine-readable resolution/verification report for CI/IDE).
