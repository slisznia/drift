# Drift tooling, build, and package ecosystem – hybrid specification

This document describes the **Drift toolchain surface** and the machinery behind it:
- project and target configuration
- builds and outputs
- package acquisition, caching, and vendoring
- repositories and discovery (including `drift-sources.json`)
- trust model defaults (TOFU + reserved namespaces)

It is intentionally *hybrid*: part specification, part operational contract.

---

## 1. Goals and non-goals

### Goals
- Deterministic builds
- **Zero implicit network access during compilation**
- Clear separation between *building* and *dependency acquisition*
- Minimal overhead for “hello world”
- Natural scaling to multi-package, multi-binary repositories
- Eliminate “publish before use” friction for **local** packages
- Community-scale discovery without requiring a single central storage service

### Non-goals
- IDE behavior specification
- Test runners or execution environments
- Runtime deployment conventions
- Rich visibility lattice (`pub(crate)` etc.)

---

## 2. Tools and responsibilities

### 2.1 `driftc` (compiler / builder)

`driftc` is responsible for:
- Loading project and target configuration
- Discovering targets
- Resolving modules from **local package roots only**
- Verifying package integrity (hashes) and, when present, package signatures and trust policy **before** using any package contents (**gatekeeper**)
- Compiling sources
- Producing final artifacts (executables or package artifacts)

**Hard rule:** `driftc` never performs network I/O.

**Gatekeeper rule:** `driftc` is the final authority on whether a package is trusted for use.
Even if `drift` verified a package at download time, `driftc` must re-check trust at use time because
trust can change over time (e.g., key rotation, revocation lists, or namespace policy updates).

`driftc` is a verifier/consumer only: it never signs packages, never publishes packages, and never compresses artifacts for distribution.

**Implementation status:** package containers are hash-verified today; signature verification is planned but not implemented yet.

### 2.2 `drift` (package manager / ecosystem tool)

`drift` is responsible for:
- Fetching packages from remote **repositories** (HTTP/S3/etc.)
- Managing a **project-local** dependency cache
- Optionally verifying signatures at download time (early rejection; `driftc` still verifies at use time)
- Resolving dependency graphs and versions
- Writing/updating the lockfile
- Producing vendor snapshots for CI/offline use
- Repository discovery configuration (`drift-sources.json`)
- Publisher tooling: building and signing repository indexes

---

## 3. Repository layout (typical)

```
repo/
  drift-project.json
  drift-project.lock.json

  packages/
    core/
      drift-target.json
      src/

    net/
      drift-target.json
      src/

  apps/
    cli/
      drift-target.json
      src/

  build/
    drift/

  cache/
    driftpm/

  vendor/
    driftpkgs/
```

Notes:
- `build/` contains build outputs only (safe to delete).
- `cache/` contains downloaded dependencies for this project (safe to delete; will re-download).
- `vendor/` is an optional snapshot for CI/offline/shipping scenarios.

---

## 4. Project file (`drift-project.json`)

The project file defines **policy and dependency universe**, not build units.

It includes:
- Project identity and version (**epoch label only**; not used for compatibility)
- Dependency catalog (keys → packages + constraints + repository)
- Repository definitions
- Trust policy
- Default target

Example:

```json
{
  "format": 1,
  "project": { "name": "example", "version": "1.0.0" },

  "repositories": {
    "toolchain": { "type": "toolchain" },
    "default": { "type": "http", "url": "https://packages.example.com/drift" }
  },

  "deps": {
    "std":  { "package": "std",       "version": "^0.3", "repository": "toolchain" },
    "http": { "package": "acme.http", "version": "^1.4", "repository": "default" }
  },

  "trust": {
    "require_signed": true
  },

  "default_target": "cli"
}
```

Terminology: this spec uses **repository** (not registry).

---

## 5. Target files (`drift-target.json`)

Each directory containing `drift-target.json` declares itself as a build target.

The filename is a **marker**, not an identifier.

### 5.1 Common fields
- `name` – unique target name
- `kind` – `"package"` or `"exec"`
- `version` – semantic version (packages only; used for compatibility)
- `uses` – dependency keys from project file (no URLs/versions here)
- `depends_on` – other local targets (typically packages)

### Package target example
```json
{
  "format": 1,
  "kind": "package",
  "name": "core",
  "version": "0.9.0",
  "modules": ["example.core"],
  "uses": ["std"]
}
```

### Executable target example
```json
{
  "format": 1,
  "kind": "exec",
  "name": "cli",
  "entry": "example.cli.main",
  "uses": ["std"],
  "depends_on": ["core"]
}
```

