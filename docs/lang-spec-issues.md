## 1. Chapter ordering & logical flow

### 1.1 Current chapter order (for reference)

1. Overview
2. Expressions (surface summary)
3. Variable and reference qualifiers (+ some struct + comments + SourceLocation)
4. Ownership and move semantics
5. Imports and standard I/O
6. Control flow
7. Reserved keywords and operators
8. Standard I/O design
9. `lang.array`, `ByteBuffer`, and array literals
10. Collection literals
11. Variant types
12. Exceptions and error context
13. Mutators, transformers, and finalizers
14. Null safety & optional values
15. Traits and compile-time capabilities
16. Interfaces & dynamic dispatch (+ closures preview)
17. Memory model
18. Concurrency & virtual threads
19. Pointer-free surface and ABI boundaries
20. Signed modules and DMIR
21. Dynamic plugins (Drift→Drift ABI)
    Appendix A/B/C

### 1.2 Where “definitions before uses” is currently violated

You regularly *use* a concept before giving its canonical definition:

* `Copy` trait: mentioned in Ownership (§4) as “Types that want implicit copies implement the `Copy` trait (see Section 13.3...)” but traits are only defined in §15.
* `Display`, `Serializable`, `Debuggable`, `Destructible`, `Send`, `Sync`: used in examples in I/O, exception formatting, ByteBuffer, traits, concurrency, etc., but the trait system itself is only formalized in §15.
* `interface`: used in §5 and defined informally in §8 (`OutputStream`) before the real “what is an interface” chapter (§16).
* `Result<T, E>` and `Option<T>`: both appear earlier than the variant chapter (§11). `Result` is used heavily in §12 and §21, but its formal shape is given only in §11.
* `Optional<T>`: null-safety chapter (§14) effectively describes an “optional type” that conflicts with `Option<T>` in §11.
* `Slot<T>` / `Uninit<T>`: described partially in §17 and §19, but referenced with a bogus cross-ref (`Section 15.1.2`).

So strictly speaking you *don’t* satisfy “definitions dominate uses” today.

### 1.3 Recommended **minimal reordering** (no massive rewrite)

If you want to keep churn low but tighten the logical flow, here’s a minimal reordering that fixes most definition-before-use issues:

**Keep 1–4 as-is:**

1. Overview
2. Expressions
3. Variable/refs/structs/comments/SourceLocation
4. Ownership and move semantics

**Then move traits & interfaces up so everything else can rely on them:**

5. Traits and compile-time capabilities (current 15)
6. Interfaces & dynamic dispatch (+ closure preview) (current 16)

**Then general language plumbing:**

7. Imports (split out console details, see below) (current 5 minus IO bits)
8. Control flow (current 6)
9. Keywords and operators (current 7)

**Then core types & collections:**

10. Variant types (`variant`, `Result`, `Option`) (current 11)
11. Null safety & optional values (current 14, cleaned up to *reuse* `Option<T>`)
12. `lang.array`, `ByteBuffer`, slices, array literals (current 9)
13. Collection literals (current 10)

**Then error handling and operational semantics:**

14. Exceptions and error context (current 12)
15. Mutators, transformers, and finalizers / pipeline `>>` (current 13)
16. Memory model (current 17)
17. Pointer-free surface & ABI boundaries (current 19)

**Then “standard library design chapters”:**

18. Standard I/O design (`std.io`, `std.console`) (current 8)

**Then concurrency & distribution:**

19. Concurrency & virtual threads (current 18)
20. Signed modules and DMIR (current 20)
21. Dynamic plugins ABI (current 21)

Appendices unchanged, but Appendix C must be updated (see below).

That reordering:

* Guarantees traits/interfaces are defined before you lean on them in I/O, ByteBuffer, and concurrency.
* Puts `variant` (and thus `Result`/`Option`) before exceptions and null safety.
* Groups memory model and pointer-free ABI so 19 doesn’t have to forward-define uninitialized storage.

You *don’t* have to implement this reordering right now, but if you keep current order you should at least:

* Add forward references (“Traits are defined formally in Chapter 15”) wherever you use trait names earlier.
* Fix all chapter numbers and dangling references regardless.

---

## 2. Cross-reference & numbering issues

These are the things that are just flat wrong today and need to be fixed regardless of chapter order.

> I’ll use “current chapter number” so you can patch the existing file even if you postpone reordering.

### 2.1 Ownership and Copy trait (current §4)

* You say “Types that want implicit copies implement the `Copy` trait (see Section 13.3 for the trait definition)” — there *is* no Section 13.3 and the trait system is in Chapter 15.
* **Fix:** Replace with something like:

  * “Types that want implicit copies implement the `Copy` trait (see Chapter 15, *Traits and compile-time capabilities*).”
