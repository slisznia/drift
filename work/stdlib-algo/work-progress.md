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
  - Status (2026-01-22): LLVM codegen now requires typed operands for wrapping_{add,mul}_u64 (hard error if missing).
  - Status (2026-01-22): borrow-checker comment updated to reflect field/index borrows are supported; rvalue materialization remains future work.
  - Status (2026-01-22): added HashMap e2e coverage for empty iterator, get_mut, zero-capacity insert, repeated remove, and String values.
  - Status (2026-01-22): trait impl metadata now captures trait args (including exports); trait solver matches impls by args; added driver test for UFCS trait impl type args.
  - Status (2026-01-22): UFCS trait calls now enforce trait args for concrete receivers; added negative diagnostic test for mismatched trait args.
  - Status (2026-01-22): UFCS trait call impl check now uses global trait world first to avoid missing downstream impls; hashmap_collision e2e passes.
  - Status (2026-01-22): Intrinsic dispatch now uses FnSignature.intrinsic_kind (no name matching in call resolver); signatures encode/decode intrinsic_kind for packages; wrapping_u64_ops e2e passes.
  - Status (2026-01-22): MIR validator now asserts wrapping_u64 operands are Uint64 (before LLVM); wrapping_u64_ops e2e passes.
  - Status (2026-01-22): added HashMap e2e cases (overwrite, remove-missing, clear, iter-all count) and HashSet iter invalidation; all new cases pass.
  - Status (2026-01-22): stage1 lower_function_block now records param_binding_ids on HBlock; normalize_hir preserves; driftc passes preseed_scope_bindings; type_checker uses preseed binding ids instead of scanning.
  - Status (2026-01-22): call_resolver canonicalizes TypeParamId via ensure_typevar for replace/swap comparisons; mem.write/read now validate index/value types; ptr_write value checks canonicalized.
  - Status (2026-01-22): type_checker seed binding id counter now descends into HUnsafeBlock, fixing false "&mut of immutable binding" errors for mem.write/mem.replace.
  - Status (2026-01-22): stage2 match lowering now emits Unreachable terminator when all arms return (prevents missing-return on stmt matches).
  - Status (2026-01-22): TreeMapIter/TreeSetIter no longer require Comparable in SinglePassIterator impls (avoids method-requirement mismatch); TreeSetIter.next now has explicit trailing return.
  - Status (2026-01-22): TreeMap.min_idx now ends with explicit `return i;` to satisfy stage2 return checks.
  - Status (2026-01-22): borrow checker now defers method receiver loans until after argument evaluation (two-phase-like), fixing TreeMap insert_fixup/remove_at borrowcheck errors and for-iter diagnostics.
  - Status (2026-01-22): stage2 array-literal inference now ignores Unknown element types when any known types agree; _infer_expr_type for int literals only trusts typed scalar int/uint/byte (avoids node-id collisions yielding Bool).
  - Status (2026-01-22): try-expression validator now allows nothrow call attempts (HCall/HMethodCall/HInvoke) to avoid false errors in package/boundary calls.
  - Status (2026-01-22): try-expression validator now treats any attempt containing a call expression as eligible (allows try on expressions like a() + b()).
  - Status (2026-01-22): adjusted e2e expectations for borrow_mut_field_param and match_ctor_type_args to be success cases (main returns 0).
  - Status (2026-01-22): tests run: pytest stage1+stage2+type_checker all pass; treemap_basic e2e not re-run yet.
  - Next: add collision/resize/iterator invalidation tests; consider HashCode alias if needed.

Algorithms

- sort_in_place (done; heapsort on RandomAccessPermutable)
- binary_search (done; BinarySearchable)
- equal (done earlier)
- min/max (gating tests done; implementation already exists)
- swap/replace intrinsics (done in std.mem)

TreeMap decisions (pinned):

- TreeMap<K, V> require K is cmp.Comparable.
- Core API:
  - tree_map_new<K,V>() -> TreeMap<K,V>
  - len(&self) -> Int, is_empty(&self) -> Bool
  - clear(&mut self)
  - contains_key(&self, key: &K) -> Bool
  - get(&self, key: &K) -> Optional<&V>
  - get_mut(&mut self, key: &K) -> Optional<&mut V>
  - insert(&mut self, key: K, value: V) -> Optional<V>
  - remove(&mut self, key: &K) -> Optional<V>
  - iter(&self) -> TreeMapIter<K,V>
