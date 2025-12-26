# Borrow same-block last-use issue
## Status
Completed (2025-12-26).


## Goal
Fix NLL-lite false positives where a borrow is last-used earlier in the same block but still blocks later writes.
Also propagate loans across ref-to-ref assignments so carrier liveness is accurate.

## Detailed intent (from user)
Eliminate same-block false positives like:

```
let r = &mut x;
use(r);   // last use
x = 1;    // should be allowed
```

by making loan death happen at the statement after the last use, not "somewhere later in the same block".

Also fix correctness/precision for cases where a borrow is copied:

```
let r = &mut x;
let s = r;     // s should carry the borrow too
use(s);
x = 1;         // must be rejected until s is dead
```

### Current behavior (what's wrong)
#### A) Loan liveness is block-granular
You already compute NLL-lite as:

- "this ref binding is live in these blocks"
- `Loan.live_blocks` = set of blocks where the loan may be live

But within a block, any use of `r` earlier keeps `r` effectively live until the end of that block, because the region model can only say "live in block X", not "live until stmt i".

So you end up conservatively treating:

- `loan(ref_binding_id=r)` as live for the whole block
- thus `x = 1` conflicts even though the last use happened earlier

#### B) Loans don't follow ref-to-ref copies/moves
Even if you add statement kill points for `r`, you'll still be wrong/overly permissive or overly conservative depending on implementation unless you also fix carrier propagation:

- if `s = r`, and `use(s)` occurs, the borrow should be live through `s`
- if you only track loans by original `ref_binding_id`, you'll incorrectly think the loan dies when `r` dies even if `s` is still live

### What the patch is supposed to change
#### 1) Introduce statement-level "kill points" inside each block
New data: for each block `B`, for each statement index `i`, compute the set:

> `live_after_stmt[B][i]` = the set of ref binding ids that are live immediately after executing statement `i`.

This is not replacing your existing block-level sets. It's refining them.

Key property:
If `r` is last used at statement `k`, then `r` is not in `live_after_stmt[B][k]`.
So loans tied to `r` can be dropped immediately after statement `k`.

How to think about it:
You already have:

- ref uses (where a ref binding id is used)
- ref defs (where a ref binding id is (re)assigned)

You just need them at statement granularity in addition to block granularity:

- `uses_stmt[B][i]` = ref ids used by statement i
- `defs_stmt[B][i]` = ref ids defined/rebound by statement i
- `uses_term[B]` = ref ids used by the terminator (branch condition etc.)

Then for each block, compute backward:

- start from `live_out[B]` (from your existing CFG fixed point)
- seed with terminator uses too, so branch conditions keep refs alive

Backwards recurrence:

```
live = live_out[B] ∪ uses_term[B]
for i from last_stmt down to 0:
    live_after_stmt[B][i] = live
    live = (live - defs_stmt[B][i]) ∪ uses_stmt[B][i]
```

This is the statement-level refinement; it must be consistent with your existing region caps.

Important nuance: Do not hack this by calling `_collect_ref_uses_in_expr` with a sentinel block id if that function writes into a block-keyed map. You need a collector that returns a set of ref ids without mutating the global per-block accumulator (or refactor the collector to accept an output set).

#### 2) Drop dead ref-bound, non-temporary loans after each statement during transfer
Inside `_transfer_block`, after each statement is processed (including paths that currently `continue` early), apply a loan filter based on `live_after_stmt`:

Drop a loan `L` iff all are true:

- `L.ref_binding_id != None` (loan is tied to a ref local)
- `L.temporary == False` (temporaries already drop correctly)
- `L.ref_binding_id` not in `live_after_stmt[B][i]` (the carrier isn't live anymore after the statement)
- (optionally) `B in L.live_blocks` is irrelevant at this point because you're already in `B`; the statement filter is strictly stronger than the block filter.

Keep loans intact if:

- `ref_binding_id is None` (function-wide or non-carrier based loans, whatever you already do)
- `temporary=True`

Where exactly this must happen:

- At the end of the normal statement loop iteration
- Also on any early-continue path inside statement handling:
  - "HBorrow rebind fast path"
  - "error path where you bail out early but still keep analyzing"
  - any "skip remainder of statement" path

Net effect: within a single block, loans die as soon as their carrier ref binding becomes dead, enabling writes that follow the last use.

#### 3) Propagate loans across ref-to-ref assignments (loan carrier cloning)
You want semantics:

- If `dst` becomes a copy/move of `src` (both ref-typed locals), then `dst` should now carry the same loans as `src`, and those loans should be considered live as long as `dst` is live too.

Minimal carrier model that fits your existing structure:

- Keep `Loan.ref_binding_id` as a single carrier id per loan.
- On `dst = src`, create cloned loans with identical payload but `ref_binding_id = dst`.

This avoids introducing "multiple carriers per loan" and fits the current loan structure.

What to do on assignment vs let:

- HAssign (rebinding): it overwrites `dst`, so:
  1. drop existing loans where `loan.ref_binding_id == dst` (dst no longer carries old borrows)
  2. clone src-carried loans onto dst
- HLet (new binding): dst is fresh, so:
  - no need to drop old dst loans (they can't exist)
  - clone src-carried loans onto dst

Interaction with existing HBorrow path:
Keep your existing "dst becomes a new borrow of place P" logic intact.
This propagation rule only kicks in when RHS is a ref local, not a borrow expression.

Region cap / live_blocks for cloned loans:
A cloned loan tied to `dst` must follow dst's region, not src's, otherwise you'll either keep it live too long or kill it too early.

So when cloning, set:

- `clone.live_blocks = ref_live_blocks[dst]` (or equivalent region info for dst)
- keep everything else (place, kind, origin span) identical

This is crucial: you're not "moving the original loan"; you're "creating a new carrier-bound view of the same underlying borrow" with the correct lifetime bound.

### Invariants this change is trying to preserve
1) Soundness is not weakened relative to current behavior:
   - The statement-kill only removes loans when their carrier is proven dead at that point (per backwards liveness).
   - Carrier propagation makes you more sound, not less, because you stop losing borrows when refs are copied.
2) Temporaries continue to work exactly as they do now.
   - Any loan flagged temporary continues to die at the expression/call boundary.
   - The new kill filter should explicitly ignore temporary loans.
