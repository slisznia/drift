# Proposal: std.runtime.GlobalRegistry / ThreadLocalRegistry

## Status
Proposal (non-normative). Intended to guide stdlib design and compiler hooks.

## Summary
`std.runtime.GlobalRegistry` is a process-global, type-indexed storage facility
for long-lived values. It covers common "global state" needs without language
globals. The registry is thread-safe for lookup. It is **set-once / store-forever**:
values are inserted at most once per type and never replaced or removed.

`std.runtime.ThreadLocalRegistry` mirrors the same API but stores values per
thread rather than process-wide.

The global registry is a runtime-provided singleton available before user
`main` executes; implementations may initialize it lazily on first access.

## Goals
- Provide a single, well-defined place for long-lived shared state.
- Avoid language-level globals while preserving usability and testability.
- Keep the API type-safe via type-indexed access.
- Enforce lifetime safety: values stored long-term must not borrow from
  shorter-lived data.
- Be thread-safe for lookup without imposing per-entry mutability.

## Non-goals
- Implicit global mutable variables.
- Dynamic string-keyed registries by default.
- Replace/take semantics (no invalidation of shared references).

## Core API (sketch)

```drift
module std.runtime

struct GlobalRegistry
struct ThreadLocalRegistry

// The global registry instance (process-wide).
fn global_registry() returns &GlobalRegistry

// The thread-local registry instance (per-thread).
fn thread_local() returns &ThreadLocalRegistry

// Convenience forwarders for the global registry.
fn get<T: Unborrowed + Send + Sync>() returns Optional<&T>
fn set<T: Unborrowed + Send + Sync>(value: T) returns Optional<&T>
fn contains<T: Unborrowed + Send + Sync>() returns Bool
// Traps if missing (does not throw).
fn expect<T: Unborrowed + Send + Sync>(msg: String) returns &T

// Convenience I/O wrappers (trap if the console is not registered).
fn print(msg: String) returns Void
fn println(msg: String) returns Void
fn eprint(msg: String) returns Void
fn eprintln(msg: String) returns Void

implement GlobalRegistry {
    // Inserts `value` if no value for `T` exists. Returns the existing value
    // when present.
    fn set<T: Unborrowed + Send + Sync>(value: T) returns Optional<&T>

    // Returns a shared reference to the stored value, if present.
    fn get<T: Unborrowed + Send + Sync>() returns Optional<&T>

    // Convenience: whether a value for `T` exists.
    fn contains<T: Unborrowed + Send + Sync>() returns Bool

    // Convenience: returns the value or traps with `msg`.
    fn expect<T: Unborrowed + Send + Sync>(msg: String) returns &T
}

implement ThreadLocalRegistry {
    // Same semantics as GlobalRegistry, but per-thread.
    fn set<T: Unborrowed>(value: T) returns Optional<&T>
    fn get<T: Unborrowed>() returns Optional<&T>
    fn contains<T: Unborrowed>() returns Bool
    fn expect<T: Unborrowed>(msg: String) returns &T
}
```

Notes:
- `Unborrowed` guarantees the value does not depend on borrowed views.
- Global registry operations require `Send + Sync` because values may be
  initialized on one thread and accessed on another.
- `get` returns `&T` (not `&mut T`). For mutable global state, store
  `Mutex<T>`, `RwLock<T>`, or an atomic type.
- `expect` traps if the value is missing; it is a non-throwing helper for
  required dependencies (e.g., stdout).

## Semantics and invariants
- **Type-keyed:** The registry is keyed by canonical type identity including
  package identity and alias expansion. There is at most one stored value per
  type `T`.
- **Set-once:** `set` succeeds only if no value exists for `T`.
- **Store-forever:** Values are never replaced or removed; references are stable
  for the life of the process or thread.
- **No implicit mutation:** The registry does not grant mutable access to stored
  values. If mutation is needed, the stored value must provide it explicitly.

## Thread safety
- Global registry lookups are thread-safe.
- The registry does not enforce safe mutation of stored values; instead it
  enforces `Send + Sync` and relies on explicit synchronization inside `T`.
- Thread-local registry values are visible only to the owning thread; `Send`/
  `Sync` are not required there.

## Examples

Global config (immutable):

```drift
struct AppConfig { port: Int, mode: String }

fn init(cfg: AppConfig) returns Void {
    std.runtime.set<AppConfig>(cfg);
}

fn port() returns Int {
    return std.runtime.get<AppConfig>()?.port ?? 0;
}
```

Global counter (mutable):

```drift
fn init_counter() returns Void {
    std.runtime.set<Mutex<Int>>(Mutex.new(0));
}

fn bump() returns Int {
    val m = std.runtime.get<Mutex<Int>>()?;
    return m.lock(|n| { *n = *n + 1; *n });
}
```

Multiple values per type (store a container):

```drift
fn init_cache() returns Void {
    std.runtime.set<Map<String, Int>>(Map.new());
}
```

Thread-local scratch:

```drift
fn init_tls() returns Void {
    std.runtime.thread_local().set<Array<Int>>(Array.new());
}
```

Console helper (global registry):

```drift
import std.runtime as rt;

fn main() nothrow returns Int {
    rt.println("hello");
    return 0;
}
```