- Iteration: in-order; iterator stores gen_snapshot; any mutation bumps gen; next() throws std.err.IteratorInvalidated if gen mismatched.
- Entry API:
  - entry(&mut self, key: K) -> Entry<K,V>
  - Entry is enum-like: Occupied(OccupiedEntry<K,V>), Vacant(VacantEntry<K,V>)
  - Occupied: key(&self)->&K, get(&self)->&V, get_mut(&mut self)->&mut V, replace(self, value: V)->V, remove(self)->V
  - Vacant: key(&self)->&K, insert(self, value: V)->&mut V
- Design constraint: Entry holds &mut TreeMap internally to prevent concurrent mutation.

TreeMap representation feedback (pinned):

- Use index-based arena for nodes; store by index (no pointers).
- Node fields: key, value, left/right/parent (parent recommended for RB delete fixup + iterator), color: Bool (RB) or height: Int (AVL).
- TreeMap fields: root, len, gen, nodes (RawBuffer<MaybeUninit<Node<K,V>>> or Array<NodeSlot>), free_head (free list), cap (if needed).
- alloc_node: pop free list or grow buffer; write Node into slot; return index.
- free_node: drop key/value as needed; push idx onto free list.
- clear/drop: walk all live nodes and drop exactly once; then root=None, len=0; rebuild free list (e.g., mark all indices free).
- Hotspot: clear/drop correctness; add tests to ensure drop exactly once.

TreeMap algorithms (pinned):

- Search: standard BST using cmp.Comparable::compare(&k, &node.key).
- Insert (RB): insert as red leaf; fix-up via parent/uncle cases; ensure root black; len++, gen++.
- Remove (RB): standard RB delete with transplant + fix-up; move out removed value before free_node; len--, gen++.

TreeMap iteration (pinned):

- Use explicit stack (Array<Int>) for in-order traversal; simpler MVP.
- Iterator fields: stack, gen_snapshot (and optional cur or just stack).
- Init: push left spine from root.
- next(): check gen, pop idx, push left spine of right child, yield (&key, &value).
- Parent-pointer threaded walk optional later; skip for MVP.

TreeSet (pinned):

- TreeSet<K> require K is cmp.Comparable.
- Thin wrapper over TreeMap<K, ()>.
- insert(k) -> Bool (true if new), remove(&k) -> Bool, contains(&k) -> Bool.
- iter() -> Iter<K> yielding &K.

TreeMap/TreeSet tests (MVP, pinned):

Correctness
- insert/get/overwrite/remove
- contains/get_mut
- remove missing key returns None

Order
- insert shuffled keys, iter yields sorted
- remove some keys, iter still sorted

Rotation / balancing invariants
- RB: root black; no red node with red child; equal black height on all root->leaf paths (debug_validate helper for tests)
- AVL (if used later): height invariants and balance factor in {-1,0,1}

Remove cases
- leaf, one child, two children
- removing root repeatedly until empty

Entry API
- Vacant.insert returns &mut V to inserted
- Occupied.replace returns old
- Occupied.remove returns value and deletes key
- Optional: compare-count key to assert no double lookup if available

Iterator invalidation
- create iter; mutate map; next() throws IteratorInvalidated

Arena safety
- clear drops once
- remove drops once
- reuse freed indices (insert/remove/insert sequences)

TreeMap implementation staging (pinned):

1) Arena + free list + traversal helpers (push_left_spine, find_node, min/max).
2) Search + iter (even before balancing) to validate ordering + arena correctness.
3) Insert with balancing (RB).
4) Remove with balancing.
5) Entry API (using internal find-or-insert-position routine).
6) TreeSet wrapper.

TreeMap implementation status (2026-01-22):
- Started RB TreeMap implementation in stdlib; initial arena-based RawBuffer version hit typechecker limits around nested generics and reference-return escape rules.
- Temporarily removed Entry API from stdlib exports/impl and dropped treemap_entry e2e to unblock compilation (entry methods returning references violate MVP escape rule).
- Began refactor to SoA buffers (keys/values/left/right/parent/red/free_next) to avoid MaybeUninit<TreeNode<...>> nesting; still failing in typecheck (mem.* constraints around RawBuffer/V, swap, and mutable bindings).
- Added TreeMap/TreeSet e2e cases: treemap_basic, treemap_iter_order, treemap_iter_invalidate, treemap_remove_cases, treemap_resize, treeset_basic, treeset_iter_invalidate.
- Current blocker: typecheck errors in TreeMap mem.* usage (ptr_at_mut/write/swap/dealloc) + TreeMapItemRef inference and TreeSet iterator Optional match inference.
