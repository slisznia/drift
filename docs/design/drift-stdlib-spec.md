# Drift Standard Library Spec (Draft)

## Scope
This document specifies the MVP surface for standard library modules used by the
compiler and core tooling. It is the source of truth for iterator traits,
collections, algorithms, and error events referenced by language lowering.

## Modules
- `std.iter`: iterator traits and `for` lowering hooks.
- `std.containers`: core container types.
- `std.algo`: algorithms (functions only).
- `std.core.cmp`: comparison traits and operator lowering paths.
- `std.err`: standard error/exception events used by stdlib APIs.

## std.iter

### Iterable
```drift
module std.iter

trait Iterable<Src, Item, Iter> {
	fn iter(src: Src) returns Iter
	require Iter is SinglePassIterator<Item>
}
```

Resolution:
- `std.iter.Iterable.iter(expr)` is trait dispatch (UFCS), not a static function lookup.
- Coherence: for any concrete `Src`, at most one applicable `Iterable<Src, Item, Iter>` impl may exist.

### Iterators
```drift
trait SinglePassIterator<T> {
	fn next(self: &mut Self) returns Optional<T>
}

trait MultiPassIterator<T> require Self is SinglePassIterator<T> {
	require Self is Copy
}

trait BidirectionalIterator<T> require Self is MultiPassIterator<T> {
	fn prev(self: &mut Self) returns Optional<T>
}

trait RandomAccessReadable<T> {
	fn len(self: &Self) returns Int
	fn compare_at(self: &Self, i: Int, j: Int) returns Int
}

trait RandomAccessPermutable<T> require Self is RandomAccessReadable<T> {
	fn swap(self: &mut Self, i: Int, j: Int) returns Void
}
```

Contracts:
- MultiPass independence: copying a MultiPassIterator yields an independent cursor.
  Advancing one copy must not affect the other.
- Bounds: if `i < 0` or `j < 0`, raise `std.err:IndexError`. Otherwise require
  `i < len` and `j < len`; out-of-range raises `IndexError`.
- Invalidation: any method (`len`, `compare_at`, `swap`) on an invalidated
  iterator/range raises `std.err:IteratorInvalidated(container_id, op_id)`.
- Stability: `len()` is stable for the duration of any `std.algo` operation on `&Self` / `&mut Self`.

### `for` lowering
Pinned lowering shape (fully-qualified, no shadowing):

```drift
val __src = expr
var __it = std.iter.Iterable.iter(__src)

loop {
	val __opt = std.iter.SinglePassIterator.next(&mut __it)
	match __opt {
		None => break
		Some(x) => { body }
	}
}
```

Rules:
- `expr` is evaluated exactly once.
- `Iterable.iter` is called exactly once.
- `SinglePassIterator.next` drives the loop.
- If `Iterable.iter` is missing: error category "type is not iterable".
- If `iter()` returns a type not implementing `SinglePassIterator`: error
  category "iter() result is not an iterator".

## std.containers

Pinned MVP container set:
- `Array<T>`
- `HashMap<K, V>`
- `TreeMap<K, V>`
- `HashSet<T>`
- `TreeSet<T>`
- `List<T>`
- `Queue<T>`
- `Deque<T>`

Array API (MVP):
- Indexing:
  - `arr[i]` returns `T` (throws `IndexError` on OOB; only allowed for Copy elements).
  - `arr.get(i) -> Optional<&T>` returns `None` on OOB.
- Mutation:
  - `push(value: T) -> Void` appends to the tail.
  - `pop() -> Optional<T>` removes and returns the tail element.
  - `insert(index: Int, value: T) -> Void` inserts at `index` (shifts right).
  - `remove(index: Int) -> T` removes and returns element at `index` (shifts left).
  - `swap_remove(index: Int) -> T` removes element at `index` by swapping with tail (order not preserved).
  - `set(index: Int, value: T) -> Void` overwrites element at `index`.
  - `clear() -> Void` drops all elements (capacity unchanged).
  - `reserve(additional: Int) -> Void` ensures capacity for `len + additional`.
  - `shrink_to_fit() -> Void` reduces capacity to `len`.
- Length/capacity:
  - `len` and `cap` return `Int` and are never negative.

Pinned iterator capability matrix (per iter form):

- Array:
  - `iter(self: T)`: SinglePass
  - `iter(self: &T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &mut T)`: deferred (not implemented; borrow-safety enforcement pending)
- List:
  - `iter(self: T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &mut T)`: SinglePass
- Deque (no RandomAccess* in MVP):
  - `iter(self: T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &mut T)`: SinglePass
- Queue:
  - `iter(self: T)`: SinglePass
  - `iter(self: &T)`: SinglePass
  - `iter(self: &mut T)`: SinglePass
- TreeMap/TreeSet (in-order):
  - `iter(self: T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &T)`: SinglePass, MultiPass, Bidirectional
  - `iter(self: &mut T)`: SinglePass
