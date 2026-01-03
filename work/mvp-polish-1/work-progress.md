# MVP Polish 1 - Work Progress

Status legend: [todo], [in-progress], [done]

## 1) LLVM struct type caching can become unsound with multiple instantiations

Problem: `LlvmModuleBuilder.ensure_struct_type(...)` caches by `module::name`, which can collide across generic instantiations. `_type_key()` for STRUCT also ignores type args, colliding in `FnResult` naming.

Plan:
- [done] Add a stable, argument-sensitive type key string (in `TypeTable`) including package/module/name + type args + ref mutability + fn throwness.
- [done] Use this key for struct LLVM cache key, LLVM type name mangling, and `_type_key()` for STRUCT.
- [done] If `type_key_from_typeid(...)` exists, reuse/mangle/hash its canonical form. (Implemented a direct TypeTable key; LLVM uses a hash suffix.)
- [done] Stopgap if needed: cache struct LLVM types by TypeId and add stable hash suffix to the LLVM name. (Hash suffix added to LLVM struct type names.)

## 2) Struct constructor lowering drops type context

2a) No `expected_type` threaded into field expressions
- [done] In struct ctor lowering, pass `expected_type=field_types[idx]` for positional args.
- [done] For keyword args, pass `expected_type=field_types[field_idx]`.

2b) Constructed struct temp not recorded in `_local_types`
- [done] After `ConstructStruct`, set `self._local_types[dest] = struct_ty`.

## 3) `expr_types` consumption policy inconsistent / under-specified

3a) `_infer_expr_type` consults `expr_types` unconditionally
- [done] Define explicit modes: typed_strict vs typed_recover.
- [done] Gate `expr_types` usage on mode and assert invariants.
- [done] Update stage2 doc comment (currently claims it doesn’t consume `expr_types`).

3b) Ignoring `Unknown` masks checker bugs in typed_strict
- [done] In typed_strict, treat `Unknown` as internal error instead of silent fallback.

3c) Typed mode selection should be data-driven
- [done] Choose typed mode per function based on typecheck success + non-Unknown expr_types (strict when clean; recover otherwise) to avoid false ICEs in tests.

3d) Typed mode completeness criteria still unclear
- [done] Define a concrete “strict” criterion (typecheck succeeded + no Unknown expr types) and align implementation + docs.

## 4) Generic instantiation detection must block codegen deterministically

- [done] Confirm diagnostics hard-stop before MIR→SSA→LLVM when unresolved typevars remain.
- [done] Add an explicit gate (fail-fast) when `type_diags` exist.

## Optional coverage gap

- [done] Add a codegen e2e case with two distinct instantiations of the same generic struct in one module to catch LLVM struct caching collisions. (Added `lang2/codegen/tests/e2e/generic_struct_two_instantiations_same_module/` with ternary usage, since `if` is statement-only.)

## Follow-up risks

- [done] type_key_string recursion fallback uses TypeId; replaced with deterministic nominal/stack-based marker to keep IR stable across runs.
- [done] type_key_string now qualifies SCALAR when module/package is present (avoid collisions for module-scoped scalars).
- [done] Updated LLVM struct cache docstring to reflect type_key-based caching and hashed LLVM type names.
- [done] _type_key now qualifies module-scoped SCALAR and uses stable keys for VARIANT instead of TypeId.
- [done] typed strict selection treats warning-only diagnostics as ok (only errors disable strict).
- [done] LLVM variant types now use stable, hashed type keys instead of TypeId for naming/caching.