3) Terminators are treated as uses at end of block.
   - If a ref is used in a branch condition or switch, it must remain live through the terminator evaluation.
   - That means the liveness seed for the backwards per-statement walk is `live_out ∪ uses_term`, not just `live_out`.
4) No new IR pass.
   - You're not rewriting CFG; you're just refining the transfer function and region construction with per-statement info.

### What fixed looks like (behavioral tests)
Same-block last use (allowed):

```
let r = &mut x;
use(r);
x = 1;
```

Copy keeps borrow alive (rejected until last copy use):

```
let r = &mut x;
let s = r;
use(s);
x = 1;     // reject
```

Allowed after last use of all carriers:

```
let r = &mut x;
let s = r;
use(s);
s = &mut y;   // rebinding kills dst-carried loans
x = 1;        // allow (assuming r not used later)
```

Terminator use (still rejected if borrow needed by branch condition):

```
let r = &mut x;
if cond(r) { ... }   // r used in terminator/cond path
x = 1;               // reject if r may be live here
```

### Merge guidance
We are changing `Loan.live_blocks` from being the only lifetime gate to being the outer gate, with `live_after_stmt` providing an inner gate within blocks, and we are ensuring that `ref_binding_id` correctly tracks all locals that can carry the borrow via cloning on ref-to-ref assignment.

## Results
- Added statement-level ref liveness and per-statement loan dropping while preserving conservative behavior for no-use refs.
- Implemented ref-to-ref loan propagation on `HLet`/`HAssign` using cloned loans bound to the destination ref's region cap.
- Added regression tests for same-block last use, ref copies, and unused-borrow conservatism (including inner-scope case).

## Tests run
- `PYTHONPATH=. .venv/bin/python -m pytest lang2/tests/borrow_checker/tests/test_regions.py -k "last_use_same_block or ref_copy or unused_borrow"`
- `PYTHONPATH=. .venv/bin/python -m pytest lang2/tests/borrow_checker/tests`

## Plan
1) Extend `BorrowChecker._build_regions` to compute per-statement ref liveness (`_ref_live_after_stmt`).
2) Drop dead ref-bound, non-temporary loans after each statement using `_ref_live_after_stmt` (including early-continue paths).
3) Propagate loans across ref-to-ref `HLet` and `HAssign` by cloning loans from src rid to dst rid.
4) Update tests: make the same-block last-use test expect success after the fix; add a ref-to-ref copy coverage case.

## Implementation constraints (confirmed)
- Use a pure collector for per-statement ref uses; do not call `_collect_ref_uses_in_expr` with a sentinel block id.
- Seed per-block statement liveness with `live_out ∪ uses_term` so terminator uses keep refs live.
- Clone loans only when RHS is a ref local with no projections (HVar or HPlaceExpr with empty projection chain); never on HBorrow RHS.
- Cloned loans must use the destination ref's region cap (`_ref_live_blocks[dst]` when present).
- Ensure per-statement loan-kill runs on early-continue paths (HBorrow rebind, non-lvalue errors).

## Notes / open questions
- Decide whether `_ref_witness_in` diagnostics should become statement-precise (optional).
- Ensure terminator uses are included in per-statement liveness so branch conditions keep refs alive.

## Tests
- `PYTHONPATH=. .venv/bin/python -m pytest lang2/tests/borrow_checker/tests/test_regions.py -k last_use_same_block`
- `PYTHONPATH=. .venv/bin/python -m pytest lang2/tests/borrow_checker/tests/test_regions.py -k ref_copy`
