# keep pointers out of the language surface

**Policy**

* No `*mut T`, `*const T` tokens in the language.
* No user-visible pointer arithmetic or casting.
* All low-level bytes live behind sealed, `@unsafe` stdlib internals.

---

# how we still get “placement new” without pointers

## 1) Opaque slots, not pointers
 
Introduce an internal, opaque handle:

* `Slot<T>` — a single uninitialized location for a `T`.
* `Uninit<T>` — marker wrapper for “not constructed yet”.

Userland never sees addresses; they see handles.

**Core ops (exposed only via controlled APIs):**

* `slot.write(value: T)` — constructs `T` in place.
* `slot.emplace(args…)` — constructs with ctor args.
* `slot.assume_init() -> &mut T` — `@unsafe`, returns a normal reference once you promise it’s live.

No `*mut T` anywhere.

## 2) Array growth via a builder guard

Provide a safe guard that manages spare capacity:

```drift
var xs = Array<Line>()
xs.reserve(100)

var b = xs.begin_uninit(3)   // returns UninitBuilder<Line>
b.emplace(/* args for element 0 */)
b.emplace(/* args for element 1 */)
b.emplace(/* args for element 2 */)
b.finish()                   // commits len += 3; auto-rollback on drop if not finished
```

* `UninitBuilder<T>` exposes only `emplace(...)`, `write(value)`, `len_built()`, `finish()`.
* If it drops without `finish()`, it destroys any partially built elements and **does not** change `Array.len`.
* Zero pointers exposed; capacity math and placement are internal.

## 3) RawBuffer without pointers

`RawBuffer<T>` remains the internal workhorse, but its public surface uses indices and opaque slots:

* `buf.capacity() -> Int`
* `buf.slot_at(i: Int) -> Slot<T> @unsafe` (still gated; not for average code)
* `buf.reallocate(new_cap: Int) @unsafe`

`Array<T>` uses this internally; typical code never touches `RawBuffer`.

---

# FFI without pointers

All interop stays in `lang.abi`. No `*mut T` tokens—only opaque handles:

* `abi.CPtr<T>` / `abi.MutCPtr<T>` — opaque pointer types; you can pass/receive them, not dereference them.
* `abi.Slice<T>` / `abi.MutSlice<T>` — lower to `(ptr,len)` at the ABI, but in Drift they’re safe views (read-only / read-write) with range-checked indexing.
* `extern "C" struct S { … }` — C layout.
* `extern "C" fn f(args…) returns R` — C call. Signatures accept `abi.MutSlice<U8>`, `abi.CPtr<S>`, etc.

Only `lang.abi` can construct `CPtr`/`MutCPtr` from real addresses; user code cannot conjure pointers.

---

# references and mutability (no pointers needed)

We already have:

* `val` / `var` bindings for immutability.
* `ref T` for pass-by-reference (borrow), which is bounds-checked and lifetime-checked by the compiler, not by addresses.

All container APIs use `ref` and slices—never raw addresses.

---

# where “unsafe” lives

Create a dedicated module `lang.internals` (or `lang.unsafe`) that is:

* import-gated (`import lang.internals as _`),
* feature-gated (compiler flag), and
* required to use any API that manipulates `Slot<T>`, `RawBuffer<T>`, or unchecked length changes.

Average programs never import it; stdlib and advanced libs do.

---

# examples without pointers

## grow + placement (safe)

```drift
var ar = Array<UserType>.with_capacity(10)

var u = UserType(/* … */)

// simple path
ar.push(u)

// batch path (placement without pointers)
var b = ar.begin_uninit(1)
b.write(u)    // copies/moves into next spare slot
b.finish()
```

## FFI call (no pointers shown)

```drift
import lang.abi as abi

extern "C" struct Point { x: Int32, y: Int32 }
extern "C" fn draw(points: abi.Slice<Point>) returns Int32

fn render(points: Array<Point>) returns Int32 {
	return draw(points.as_slice())
}
```

---

# compiler lowering (for us, not users)

* The compiler lowers `begin_uninit`/`write`/`finish` to `construct_at` and length bumps.
* Stack locals lower to hidden stack slots + `construct_at`/`destroy_at`.
* `lang.abi` lowers `Slice<T>`/`CPtr<T>` to raw pointers at the ABI boundary.

Users never see the pointer syntax or arithmetic; abuse is off the table.

---

# tl;dr

* No raw pointer syntax in Drift.
* Expose **handles** (`Slot<T>`, builders, slices) and **guards**, not addresses.
* Keep FFI behind `lang.abi` with opaque pointer types.
* Keep true raw ops sealed in `lang.internals` and `@unsafe`.
* You still get full placement-new semantics and zero-cost interop, without opening the foot-gun.