* Also, you introduce `copy <expr>` here; grammar doesn’t mention it anywhere else. Either:

  * add `CopyExpr ::= "copy" Expr` to Appendix B, **or**
  * move `copy`’s first mention into the traits chapter (where `Copy` is defined) and cross-link back.

### 2.2 ByteBuffer and `Send`/`Sync` references (current §9)

* ByteBuffer section talks about `Send`/`Sync` and explicitly says “These rules integrate with `Send`/`Sync` (Section 13.13)” — there is no §13.13; `Send`/`Sync` are defined near the end of Chapter 15.
* **Fix:** Point to the trait chapter: “These rules integrate with the marker traits `Send` and `Sync` (see Chapter 15, section *Thread-safety marker traits*).”

### 2.3 Traits chapter vs Appendix C

* Chapter 15 uses `require T is Trait`, `if T is Trait`, boolean trait expressions; Appendix C still documents an older grammar:

  ```ebnf
  TraitWhere ::= "where" TraitClause
  TraitClause ::= "Self" "has" TraitExpr
  Implement  ::= "implement" Ty "for" Ty TraitWhere? TraitBody
  ```

* This contradicts the current surface syntax.

* **Fix:**

  * Rewrite Appendix C to match the actual syntax you demonstrate in Chapter 15:

    * `struct Foo require Self is Destructible, T is Debuggable { ... }`
    * `fn f<T> require T is Debuggable (...)`
    * trait guards: `if T is Debuggable { ... }`
  * Remove or deprecate all mentions of `where Self has` / `TraitWhere`.

### 2.4 Pointer-free chapter cross-refs (current §19)

* §19 says “see Section 15.1.2” for `Slot<T>` / `Uninit<T>` and growth semantics; there is no 15.1.2 describing memory slots. The authoritative description is in Chapter 17 (Memory model) under “Slots and uninitialized handles / Array layout / Growth.”
* **Fix:**

  * Change those cross-refs to point to the Memory Model chapter (“see Chapter 17, *Value storage* and *Allocation & deallocation*”).
  * Or better: *move* the short “Slots and uninitialized handles” section out of §19 and merge it into §17, then have §19 reference §17.

### 2.5 Plugins chapter and `Result`/`Error` references (current §21)

* §21 refers to `Result<T, Error>` as “the variant described in Chapter 9” and “Error is the Chapter 9 layout”.
* In the current file:

  * `Result<T,E>` / `variant` are defined in Chapter **11**.
  * `Error` layout and exception machinery are defined in Chapter **12**.
* **Fix:**

  * “using the variant described in Chapter 11 (*Variant types*)”
  * “where `Error` has the layout defined in Chapter 12 (*Exceptions and error context*).”

### 2.6 Exceptions chapter and internal `Result` reference (current §12)

* §12 defines `Error` and then says “Conceptual form: `variant Result<T, E>` … Every function behaves as if returning `Result<T, Error>`; ABI lowers accordingly.” That’s fine, but:

  * It implicitly depends on §11’s `variant` definition; the text should say “see Chapter 11” or move a small `variant` recap into §12.
* **Fix:**

  * Add a short note: “See Chapter 11 (*Variant types*) for the definition of `variant`.”

### 2.7 `Send` / `Sync` reference to “Section 16.6”

* In the traits chapter you mention “The concurrency chapter (Section 16.6) references these bounds…” — concurrency is Chapter 18, and there is no 16.6.
* **Fix:** Rephrase to something non-numeric:

  * “The concurrency chapter references these bounds when describing virtual-thread movement and sharing.”
* If you insist on numbers, wait until you’ve finalized the chapter renumbering and then plug in the correct 18.x.

### 2.8 Appendix B mentioning traits/where

* Appendix B says “(Trait/`implement`/`where` grammar is summarized in Appendix C.)”
* Since you no longer use `where` for traits, this line is misleading.
* **Fix:** Update to “Traits and `implement` grammar are summarized in Appendix C.” and make sure Appendix C itself matches the `require` syntax.

---

## 3. Local content & semantic inconsistencies

### 3.1 Null safety vs `Option<T>` (current §14 vs §11)

Right now you have *two* optional concepts:

* Chapter 11: `variant Option<T> { Some(value: T); None }` (classic sum type).
* Chapter 14: “Null safety & optional values” that describes an `interface Optional<T>` with methods `present`, `none`, `unwrap`, `map`, `if_present`, etc., and a `module Optional` with `of` / `none`.

This is confusing:

* Is `Optional<T>` a variant (`Option<T>`), an interface, or something else?
* You also talk about `Option<T>` in the variants chapter.

**Strong recommendation:**

* Pick *one* name and *one* representation:

  * For the core type, use `variant Option<T>` in Chapter 11.
  * In Chapter 14, describe *APIs* built around that variant (helpers, methods, etc.), not a separate “interface Optional”.

