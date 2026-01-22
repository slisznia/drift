# Work Progress

Next work we will do:

Containers

- Deque (done, ring buffer on RawBuffer)
- Array (builtin for MVP; stdlib migration deferred post-MVP)
- Potential next: HashMap before TreeMap (mentioned as a future pick after Deque)
- HashMap plan (pinned):
  - Add std.core.hash with Hasher/Hash/BuildHasher/DefaultHasher/DefaultBuildHasher.
  - Hasher is primitive-only (write_u64/write_i64/write_bool + finish).
  - Hash for String iterates codepoints and feeds write_u64 (+ length delimiter).
  - HashMap<K, V, B> where B is BuildHasher (store builder, not hasher).
  - hash_map_new/with_capacity use DefaultBuildHasher; with_builder for custom.
  - Implement iter + gen invalidation (IteratorInvalidated on mutation).
  - Tests: basic ops, collisions (bad hasher), resize/rehash, iterator invalidation.
  - Implemented (2026-01-21):
    - Added std.core.hash (Hasher/Hash/BuildHasher/DefaultHasher/DefaultBuildHasher, Uint64 hash output).
    - Added string_byte_at intrinsic + String.bytes() iterator; Hash for String uses byte iteration.
    - Added HashMap/HashSet (BuildHasher stored, linear probing, gen invalidation).
    - Compiler/LLVM pipeline updates for string_byte_at + Byte result.
    - std.core.cmp/copy updated for Bool/Byte/Uint64/String equality/copy.
    - stdlib exports updated; fixed-width types allowed in std.* for Uint64.
    - Tests: stdlib exports + HashMap smoke (Int/String).
  - Remaining: collision/resize/iterator-invalidation tests; broader validation runs.
  - Status: all tests passing after recent fixes (2026-01-21).
  - Status (2026-01-21): Hash is now generic over Hasher (Hash<H>), String hash updated, UFCS trait resolution supports trait type args.
  - Status (2026-01-21): HASH_PRIME is Uint64 to avoid 32-bit overflow; _mix uses it directly.
  - Status (2026-01-21): Hasher adds write_u8; String.hash uses write_u8; added e2e string hash regression case.
  - Status (2026-01-21): Parser consts accept Uint64 literal; MIR lowering emits ConstUint64.
  - Status (2026-01-21): Hash impls specialized to DefaultHasher (trait stays generic); hash_value/Hasher/BuildHasher/_mix marked nothrow; String hash moved to std.core.hash.
  - Status (2026-01-21): LLVM codegen allows Uint64 (i64) non-throw return; string_hash_distinguishes e2e passes.
  - Status (2026-01-21): Hash<H> now requires H is Hasher (trait-level bound restored).
  - Status (2026-01-21): BuildHasher documented as a DefaultHasher seed provider (algorithms still fixed).
  - Plan: add type aliases to keep HashMap<K,V> ergonomic while allowing HashMapCore<K,V,B,H>.
    - Parser: support `type Alias<T> = Target<...>` at module scope; add AST node.
    - TypeTable: store alias defs; register during parse/load.
    - Type resolution: resolve aliases with arg substitution; detect cycles; enforce arity.
    - TypeKey/traits: normalize aliases to underlying types (diagnostics can keep alias names).
    - Tests: alias resolution, cycle error, arity mismatch, nested alias, trait bound via alias.
    - Stdlib: rename current map to HashMapCore/HashSetCore; add alias `HashMap<K,V>`/`HashSet<K>` using default hasher/builder.
  - Status (2026-01-22): type aliases implemented end-to-end; stdlib HashMap/HashSet now use aliases; stage1/stage2/type_checker pass.
  - Status (2026-01-22): added wrapping_add_u64/wrapping_mul_u64 intrinsics (nothrow) + MIR/codegen support; std.core.hash _mix now uses explicit wrapping ops; e2e tests added (wrapping_u64_ops, hash_wrap_overflow).
  - Status (2026-01-22): documented hash wrapping semantics in stdlib spec.
  - Status (2026-01-22): stdlib exports test updated to accept HashMap/HashSet as aliases.
  - Status (2026-01-22): free-call intrinsic dispatch for wrapping_add_u64/mul now uses @intrinsic on the decl (no module-name string match in call resolver).
  - Status (2026-01-22): trait solver now tracks trait type args; Hash<H> enforces H is Hasher again.
  - Status (2026-01-22): trait args now substitute type params in solver/type checker; algo capability tests pass.
  - Status (2026-01-22): function require-subject collection now includes trait-arg type params; sort_in_place generic requirements resolve.
  - Status (2026-01-22): iterator_invalidated_payload e2e updated to require SinglePassIterator<&Int>.
  - Status (2026-01-22): DEFAULT_HASH_SEED is Uint64 (no Int-typed hash constants).
  - Status (2026-01-22): LLVM codegen asserts WrappingAddU64/WrappingMulU64 operand types are Uint64.
  - Status (2026-01-22): String.bytes() kept storing a String handle copy (refs in struct fields disallowed in MVP); added note in iter.drift.
  - Status (2026-01-22): stdlib spec notes String Copy is O(1) retain-style; String.bytes() relies on it.
  - Status (2026-01-22): added HashMap/HashSet codegen e2e cases (basic ops, collisions, resize, iterator invalidation, string keys, hashset basic).
  - Status (2026-01-22): added MaybeUninit intrinsics for HashMap (maybe_write/assume_init_*), plus codegen mapping for MaybeUninit layout and std.mem call resolution.
  - Status (2026-01-22): field/index receivers now auto-borrow as canonical places in checker; removed explicit HashSetCore self.map borrows.
  - Status (2026-01-22): constructor kwarg values are now typechecked and feed ctor arg_types; fixes missing CallInfo for nested ctor args.
  - Status (2026-01-22): param binding scan now descends into stage1 dataclasses (kw args), aligning param binding_ids and enabling move on kwarg values.
  - Status (2026-01-22): HashSetCore now uses self.map.* directly; auto-borrow allows &mut on field receivers when base is &mut param.
  - Status (2026-01-22): method resolution now rejects auto-borrow on rvalue receivers; for-owned Array iteration reports Copy requirement failure instead of trying & borrow.
  - Status (2026-01-22): driver coverage for owned-for Copy requirement is locked by test_for_owned_array_requires_copy_element.
  - Status (2026-01-22): rvalue receiver autoborrow now emits the addressable-place diagnostic again (test_autoborrow_receiver_requires_place).
  - Status (2026-01-22): addressable-place diag is limited to method-call syntax so for-iter UFCS still reports Copy requirement.
  - Next: add collision/resize/iterator invalidation tests; consider HashCode alias if needed.

Algorithms

- sort_in_place (done; heapsort on RandomAccessPermutable)
- binary_search (done; BinarySearchable)
- equal (done earlier)
- min/max (gating tests done; implementation already exists)
- swap/replace intrinsics (done in std.mem)
