# Drift Module Merge & Artifact Generation (Design/Spec Hybrid)

## Goals

- Allow a single module to be defined across multiple source files.
- Provide a **merge phase** that validates module-level coherence across files:
  - No duplicate public exports (types, functions, interfaces, methods) within a module.
  - No collisions between free functions and methods of the same module/key.
  - Clear diagnostics when collisions occur.
- Support two driver outcomes:
  1. **Executable**: exactly one `main` function across all input files (in any module) is required.
  2. **Signed Drift Module (package)**: produce a module artifact after validation, suitable for reuse/import.
- Keep per-file parsing simple; merging is a distinct phase in the driver.

## Scope

- **In-scope**:
  - Merging and validating declarations across multiple files that declare the same module.
  - Defining keys for duplicate detection (free functions, methods, types/interfaces, etc.).
  - CLI mode that builds either an executable or a module artifact and enforces `main` rules for executables.
- **Out-of-scope (for now)**:
  - Full package manager semantics, versioning, or dependency resolution.
  - Incremental recompilation optimizations.

## Terminology

- **Module**: logical namespace identified by its module path (e.g., `foo`, `foo.bar`). Multiple source files may contribute to the same module.
- **Export**: a public item (type, function, interface, method) that the module exposes.
- **Artifact**: the merged, validated output. Can be an executable or a signed module.

## Merge Phase Responsibilities

Given a set of parsed source files (each with HIR + signatures + module id):

1. **Group by module path**:
   - Collect all declarations (types, free functions, methods, interfaces, exceptions) per module path.

2. **Duplicate detection**:
   - **Free functions**: key by `(module, name)`. Colliding definitions → diagnostic.
   - **Methods**: key by `(module, impl_target_type_id, method_name)`. Colliding definitions for the same type/name → diagnostic. Methods on different types may share names.
   - **Types/Structs/Interfaces/Exceptions**: key by `(module, name)`. Colliding definitions → diagnostic.
   - **Free vs method collisions**: within a module, a name cannot be both a free function and a method (any type). Emit diagnostic if both exist.

3. **Export consistency (public API)**:
   - If you track visibility, ensure public exports are unique under their keys. If visibility is not yet implemented, treat all as exported and still apply the uniqueness rules.

4. **Main function check (executable mode)**:
   - When building an executable, require **exactly one** `main` function across all modules/files. Diagnostic if zero or more than one.
   - `main` can live in any module; specify resolution priority if multiple modules define `main` (currently: uniqueness required, no priority).

5. **Method/Impl metadata integrity**:
   - Ensure every method has `impl_target_type_id` and `self_mode` populated; missing metadata → diagnostic, skip registration.
   - Ensure impl targets are nominal (reject `implement &T` in v1) and resolved to concrete `TypeId`s.

6. **Artifact assembly**:
   - If **executable**: proceed to type check/borrow check/codegen after successful merge; include only the merged, validated declarations; enforce the single `main` requirement.
   - If **signed module**: produce a module artifact containing the merged HIR/signatures/exports; sign/validate as per toolchain; no `main` required.

## Keys and Collision Rules (v1)

- **Module identity**: the `module` declaration at the top of a file (default `main` if absent) defines the module path. Used to group declarations.
- **Free functions**: `(module, name)` must be unique.
- **Methods**: `(module, impl_target_type_id, method_name)` must be unique. Method names may repeat across different impl targets. Methods do **not** create free-function aliases.
- **Free vs method**: a given `name` in a module may not be both a free function and any method name (on any type) in that module.
- **Types/Interfaces/Exceptions**: `(module, name)` must be unique.

## Driver Modes

- **Executable mode** (default):
  - Input: multiple Drift files.
  - Merge per module; validate uniqueness as above.
  - Require exactly one `main` function globally.
  - On success: type check → borrow check → lower/codegen → link executable.

- **Module/package mode** (`--emit-module` or similar):
  - Input: multiple Drift files.
  - Merge per module; validate uniqueness as above.
  - No `main` requirement.
  - On success: emit a signed module artifact containing the merged HIR/signatures/public API.

## Diagnostics

- Duplicate free function: `function 'foo' already defined in module 'm' (previous at ...).`
- Duplicate method: `method 'm' for type 'T' already defined in module 'm'.`
- Free vs method collision: `name 'foo' used for both free function and method in module 'm'.`
- Missing receiver metadata: `method 'm' missing receiver type/mode.`
- Multiple/zero mains in executable mode.

## Implementation Notes

- Keep per-file parsing simple; enrich declarations with `module` and method metadata (already present in `FnSignature`).
- Add a merge/validation step in the driver that aggregates decls per module and applies the collision rules.
- Extend the registry to be populated from the merged view (so functions/methods from all files in a module are registered once).
- For now, use stringified type expr as impl target keys during merge; when TypeIds are available earlier, switch to TypeId keys to avoid aliasing issues.

## Future Work (out of v1 scope)

- Visibility (`pub`, `pub(crate)`, etc.) and export sets per module.
- Generic impls/methods and their instantiation in the registry.
- Package versioning and dependency resolution.
- Incremental/reuse of compiled modules across builds.