- HashMap/HashSet:
  - `iter(self: T)`: SinglePass
  - `iter(self: &T)`: SinglePass
  - `iter(self: &mut T)`: SinglePass

Structural mutation (MVP):
- Any operation that can change length or internal shape is a structural mutation.
- All methods that mutate container contents are treated as structural in MVP and
  invalidate existing iterators.

## std.core.cmp

### Comparison traits
```drift
module std.core.cmp

trait Equatable {
	fn eq(self: &Self, other: &Self) returns Bool
}

trait Comparable require Self is Equatable {
	fn cmp(self: &Self, other: &Self) returns Int
}
```

Rules:
- `Comparable` implies `Equatable` for the same type.
- `compare_at` must reflect `T is Comparable` ordering.
- Ordering law: `compare_at` must satisfy sign symmetry + transitivity + totality:
  - `cmp(i,j) == 0` iff `cmp(j,i) == 0`
  - `cmp(i,j) < 0` iff `cmp(j,i) > 0`
  - transitive and total (no unordered cases in MVP)

## std.algo

### Algorithms (signatures deferred)
Algorithm signatures are defined when implemented. Capability requirements are
tracked below for MVP:

| Algorithm | Capability requirement |
| --- | --- |
| `for_each` | `SinglePassIterator<T>` |
| `find` | `SinglePassIterator<T>` |
| `any` | `SinglePassIterator<T>` |
| `all` | `SinglePassIterator<T>` |
| `count` | `SinglePassIterator<T>` |
| `fold` | `SinglePassIterator<T>` |
| `min` / `max` | `SinglePassIterator<T>` + `T is Comparable` |
| `equal` | `SinglePassIterator<T>` + `T is Equatable` (consumes both) |
| `sort_in_place` | `RandomAccessPermutable<T>` + `T is Comparable` |
| `binary_search` | `BinarySearchable<T>` + `T is Comparable` (key passed by `&T`) |

### Algorithm-specific capability traits
```drift
module std.algo

trait BinarySearchable<T> require Self is std.iter.RandomAccessReadable<T> {
	fn compare_key(self: &Self, i: Int, key: &T) returns Int
}
```

Contracts:
- Bounds/invalidation rules:
- if `i < 0` -> `std.err:IndexError(container_id, i)`
  - else require `i < len()` -> otherwise `IndexError`
- invalidated -> `std.err:IteratorInvalidated(container_id, IteratorOpId::CompareKey)`
- `compare_key` must be coherent with `compare_at`/`Comparable` ordering.

## std.runtime

`std.runtime` provides registry-backed, long-lived shared state without language
globals. It defines a process-wide global registry and a per-thread registry.

Core API sketch:

```drift
module std.runtime

struct GlobalRegistry
struct ThreadLocalRegistry

fn global_registry() -> &GlobalRegistry
fn thread_local() -> &ThreadLocalRegistry

fn get<T: Unborrowed + Send + Sync>() -> Optional<&T>
fn set<T: Unborrowed + Send + Sync>(value: T) -> Optional<&T>
fn contains<T: Unborrowed + Send + Sync>() -> Bool
fn expect<T: Unborrowed + Send + Sync>(msg: String) -> &T

implement GlobalRegistry {
	fn set<T: Unborrowed + Send + Sync>(value: T) -> Optional<&T>
	fn get<T: Unborrowed + Send + Sync>() -> Optional<&T>
	fn contains<T: Unborrowed + Send + Sync>() -> Bool
	fn expect<T: Unborrowed + Send + Sync>(msg: String) -> &T
}

implement ThreadLocalRegistry {
	fn set<T: Unborrowed>(value: T) -> Optional<&T>
	fn get<T: Unborrowed>() -> Optional<&T>
	fn contains<T: Unborrowed>() -> Bool
	fn expect<T: Unborrowed>(msg: String) -> &T
}
```

Semantics and invariants:
- Type-keyed by canonical type identity (package + module + name + args).
- Set-once / store-forever: values are inserted at most once and never removed.
- `GlobalRegistry` lookups are thread-safe; values require `Send + Sync`.
- `ThreadLocalRegistry` is per-thread; no `Send`/`Sync` required.
- Registries return shared references only; mutable state must be explicit in `T`.

## std.err

Standard exception events used by stdlib:
- `IndexError(container_id: String, index: Int)`
- `IteratorInvalidated(container_id: String, op_id: IteratorOpId)`

Iterator op ids:
- `IteratorOpId::Next`
- `IteratorOpId::Prev`
- `IteratorOpId::Len`
- `IteratorOpId::CompareAt`
- `IteratorOpId::Swap`
- `IteratorOpId::CompareKey`

Notes:
- `container_id` is the base nominal key (package + module + name) with no type arguments.
- `IndexError` is raised per the RandomAccess bounds rule (negative -> error; otherwise `i < len`).
- IteratorOpId numeric tags are ABI-stable; values are append-only (no reordering).
