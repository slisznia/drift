# Optional Consolidation Work Progress

## Goal
Consolidate `Optional<T>` as a regular variant type, remove Optional-specific ABI/codegen paths, and rely on the generic variant lowering everywhere.

## Plan
- Inventory all Optional-specific logic (TypeKind.OPTIONAL, Optional ops, Optional ABI helpers) and map to variant equivalents.
- Lock Optional layout contract: `None` tag = 0, `Some(T)` tag = 1, stable arm order independent of surface listing.
- Keep Optional as a surface type while removing Optional-specific IR kinds (lower to canonical `Variant` or `Named` that expands to variant).
- Replace Optional-specific MIR/LLVM lowering with generic variant lowering (constructors, tests, match, copy/dup, ops).
- Specify and enforce variant copy/dup/drop invariants (arm-wise copy/drop delegates to payload semantics; inactive arm has no payload).
- Ensure Optional<Bool> follows Bool storage/value rules; add targeted IR golden.
- Add mechanical tests that Optional ops/kinds are gone (no Optional MIR ops/TypeKind.OPTIONAL; IR uses variant only).
- Ensure variant layout remains deterministic for generic instantiations (stable arm list, stable cache keys, no dict-order deps).
- Remove Optional-specific type kinds and special cases once all paths use variant (type table, codegen, tests, docs).
- Update docs/spec to reflect Optional as a standard variant and remove Optional ABI claims.

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
  2026-01-05: Stage2 now seeds Optional<T> variant base on demand (None/Some order) when missing in test harnesses.
  2026-01-05: Stage2 DVAs* now uses Optional variant instantiation (no new_optional cache); added shared _optional_variant_type helper.
  2026-01-05: Array iterator next() now uses _optional_variant_type and inserts CopyValue for Copy elements; updated iterator layout comments to &Array<T>.
  2026-01-05: TypeTable declare_struct/declare_variant made idempotent on (module_id,name) with schema mismatch errors.
  2026-01-05: Array iter intrinsic now auto-borrows Array<T> places; next() accepts place receivers and compares idx < len in Uint space.
  2026-01-05: TypeChecker now validates iter()/next() receivers are addressable places; iterator next() guards negative idx before Uint conversion.
  2026-01-06: Stage2 iter/next misuse now recovers with Unknown values in recover mode (asserts in strict).
  2026-01-06: TypeChecker Optional cache now uses variant instantiation; package/link and driftc seeding no longer call new_optional.
  2026-01-06: define_struct_fields made idempotent for identical field definitions (mismatch is a hard error).
  2026-01-06: resolve_opaque_type now auto-declares the canonical lang.core Optional base and resolves Optional<T> to the variant; added a core test for arm order (None/Some).
  2026-01-06: Added Optional mechanical tests (no Optional MIR ops/TypeKind.OPTIONAL) and LLVM tests for Optional<String>/Optional<Array<String>>/Optional<Optional<String>> copy/drop, Optional<Bool> storage decode, and absence of DriftOptional legacy types.
  2026-01-06: Removed TypeTable.new_optional and updated core/codegen tests to instantiate Optional via canonical variant base; removed Optional caches in the type checker.
  2026-01-06: Documented Optional as a standard variant with fixed tag order (None=0, Some=1) in the spec.
  2026-01-06: Added a core test asserting deterministic variant instantiation caching and stable arm order for generic variants.
  2026-01-06: Stage2 Optional instantiation now uses TypeTable.ensure_optional_base (hir_to_mir Optional base lookup removed).
  2026-01-06: Spec updated to allow named variant constructor args (no mixing), define error rules, source-order evaluation, and note field names are API.
  2026-01-06: TypeChecker array-iterator return type now uses ensure_optional_base (no Optional base lookup fallback).
  2026-01-06: TypeChecker now filters ctor-to-variant diagnostics by visible modules for E-CTOR-EXPECTED-TYPE.
  2026-01-06: Added stage2 test asserting variant ctor kwargs evaluate in source order (left-to-right) regardless of field order.
  2026-01-06: Added forward nominal kind and upgraded ensure_named/declare_struct/declare_variant to reuse forward TypeIds; forward nominals are not Copy/BitCopy.
  2026-01-06: resolve_opaque_type now uses a core variant allowlist (Optional) and avoids minting placeholders when nominal structs/variants exist.
  2026-01-06: ctor-to-variant diagnostics now restrict fallback to current-module only when visibility provenance is missing.
  2026-01-06: Added reserved nominal type name checks for struct/variant declarations (builtins cannot be redefined).
  2026-01-06: Generic type instantiations now error when the base is not a known struct/variant (type args are not dropped).
  2026-01-06: Replaced remaining E_UNKNOWN_GENERIC in type checker with E-TYPE-NOT-GENERIC/E-TYPE-UNKNOWN gating for generic args.
  2026-01-06: Reserved nominal type names are now rejected for exception declarations (E-NAME-RESERVED in parser).
  2026-01-06: TypeTable generic expr evaluation now returns Unknown when args are supplied for non-generic/unknown bases (no silent arg dropping).
  2026-01-06: resolve_opaque_type now guards core allowlist bare generics with allow_generic_base, and variant instantiation errors return Unknown instead of crashing.
  2026-01-06: Workspace parser now requires module declarations for module-path builds, removes module-id inference, and errors on duplicate module ids (one file per module).
  2026-01-06: Workspace trait scopes are now module-scoped only (no trait_scope_by_file/path keys) to avoid path-dependent semantics.
  2026-01-06: Module alias resolution now uses module-scoped aliases (no module_aliases_by_file in type/call rewrite paths).
  2026-01-06: Driver tests now pass module-scoped trait scopes to the checker (trait_scope_by_file removed from test harnesses).
  2026-01-06: parse_drift_files_to_hir now rejects multi-file modules (no merging); workspace docs updated to module-scoped imports.
  2026-01-06: encode_span now strips absolute file paths in DMIR encoding to avoid host-path leakage in package metadata.
  2026-01-06: Fixed broken module_paths insertions in driver tests (trait_method_resolution/trait_guard_scoping/trait_diagnostic_goldens) and restored valid parse_drift_workspace_to_hir calls.
  2026-01-06: Method resolution e2e diagnostic test now uses module main with struct Point and asserts the "no matching method" diagnostic via JSON output.
  2026-01-06: Added module headers to borrow checker lambda capture overlap tests to avoid implicit-main drift.
  2026-01-06: apply_subst now substitutes variants only via instances (removed param_types fallback).
  2026-01-06: Spec FFI section now explicitly scopes fixed-width primitives to lang.abi.* usage in v1 examples.
  2026-01-06: Primitive palette table now marks fixed-width scalars as reserved in v1 (lang.abi.* only).
  2026-01-06: apply_subst now asserts on variant param_types without a variant instance (internal invariant guard).
  2026-01-06: Spec now treats Float as target-native (IEEE-754 binary32/64 on supported targets) and removes v1 F64 pinning.
  2026-01-06: Spec now states Float layout is target-defined and ABI stability is per-target, not cross-target.
  2026-01-06: apply_subst now falls back to variant base instantiation when param_types exist without an instance (asserts if base missing).
  2026-01-06: Renamed module_root_mismatch e2e to module_root_unrelated_ok and clarified description to reflect allowed behavior.
  2026-01-06: CLI/module docs now state --module-path is discovery-only (no path-inferred module ids); parser AST comment updated.
  2026-01-06: Spec now distinguishes value prelude vs always-on type prelude; Array in scope moved to type prelude wording.
  2026-01-06: Removed multi-file module merge helper (_merge_module_files); one-file-per-module enforced end-to-end in workspace parsing.
  2026-01-06: Workspace parsing now relabels diagnostics to module-id SourceLabels (<module>) to avoid host-path leakage; export span note updated for single-file modules.
  2026-01-06: Workspace parser diagnostics no longer embed filesystem paths; path ordering now uses module-root-relative keys for determinism.
  2026-01-06: Fixed workspace parser indentation after diagnostic message cleanup.
  2026-01-06: Normalized workspace parse loop indentation (module_paths vs non-module_paths branches).
  2026-01-06: Removed file-scoped trait scope parameter from TypeChecker API and updated call sites/tests.
  2026-01-06: Added SourceLabel relabeling (<source> then <module>) for all workspace diagnostics and switched path sort fallback to content hash.
  2026-01-06: resolve_opaque_type now enforces allow_generic_base for core allowlist in raw-string resolution.
  2026-01-06: _relabel_diagnostics now replaces Span with dataclasses.replace to avoid frozen Span mutation.
  2026-01-06: parse_drift_to_hir now resolves paths and relabels diagnostics to <source>/<module> without filesystem paths.
  2026-01-06: Workspace parsing sorts by content hash, sorts parsed entries by module id, and enforces module declarations for multi-file builds.
  2026-01-06: _diag_to_json now uses <source> for missing file labels; spec updated for catch name resolution and script-only implicit main.
  2026-01-06: resolve_opaque_type now uses depth-aware FnResult<> parsing and guards generic struct bases in raw-string paths.
  2026-01-06: JSON diagnostics now use <source>/<package>/<trust-store> labels instead of filesystem paths.
  2026-01-06: Parser/driver comments updated to module-scoped imports (removed file-scoped wording).
  2026-01-06: resolve_opaque_type string FnResult recursion now threads type_params/allow_generic_base; driftc package/trust diagnostics no longer embed filesystem paths in message text.
  2026-01-06: Added deep typevar detection for generic instantiation decisions; variant instantiation split into template vs concrete APIs to prevent TypeVar leakage.
  2026-01-06: Removed path scrubbing by string replacement; non-JSON diagnostics now use labels directly and never embed filesystem paths.
  2026-01-06: Optional<...> raw-string resolution now routes template vs concrete instantiation using has_typevar and ensure_variant_*.
  2026-01-06: Added driver regression test ensuring trust-store failures emit labels only (no filesystem paths) in JSON and stderr.
  2026-01-06: Adjusted no-path-leak test to detect absolute path patterns (regex) instead of banning all slashes.
  2026-01-06: apply_subst now routes variant/struct substitutions through template vs concrete instantiation based on deep has_typevar.
  2026-01-06: Updated package tests to use a non-reserved generic variant name (Maybe<T>) now that Optional is a builtin.
  2026-01-06: Updated e2e fixtures for module headers and micro-modules; added merge-module pattern for reexport tests and refreshed expectations for multi-file module errors.
  2026-01-06: Updated driver tests to include module headers for workspace parsing and shifted use-trait scope tests to module-scoped modules.
  2026-01-06: Fixed e2e fixtures by exporting m_a/m_b symbols, removing duplicate module headers in match fixtures, and adding explicit type args/annotations for Maybe ctor tests to reach match checks.
  2026-01-06: Updated qualified_ctor_dup_type_args_rejected expected.json to match new line/column after module header insertion.
  2026-01-06: Added missing semicolons to tuple-struct Point declarations in e2e fixtures to avoid parser-phase exits.
  2026-01-06: Standardized variant ctor fixtures to module main (variant_ctor_requires_expected_type_rejected, variant_optional_match_basic).
  2026-01-06: Removed unused current_file locals from driver tests to avoid path materialization.
  2026-01-06: Added tuple-struct semicolons in driver tests (abi boundary calls, method signature metadata) after tuple-struct terminator rule change.
  2026-01-06: Added missing tuple-struct semicolons across borrow/method/ufcs e2e fixtures to keep parser-phase clean.
  2026-01-06: Added module header and tuple-struct semicolon to borrow_nll_join_borrow_live_rejected fixture.
  2026-01-06: Added module headers to borrow_nll_* and borrow_struct_* e2e fixtures; removed duplicate origin_by_fn_id/trait_scope_by_module blocks in test_trait_method_resolution.
  2026-01-06: Added module header to borrow_prefix_field_overwrite_rejected and marked borrow_struct_field_param_mut_reborrow_rejected helper as nothrow to avoid throw-mode masking.
  2026-01-06: Standardized method_* e2e fixtures to module main; rewrote overload resolution test to use micro-modules + merge module; removed top-level stmt from grammar.
  2026-01-06: Simplified overload resolution driver test to a single-module overload case (module m exports two overloads) to avoid reexport ambiguity.
  2026-01-06: Updated grammar/spec docs to require tuple-struct semicolons and removed top-level stmt from grammar doc.
  2026-01-06: Clarified spec that expression statements are restricted to postfix forms (call/member/index/literal/name) to match parser.
  2026-01-06: Allowed top-level stray terminators in the parser grammar to match the grammar doc and reduce formatting-noise parse errors.
  2026-01-06: Standardized struct_ctor_keyword_args fixture to module main.
  2026-01-06: Added module headers and tuple-struct semicolons in borrow checker lambda capture tests to satisfy tuple-struct terminator rule.
  2026-01-06: Added module_paths to remaining driver workspace parse calls (trait_method_resolution, trait_diagnostic_goldens).
  2026-01-06: Removed legacy package type-link "optional" key handling now that Optional is a canonical variant.
  2026-01-06: Dropped unused Optional caches in LLVM codegen helper state.
  2026-01-06: Cleaned stale e2e build artifacts that still referenced DriftOptional types.
  2026-01-06: Fixed package type table decoding to always return DecodedTypeTable even without variant_schemas.
  2026-01-06: Package type-link now rejects non-builtin scalar types without module_id to avoid nominal key mismatch.
  2026-01-06: Package type linking now canonicalizes builtin u64/Uint64 and validates exception schema keys match event FQNs.
  2026-01-06: Package linking rejects non-lang.core packages that attempt to define lang.core nominals and enforces a core allowlist.
  2026-01-06: LLVM variant lowering now stores ordered arm lists with explicit arm-name lookup to keep deterministic switch ordering.
  2026-01-06: LLVM codegen only applies rename_map to same-module calls and doc now reflects bounded use of allocas.
  2026-01-06: Package linker now keys TYPEVAR by package+TypeId to avoid cross-package/unrelated generic unification.
  2026-01-06: Package variant schema decoding now validates base VARIANT TypeDef identity.
  2026-01-06: LLVM variant type emission now asserts payload alignment is a power of two.
  2026-01-06: Package linking now allows lang.core builtins and allowlisted core nominals from non-core packages (rejects everything else).
  2026-01-06: Package type linking now normalizes core nominals to package_id=lang.core and validates Optional schema against the canonical base.
  2026-01-06: Struct schema encoding now includes base_id and linker uses it (with typevar fallback) to avoid ambiguous generic struct matching.
  2026-01-06: Package type linking no longer infers module ownership from TypeDefs; scalar nominals now normalize lang.core package ids consistently.
  2026-01-06: Export wrapper lowering now coerces non-throwing Bool returns into ABI ok storage types.
  2026-01-06: Package type tables now encode TypeParamId for TYPEVAR and linker keys typevars by semantic owner+index when present.
  2026-01-06: Package type table decoding now rejects empty-string module_id values.
  2026-01-06: Updated LLVM wrapper test to expect Bool ok coercion into i8 ABI storage.
  2026-01-06: Package linker now rejects non-core lang.core TypeDefs/schemas and requires struct_schemas base_id/type_param_id for TYPEVAR.
  2026-01-06: Package linker now encodes/links struct instantiations and validates variant base param_types invariants; struct schema base_id is mandatory.
  2026-01-06: Fixed struct instantiation keying order, added instance/base identity guards, zero-initialized variant payloads, and marked variants non-bitcopy.
  2026-01-06: Struct schemas now carry field type expressions; linker defines struct schema fields and inlines array drop to avoid double-mapping LLVM values.
  2026-01-06: Package linker now allows Optional references from non-core packages while validating canonical schema; LLVM codegen now supports configurable float widths (f64 only at runtime).
  2026-01-06: Struct schema encoding now uses template field expressions; struct instance keys validated before nominal handling; float returns now honor float width.
  2026-01-06: Linker now populates struct instantiation cache when args are concrete, encodes all signatures, and enforces module-id ownership collisions across packages.
  2026-01-06: Array drop helper now uses fresh SSA names; struct schema package_id uses nominal provider; linker no longer infers module providers from schemas.
  2026-01-06: encode_signatures now emits all entries; Optional type exprs encode as lang.core; Float doc clarified as target-defined; StringFromFloat f32 now fpexts to f64.
  2026-01-06: Added LLVM test to verify nested array drop helper IR parses and verifies via llvmlite (void signature wired); restored FnResult ref err asserts to their original test.
  2026-01-06: Fixed encode_signatures early return, hardened nested array drop helper test assertions (cap=1, prefix matching), added encode_signatures determinism test, made TYPEVAR keys ignore display names with deterministic lowest-TypeId display selection (with regression test), added provided_nominals metadata + linker gating tests for lang.core references, and added variant-instantiation link regression using ensure_variant_instantiated.
  2026-01-06: Added module-id collision check across provided nominals, legacy Optional reference allowance without provided_nominals, encode_type_table package_id enforcement, and provided_nominals TypeDef validation with tests.
  2026-01-06: Documented workspace rule that module ids are globally unique across source and package modules.
  2026-01-06: Cached struct/variant template instantiations, enforced module_packages completeness for type keys, validated struct schema field-name order, restricted provided_nominals kinds, and tightened GenericTypeExpr decode with regression tests.
  2026-01-06: Linker now routes variant instantiations with TypeVar args through ensure_variant_template; added regression test.
  2026-01-06: has_typevar now inspects struct/variant instances, module-scoped scalar nominals are declared explicitly, and link regression tests cover both.
  2026-01-06: Linker now populates host.module_packages from provided_nominals and tests assert module ownership + type_key_string stability post-link.
  2026-01-06: Added struct-based module_packages population test to cover struct schema path.
  2026-01-06: Linker now seeds lang.core module ownership explicitly and has a regression test.
  2026-01-06: encode_type_table now requires module_packages entries for declared modules to avoid empty provided_nominals; added regression test.
  2026-01-06: provided_nominals is now required in payloads (legacy inference removed) with tests updated accordingly.
  2026-01-06: Added test asserting no provider inference occurs when provided_nominals is empty.
  2026-01-06: encode_type_table module_packages check now only enforces declared modules (not foreign imports), unblocking driver package emission.
