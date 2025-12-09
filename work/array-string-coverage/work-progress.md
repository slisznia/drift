Done
• - Added Array<String> store IR coverage: new test constructs an Array<String>, stores a %DriftString element, and returns it; IR is
    checked for %DriftString element type, alloc/bounds checks, and the store.
  - Fixed test setup to import ArrayIndexStore and return a String value to match the function signature.
  - Cleaned up checker bitwise detection earlier; all tests (including new array test) pass.

TODO:
  - E2E: string_array_len_sum reads elements and sums .len, but never writes.
  - Negatives: the checker enforces “index must be Int”, but we don’t have explicit negative tests (e.g., String index) or wrong-element-
    type checks for Array<String>.

  - IR test for ArrayIndexStore on Array<String> (verify %DriftString element type and bounds checks).
  - E2E that writes into an Array<String> (e.g., assign to xs[1] then read back) and asserts the length sum.
  - Negative tests: using a non-Int index on Array<String> should emit a diagnostic; mixing element types in an Array<String> literal
    should be rejected.



  - Entry shim: implement fn main(argv: Array<String>) returns Int support (C shim to build Array<String> from argv, backend wrapper logic, argv e2e tests).

  - Missing negatives: we don’t yet have e2e/unit cases that assert type errors for misuse (e.g., String + Int, String as an array index, if s where s:
    String). Those are still to add.