---

## 6. Target discovery

Targets are discovered by:
- Recursively scanning the project directory
- Any directory containing `drift-target.json` is a target

Excluded directories:
- `build/`
- `cache/`
- `vendor/`
- `.git/`

Target names must be unique within a project.

---

## 7. Dependency resolution model

### 7.1 External dependencies (downloaded)
- Defined in `drift-project.json` under `deps`
- Resolved by `drift`
- Downloaded into **project-local** cache:
  - `cache/driftpm/`

### 7.2 Internal dependencies (local packages)
- Expressed via `depends_on`
- Built automatically by `driftc` in dependency order
- Published locally into:
  - `build/drift/localpkgs/`

Internal packages are immediately available for downstream targets **in the same build invocation**.
This removes the Maven-style “publish before use” pain.

---

## 8. Package roots during build

Effective package root order during a build (conceptual; exact defaults are a tool UX decision):
- localpkgs (`build/drift/localpkgs/`)
- vendor snapshot (`vendor/driftpkgs/`)
- cache (`cache/driftpm/`)
- explicit roots passed on the command line

**Policy:**
- Packages placed in localpkgs may be unsigned (developer-produced).
- Packages sourced from vendor/cache are expected to be signed.
- The compiler must verify trust at use time; trust can change after download.

**Offline rule:** `driftc` verification is fully offline. It relies only on local package bytes, local sidecar signatures (`.dmp.sig`), and local trust configuration (toolchain/project/user trust roots). No network access is required.

**Per-root signature requirement:** signature requirements are a policy decision scoped to package roots. A typical (recommended) policy is:
- `build/drift/localpkgs/`: unsigned allowed (local build outputs)
- `vendor/` and `cache/`: signature required (downloaded or vendored dependencies)

This avoids a culture of “ignore signature” flags in normal development while keeping `driftc` as the final gatekeeper.

CLI flags are driver UX only:
- `-M` / `--module-path <dir>` (repeatable): source module roots
- `--package-root <dir>` (repeatable): package roots

---

## 9. Packages are distribution containers

**Packages are distribution containers.** A single package artifact (e.g., a signed DMIR/DMP) may contain **many modules**.
Each contained module retains its own canonical **module id** (e.g., `std.io`, `std.net`, `std.fmt`) and exports an interface independently.
Imports always target modules by module id; packages only determine **where** module contents and interfaces are sourced from (source roots vs package roots).

Example: the Drift standard library is distributed as one package containing multiple modules under the `std.*` module-id prefix.

---

## 20. Signed modules and DMIR

This section defines the trust boundary at the package level.

**Container format note:** DMIR-PKG v0 containers are stored uncompressed. Compression, if used, is applied as an outer transport layer (Zstandard recommended) and is not part of the container format nor the signed payload.

### 20.1 Signature sidecar (`.dmp.sig`)

Local build artifacts produced inside a project (e.g. `build/drift/localpkgs/*.dmp`) may be unsigned.
Distributed packages are expected to be signed.

Signatures are stored as a **sidecar JSON file** next to the package container:

- Package container: `pkg.dmp`
- Signature sidecar: `pkg.dmp.sig`

The sidecar is a JSON object that may contain **multiple signatures** (to support multiple keys, rotations, and different trust roots).
The sidecar records:

- signature algorithm identifier
- key identifier (or key metadata)
- signature bytes
- optional metadata needed for verification (e.g. certificate chain references, timestamps)

Compression (e.g. `pkg.dmp.zst`) is an outer transport concern; signatures cover the canonical **uncompressed** `pkg.dmp` bytes.

Signature generation is performed by `drift` (or `drift sign`), not by `driftc`.

At minimum, signatures cover:
- package metadata (manifest)
- module interfaces
- module payload IR blobs (DMIR)

The compiler verifies signatures and trust policy before using any package contents.

**Implementation status:** signature verification is planned but not implemented yet; integrity verification (hashes) is enforced.

---

## 23. Native components: threat model and trust boundary

Native components (C shims) may be required by some packages.

**Threat model and trust boundary**
- Drift signatures guarantee authenticity of:
  - Drift IR (DMIR)
  - package metadata
  - native shim *source* and build recipe
- Native shims are compiled locally; compiled objects are **not signed**
- Trust therefore extends to:
  - the local compiler toolchain
  - the operating system
  - system libraries linked at build time
- This is intentional and unavoidable for native interop.
- Drift does **not** attempt to secure or replace OS-level trust.