* Concretely:

  * Replace `interface Optional<T>` in §14 with either:

    * a `variant Option<T>` recap referencing §11, and
    * free functions or extension methods (e.g., `OptionExt<T>` trait) that give you `present()`, `map`, etc.
  * Replace `Optional.of`/`Optional.none` with `Option.some` / `Option.none` (or align naming with what you actually want long-term).

Right now this is the biggest conceptual conflict in the whole spec.

### 3.2 Broken code block and stray “tuple” section in §14

Inside §14 you have:

* `### End-to-end example`, then a ```drift code fence, then mid-block you suddenly get:

  * “### Tuple structs & tuple returns”
  * Narrative text about tuple structs
  * `import sys.console.out`
  * Then eventually code.

This is clearly a merge artifact:

* The “Tuple structs & tuple returns” subsection belongs either:

  * up in §3 where you first introduce struct syntax, or
  * in its own mini section (e.g., “Tuple structs and tuple returns”) earlier in the type system material.
* The code fences are broken: markdown parsers will treat “### Tuple structs...” as literal text inside the code block.

**Fix:**

* Close the ```drift fence before “### Tuple structs & tuple returns”.
* Move that entire “Tuple structs & tuple returns” subsection out of §14; it has nothing to do with null safety.
* Decide where tuple structs live long-term (probably in Chapter 3 with structs, or immediately after variants).

### 3.3 Method naming consistency (`to_string` vs `toString`)

Across the spec you have both:

* `Display.to_string()` (lowercase with underscore) and
* examples using `.toString()` (camelCase) in §14.

You also explicitly say C++ devs will find certain notations confusing and want consistency.

**Fix:**

* Standardize on `to_string()` everywhere:

  * Traits chapter, exceptions chapter, null-safety examples, etc.
* Search and kill all `toString()` mentions.

### 3.4 `let` keyword usage vs keywords list

You explicitly forbid `let` in earlier design discussions and don’t list it as a keyword in the reserved list (§7). But some examples still use `let`:

* In ByteBuffer copy pattern: `let filled = src.read(...)`, `let chunk = scratch.slice(...)`.
* In literals chapter: `let m = Map<K, V>()`, etc.

**Fix:**

* Replace `let` with `val` or `var` consistently in all examples.
* Either:

  * keep `let` *completely unused* and unreserved, or
  * add it to the keyword list and document its meaning (but you explicitly said you don’t want it).

Right now it’s phantom syntax.

### 3.5 Traits syntax vs “where” and “Self has”

Chapter 15 is internally consistent on the *examples*:

* `require T is Debuggable`
* `require Self is Destructible`
* Trait guards: `if T is Debuggable { ... }`

But the very bottom of Appendix C still talks about `where` and `Self has TraitExpr`. You also have a one-line comment “These forms defer to the existing `where` machinery described in Section 13.” which no longer exists.

**Fix** (beyond Appendix C):

* Delete or rewrite any text that claims traits use `where`.
* Keep *only* `require` and `if T is` forms in the spec.

### 3.6 Pipeline operator `>>` (current §13)

Mutators/transformers/finalizers chapter uses `>>` pipelines heavily:

```drift
open("x")
  >> fill
  >> tune
  >> finalize;
```

But:

* `>>` is not mentioned in the operators list in §7.
* Not present in the grammar in Appendix B.
* Not defined in terms of associativity, precedence, or desugaring.

**Fix:**

* In §7, list `>>` as a binary operator, with precedence relative to `+`, `|`, etc.
* In Appendix B, add:

  ```ebnf
  PipeExpr ::= PipeExpr ">>" PipeStage
             | PrimaryExpr
  PipeStage ::= Ident | CallExpr | ...
  ```

  (or whatever your real grammar is).
* In §13, explicitly specify desugaring. For example:

  * `x >> f` desugars to `f(x)` (with ownership rules based on parameter type).
  * `x >> f >> g` is `(g(f(x)))` with left-associativity.

Right now the semantics are described conceptually but not nailed into syntax.

### 3.7 Imports vs Standard I/O duplication (current §§5 and 8)

You have:

* Chapter 5: “Imports and standard I/O” that covers import syntax *and* shows examples with `std.console.out`.
* Chapter 8: “Standard I/O design” that defines `std.io` / `std.console` in more detail, repeats `out.writeln` examples, etc.

This is mostly harmless but a bit messy:

* If you keep both:

  * §5 should be “Imports” and only **lightly** touch I/O (“we’ll define `std.console` in Chapter 8”).
  * §8 should be the canonical place for `OutputStream`, `InputStream`, and the `out/err/in` definitions.
* Right now they compete and look partially redundant.

### 3.8 Closures and `Callable<Args, R>` (inside §16)

Interfaces chapter contains a long “Closures/lambdas (surface preview)” subsection that:

