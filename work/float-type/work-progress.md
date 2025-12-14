# Float type (`Float`) — work tracker (lang2)

This tracker captures the end-to-end work needed to add a production-quality surface `Float`
type to the `lang2/` compiler pipeline.

## Locked decisions (v1)

- Surface type: `Float` exists as a language type.
- Underlying representation: IEEE-754 **double** (`f64` / C `double` / LLVM `double`).
- No width-specified types in v1 (`Float32`, `Float64`, etc. are future work).

## Float literal syntax (v1)

### Accepted

- Decimal only, base-10.
- Requires digits on both sides of the dot:
  - `DIGITS "." DIGITS`
  - Optional exponent *only when the dot form is present*:
    - `DIGITS "." DIGITS (("e"|"E") ("+"|"-")? DIGITS)?`
- Negative sign is **not** part of the literal:
  - `-3.5` parses as unary `-` applied to the float literal `3.5`.

Examples (valid):
- `1.25`, `0.0`, `10.5`
- `1.0e3`, `1.25E-3`, `0.0e+0`

### Rejected (v1)

- Trailing dot: `1.` (suggest `1.0` later via diagnostics)
- Leading dot: `.5` (suggest `0.5` later)
- Exponent without dot: `1e-3` (suggest `1.0e-3` later)
- Underscores: `1_000.0`
- Hex floats: `0x1.2p3`
- `NaN` / `Inf` literals

## Formatting (v1)

- Deterministic float-to-string uses **Ryu** via `drift_string_from_f64(double)` (already vendored in `lang2/drift_core/runtime`).
- F-string holes support `Float` by lowering to `StringFromFloat` → `drift_string_from_f64`.

## Work items

### 1) Parser / lexer
- [x] Add a `FLOAT` token that matches `DIGITS "." DIGITS EXP?` and does not accept `.5` or `1.`.
- [x] Ensure token precedence: float lexes before int (`1.0` is one token, not `1` + `.` + `0`).
- [x] Keep `-` as unary operator (no signed float token).

### 2) Type system
- [x] Add `TypeKind.FLOAT` and `TypeTable.ensure_float()` for canonical `Float`.
- [x] Wire resolver mapping for surface `Float` annotations.

### 3) HIR + typing
- [x] Add `HLiteralFloat` (or equivalent) produced by lowering from parser/stage0.
- [x] Type checker infers float literal type = `Float`.
- [x] Ensure `Float` participates in relevant contexts (let/assign/return/params).

### 4) MIR + LLVM codegen
- [x] Add `ConstFloat` MIR instruction (double) and lower to LLVM `double` constants.
- [x] Thread float types through `TypeEnv` / `value_types` where required.
- [x] Add `StringFromFloat` MIR op and lower to runtime `drift_string_from_f64`.
- [x] Update f-string lowering to accept `Float` holes.

### 5) Tests (tight matrix)

**Parser/type matrix**
- [x] Valid literals parse:
  - `0.0`, `1.25`, `10.5`, `1.0e3`, `1.25E-3`, `0.0e+0`
- [x] Invalid literals reject (and do not crash):
  - `1.`, `.5`, `1e-3`, `1.0e`, `1.0e+`, `1_0.0`

**E2E (Drift → LLVM → binary)**
- [x] Print float via f-string: local `Float` var interpolates and prints stable output.
- [x] F-string mixed holes: `Bool`, `String`, `Int`, `Float`.

## Notes / future work

- Targeted float diagnostics (e.g., `E-FLOAT-TRAILING-DOT`) can be added once the parser has a general parse-error-to-diagnostic path.
- Float arithmetic ops and comparisons are deferred unless needed by tests.
