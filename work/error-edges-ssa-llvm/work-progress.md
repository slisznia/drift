### Next step: lower **Call with normal/error edges** in SSA→LLVM and add one tiny run-mode test

Do *just* this:

#### 1. Implement lowering for `mir.Call` with `normal`/`error` edges

In `ssa_codegen.py`, in your instruction/terminator lowering:

* Detect the **call-with-edges terminator** shape you already use in SSA MIR, e.g.:

  ```python
  isinstance(term, mir.CallTerm) and term.normal and term.error
  ```

* Assume the callee’s LLVM type matches your legacy `{T, Error*}` ABI (same as the old backend):

  ```llvm
  { T, %Error* } @foo(...)
  ```

* Emit LLVM like:

  ```llvm
  %pair = call {T, %Error*} @foo(args...)

  %val = extractvalue {T, %Error*} %pair, 0
  %err = extractvalue {T, %Error*} %pair, 1
  %has_err = icmp ne %Error* %err, null

  br i1 %has_err, label %error_bb, label %normal_bb
  ```

* Wire **block params** for both successors using your existing PHI machinery:

  * For the normal edge: pass `%val` (and any other edge args) into the target block’s params.
  * For the error edge: pass `%err` (and any other edge args) into the error block’s params.

If you see any call-with-edges that doesn’t match `{T, Error*}` yet, hard-error with a clear message.

No `throw`, no `try` lowering yet. Just the branching pattern.

#### 2. Add a single run-mode e2e that uses one error edge

Something dead simple like:

```drift
import std.console.out

fn always_ok(x: Int) returns Int {
    return x + 1
}

fn main() returns Int {
    // desugars to a call-with-edges at SSA
    val y: Int = try always_ok(41) else {
        out.writeln("err")
        return -1
    }
    out.writeln("ok")
    return y
}
```

Expected in `expected.json`:

* `mode: "run"`
* `exit_code`: `42`
* `stdout`: `"ok\n"`
* `stderr`: `""`

Make sure this test uses *exactly* the error-edge shape your SSA lowering already produces for `try … else` (check your existing SSA tests for that shape).

#### 3. Run the full suite

* All existing run-mode tests stay green.
* New `try_simple` (or whatever you call it) passes via SSA→LLVM.
* Any unimplemented error-edge shapes still fail loudly in the backend.