* Defines closure syntax `|params| => expr`.
* Mentions capture modes (`x`, `copy x`, `ref x`, `ref mut x`) and an `env` box.
* Introduces a `Callable<Args, R>` interface type used in examples — but `Callable` is never formally defined elsewhere.

**Fix:**

* Either:

  * Move the closures section to its own chapter (“Closures and callable interfaces”) and define `interface Callable<Args, R> { fn call(self: ref Callable<Args,R>, args...) returns R }` properly, or
  * Mark this section explicitly as *non-normative preview* and clarify that details (including `Callable`) will be specified in a future chapter.

Right now it reads like a spec but doesn’t actually define the types it uses.

### 3.9 Grammar excerpts vs real surface

Appendix B’s grammar is clearly “EBNF excerpt” and outdated:

* It still uses `FnDef ::= "fn" ... (":" Type)?` rather than `returns`.
* It doesn’t know about `returns`, `variant`, `exception`, `module`, trait `require`, pipelines, etc.

That’s okay *as long as you label it clearly as partial*, but you should:

* Add a header: “This appendix is a partial, outdated sketch; the authoritative grammar will be updated in a future revision.”
* Or invest the time to bring it in sync with the syntax you actually use (big lift, but worth it long-term).

Right now, a reader could be misled if they treat Appendix B as normative.

---

## 4. Concrete TODO checklist

Here’s a punch-list you can turn into Git issues / commits:

1. **Decide on chapter ordering.**

   * Minimal reordering as in §1.3 (traits/interfaces earlier, DMIR/plugins at the end).
   * If you *don’t* reorder now, add explicit forward references where you use traits/interfaces/variants before defining them.

2. **Fix all numeric cross-refs:**

   * Ownership → `Copy` trait: change “Section 13.3” to “Chapter 15”.
   * ByteBuffer → `Send`/`Sync`: change “Section 13.13” to “Chapter 15”.
   * Pointer-free → `Slot<T>` / `Uninit<T>`: point to Memory Model chapter instead of “15.1.2”.
   * Plugins → `Result` and `Error`: point to Chapter 11 (variants) and 12 (exceptions), not 9.
   * Traits → concurrency section: remove “Section 16.6” or update after you fix numbering.
   * Anywhere else “Chapter X”/“Section X.Y” appears: do a global search and fix to current chapters.

3. **Unify optional / null-safety story:**

   * Base optional type is `variant Option<T>`.
   * Null-safety chapter describes semantics on top of that, doesn’t introduce a second “Optional<T> interface”.
   * Fix `Optional.of`/`Optional.none` naming accordingly.

4. **Clean up §14 code blocks and misplaced tuple text:**

   * Close the ```drift block before “Tuple structs & tuple returns”.
   * Move the tuple subsection to Chapter 3 (or wherever you want struct syntax documented).
   * Fix method names (`to_string` not `toString`) and `let` usages.

5. **Make traits syntax consistent:**

   * Use only `require` and `T is Trait` / `Self is Trait`.
   * Update Appendix C grammar to match:

     * `TraitDef ::= "trait" Ident TraitParams? TraitReqs? TraitBody`
     * `TraitReqs ::= "require" TraitReq ("," TraitReq)*`
     * `TraitReq ::= Type "is" Ident | "not" Type "is" Ident | ...`
   * Remove all references to `where`/`Self has`.

6. **Specify pipeline operator `>>`:**

   * Add it to keywords/operators chapter with precedence & associativity.
   * Add to grammar excerpt in Appendix B.
   * In §13, give desugaring rules formally (how ownership/moves are chosen).

7. **Resolve `let` vs `val`/`var`:**

   * Replace all `let` uses with `val` or `var`.
   * Make sure `let` is not reserved in keywords list unless you decide to support it.

8. **Standardize method names:**

   * Use `to_string()` everywhere (Display, Error formatting, examples).
   * Fix `toString()` occurrences.

9. **Clarify closures & `Callable<Args,R>`:**

   * Either fully spec `Callable` in the interfaces chapter (as a normal interface).
   * Or extract closures into a separate, clearly “preview” section and mark the semantics as provisional.

10. **Imports vs IO duplication:**

    * Turn §5 into “Imports” only; reduce IO talk to “we’ll use `std.console.out` (see Chapter 8).”
    * Keep the full IO semantics in §8 and cross-link from examples.

11. **Memory vs pointer-free duplication:**

    * Make §17 (Memory model) the canonical place for `Slot<T>`, `Uninit<T>`, `RawBuffer`, growth semantics.
    * Let §19 reference §17 instead of partially redefining them.

12. **Mark Appendix B as partial or update it:**

    * Either clearly label it as “partial, not authoritative” or bring it in line with current syntax (`returns`, `variant`, `exception`, `require`, `>>`, etc.).

