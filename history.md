## 2025-12-08 – String params & array helper decls
- Fixed LLVM backend to type arguments using function signatures (Int → i64, String → %DriftString) and emit typed call sites; function headers now preload param types into value_types.
- Moved array runtime helper declarations to module scope (emit once per module), preventing invalid IR from function-local declares.
- Added LLVM IR tests for typed params: Int+Int headers/calls and mixed Int/String param plus String return; added String literal pass-through call test.
- Updated docs/comments: compile_to_llvm_ir_for_tests now mentions Int/String/FnResult returns; string work-progress reflects param support; TODO trimmed.
- All tests green (PYTHONPATH=.. ../.venv/bin/pytest).
## 2025-12-08 – String ops in LLVM
- Added String-aware binary op lowering: `==` calls `drift_string_eq`, `+` calls `drift_string_concat`, and String `len` reuses ArrayLen lowering to extract the length field.
- Module builder now emits `drift_string_eq`/`drift_string_concat` declares once when needed; array helper declares remain module-level.
- Added LLVM IR tests for string len on a String operand and for string eq/concat; existing literal/pass-through tests remain green.
- All tests passing: PYTHONPATH=.. ../.venv/bin/pytest.
## 2025-12-08 – String ops via MIR, e2e len/eq/concat
- HIR→MIR now emits explicit `StringLen`, `StringEq`, and `StringConcat` for `len(s)`, `s == t`, `s + t` on strings; BinaryOpInstr no longer handles string operands.
- LLVM lowers these MIR ops: string len via `extractvalue %DriftString, 0`; eq/concat via runtime calls with module-level declares for `drift_string_eq` / `drift_string_concat`.
- E2E runner links string_runtime; added e2e cases for string len (literal/roundtrip), concat len, and eq; all passing. Added negative LLVM test for unsupported string binops.
- Array helper declares remain module-level; all tests green.
