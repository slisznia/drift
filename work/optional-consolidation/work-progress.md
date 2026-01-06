# Optional Consolidation Work Progress

## Goal
Consolidate `Optional<T>` as a regular variant type, remove Optional-specific ABI/codegen paths, and rely on the generic variant lowering everywhere.

## Plan
- [done] Inventory all Optional-specific logic (TypeKind.OPTIONAL, Optional ops, Optional ABI helpers) and map to variant equivalents.
- [done] Lock Optional layout contract: `None` tag = 0, `Some(T)` tag = 1, stable arm order independent of surface listing.
- [todo] Keep Optional as a surface type while removing Optional-specific IR kinds (lower to canonical `Variant` or `Named` that expands to variant).
- [todo] Replace Optional-specific MIR/LLVM lowering with generic variant lowering (constructors, tests, match, copy/dup, ops).
- [todo] Specify and enforce variant copy/dup/drop invariants (arm-wise copy/drop delegates to payload semantics; inactive arm has no payload).
- [todo] Ensure Optional<Bool> follows Bool storage/value rules; add targeted IR golden.
- [todo] Add mechanical tests that Optional ops/kinds are gone (no Optional MIR ops/TypeKind.OPTIONAL; IR uses variant only).
- [todo] Ensure variant layout remains deterministic for generic instantiations (stable arm list, stable cache keys, no dict-order deps).
- [todo] Remove Optional-specific type kinds and special cases once all paths use variant (type table, codegen, tests, docs).
- [todo] Update docs/spec to reflect Optional as a standard variant and remove Optional ABI claims.

## Log
- 2026-01-05: Created work progress file and captured plan.
  2026-01-05: Added layout contract, surface/IR split, copy/drop invariants, Bool storage checks, and deterministic tests per review.
  2026-01-05: Inventory pass (partial) found Optional-specific logic in:
    - TypeTable: `lang2/driftc/core/types_core.py` `new_optional()` cache + instantiation.
    - Type resolver: `lang2/driftc/core/type_resolve_common.py` Optional<...> shorthand parsing.
    - Parser prelude injection: `lang2/driftc/parser/__init__.py` injects `lang.core Optional<T>` variant base.
    - MIR nodes: `lang2/driftc/stage2/mir_nodes.py` OptionalIsSome/OptionalValue and DV Optional ops.
    - Stage2 lowering: `lang2/driftc/stage2/hir_to_mir.py` uses `_opt_*` type ids, Optional base instantiation, Optional-specific match handling.
    - ARC pass: `lang2/driftc/stage2/string_arc.py` handles OptionalIsSome/OptionalValue.
    - LLVM codegen: `lang2/codegen/llvm/llvm_codegen.py` OptionalIsSome/OptionalValue NotImplemented, Optional runtime types, opt_* TypeIds.
    - Runtime: `lang2/runtime/diagnostic_runtime.[ch]` Optional structs + DV conversions; `lang2/runtime/error_dummy.[ch]` OptionalString.
    - Tests: core/type_table Optional caches, parser qualified ctor tests, stage2 for-desugaring Optional match binders, codegen optional ops tests, package tests exporting variant Optional.
  2026-01-05: Enforced Optional arm order in prelude injection (`None` then `Some`) to lock tag order.
  2026-01-05: Removed MIR OptionalIsSome/OptionalValue ops and references (mir_nodes, stage2 __init__, string_arc, llvm codegen).
  2026-01-05: DV optional ABI pivoted to out-params + bool return; removed DriftOptional* runtime structs; updated DVAs* lowering/tests; aligned DV ctor ABI.
  2026-01-05: Switched DV optional ABI to out-params + bool return; removed DriftOptional* structs and optional helpers from runtime headers; updated LLVM DVAs* lowering to build Optional variants directly and retain borrowed strings; updated DV-related LLVM tests; removed duplicate @dataclass on DVAsInt.
  2026-01-05: Aligned `TypeTable.new_optional` arm order to `None` then `Some` to match canonical Optional layout.
  2026-01-05: Changed DV runtime helpers to return `bool` and updated DVAsInt/DVAsBool lowering to avoid uninitialized out-param loads (branch + phi).
  2026-01-05: Aligned DV constructor ABI in LLVM (drift_dv_int uses isize, drift_dv_bool uses i8) and zext bools before calls.
  2026-01-05: Fixed FnResult ok-zero defaults for Uint/Uint64/Float and corrected struct CopyValue/ZeroValue handling for Bool storage types.
  2026-01-05: Fixed struct size/align computation to use StructInstance.field_types for instantiated structs.
  2026-01-05: Seeded Byte in builtin priming order to keep TypeIds deterministic.
  2026-01-05: Fixed StringCmp cast on 32-bit to avoid invalid bitcast and updated test expectations.
  2026-01-05: Removed redundant pointer-null bitcasts in ZeroValue and avoided same-type FnPtrConst bitcasts (tests updated).
  2026-01-05: Require fnptr const signature metadata to avoid unsafe fallback casts; ZeroValue for pointers now emits no IR (typed null constant).
  2026-01-05: Fixed ArrayLit to emit valid insertvalue into dest; restored ZeroValue pointer SSA emission.
  2026-01-05: ArrayLit now performs CopyValue for Copy-but-not-bitcopy elements; added Array<String> literal retain IR test.
  2026-01-05: FnResult Bool ok payload now stored as i8 with conversions in ConstructResultOk/ResultOk; Array<ZST> asserted in codegen.
