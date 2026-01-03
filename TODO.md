# TODO

## MVP
[String]
- Expose/route any user-facing string printing helper once available.
- Keep expanding test coverage as features land (print, more negative cases).

[I/O]
- Move `print`/`println`/`eprint`/`eprintln` from the prelude hack into real `std.runtime` APIs (no lang.core special-casing).

[FFI / ABI]
- Document “current ABI intent” now; freeze later:
  - Variant layout intent (tag width rules, payload alignment, field order) and what is stable vs internal.
  - Calling convention assumptions at ABI boundaries and current string/array/buffer representations.
  - Add an explicit NOT YET STABLE banner + checklist for freezing.

[Traits]
- Gate `copy` via a real `Copy` trait post-typecheck.
- Trait-based iteration: replace iterator intrinsics with a real `Iterator` trait + library implementation once module support lands (no dynamic dispatch in MVP).
- Dynamic dispatch and trait bounds: pin surface syntax and type rules for trait bounds / trait objects.
- Replace iterator intrinsics with real modules/traits: migrate `Array<T>.iter()` / `__ArrayIter_<T>.next()` from compiler intrinsics to a real `Iterator` trait + library implementation when module support lands.

## Post MVP

[Error handling]
  - Captures (`^`): implement unwind-time frame capture (locals per frame + frames list), runtime representation, lowering/codegen, and e2e tests.
  - DiagnosticValue payloads: design/implement a stable ownership/handle model for opaque/object/array payload kinds so they can be stored in `Error.attrs` without ABI/lifetime churn.

[Variants]
  - Module-qualified constructor syntax: consider `Optional.Some(...)` ergonomics once namespacing rules are pinned (keep current `TypeRef::Ctor(...)`).
  - Variant pattern ergonomics: consider rest/wildcard patterns and richer exhaustiveness diagnostics (named-field construction + named binders are implemented in MVP).
  - Variant external ABI: freeze and document a stable ABI in `docs/design/drift-lang-abi.md` once FFI/packages demand it (currently compiler-private).

[Tooling / Packages]
- Phase 5 polish (highest leverage):
  - Lockfile authoritative by default: `drift build` honors `drift.lock.json`; only `drift update` changes resolution.
  - Multi-source deterministic selection rules (stable source ordering + tie-break + precedence) so identical inputs resolve identically.
  - Sharper index/identity mismatch errors (print claimed vs observed identity, signer, source id, mismatch axis).
  - `drift doctor` (sources, index sanity, trust graph, lock/cache consistency, toolchain compatibility).
  - `drift fetch --json` (machine-readable resolution/verification report for CI/IDE).
