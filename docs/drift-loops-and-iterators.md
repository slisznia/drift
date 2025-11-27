# Drift Loops and Iterators — Integrated Spec (with Grammar Extension)

## 1. Goals

Drift’s looping model centers around a single, composable construct:

    for pattern in iterable { body }

This replaces all C-style loops. There is **no** `for (init; cond; step)` in Drift.

Rationale:
- Drift favors compile-time guarantees, ownership correctness, and explicit semantics.
- `for … in …` expresses iteration directly, integrates with the type system, and avoids hidden mutation/aliasing patterns common in C-style loops.
- All iteration is routed through a unified trait system (`IntoIterator`, `Iterator`) with `Option<T>` signaling termination.

---

## 2. Placement & Prelude

The iteration traits live in the standard library:

```
module std.iter
```

They are automatically made available to all Drift programs through the prelude:

```
import std.prelude.*
```

which re-exports:

```
export std.iter.{Iterator, IntoIterator}
```

Thus users **do not** manually import iteration traits.  
The control-flow chapter of the spec normatively states that `for pattern in expr` depends on these traits.

---

## 3. Core Traits

### 3.1 `Iterator<Item>`

```
trait Iterator<Item> {
    fn next(self: &mut Self) returns Option<Item>
}
```

### 3.2 `IntoIterator<Item, Iter>`

```
trait IntoIterator<Item, Iter>
    require Iter is Iterator<Item>
{
    fn into_iter(self) returns Iter
}
```

Any type may define how to turn into an iterator, supporting owned or borrowed iteration.

---

## 4. Foreach Loop Syntax

```
for pattern in expr {
    body
}
```

- `pattern` is a full Drift pattern (identifier, tuple, or variant pattern).
- `expr` must implement `std.iter::IntoIterator<Item, Iter>`.
- No implicit indexing, no C-style loop constructs.

---

## 5. Desugaring (Normative)

```
for pat in expr {
    body
}
```

desugars to:

```
{
    val __iterable = expr
    var __iter = __iterable.into_iter()

    loop {
        val __next = __iter.next()
        match __next {
            Some(pat) => { body }
            None => break
        }
    }
}
```

---

## 6. Borrowed vs Owned Iteration

### 6.1 Owned (consuming) iteration

```
var xs = Array<Int>[1, 2, 3]
for x in xs {
    out.writeln(x)
}
// xs is moved
```

### 6.2 Borrowed iteration

```
var xs = Array<Int>[1, 2, 3]
for x in &xs {
    out.writeln(x)
}
// xs is still valid
```

---

## 7. Pattern Support

Allowed pattern forms:

- `x`
- `(k, v)`
- `(a, (b, c))`
- `Some(x)`
- `Some((k, v))`
- Named-field variant patterns: `Some(value = x)`

For single-field variants:

```
Some(x) == Some(value = x)
```

Positional destructuring is preferred and idiomatic.

---

## 8. Iterator Implementations (Examples)

### 8.1 Consuming iterator

```
struct ArrayIter<T> {
    data: Array<T>,
    index: Int
}

implement<T> Iterator<T> for ArrayIter<T> {
    fn next(self: &mut Self) returns Option<T> {
        if self.index >= self.data.len() { return None }
        val item = self.data[self.index]->
        self.index += 1
        return Some(item)
    }
}
```

### 8.2 Borrowed iterator

```
struct ArrayIterRef<'a, T> {
    data: &'a Array<T>,
    index: Int
}

implement<'a, T> Iterator<&'a T> for ArrayIterRef<'a, T> {
    fn next(self: &mut Self) returns Option<&'a T> {
        if self.index >= self.data.len() { return None }
        val r = &self.data[self.index]
        self.index += 1
        return Some(r)
    }
}
```

---

## 9. Removing C-Style Loops

Drift supports only:

- `for pattern in expr { … }`
- `while cond { … }`
- `loop { … }` (planned)

Drift **does not** support:

- `for(init; cond; step)`
- `do { … } while`
- implicit indexing

All iteration routes through the iterator protocol.

---

## 10. Index-Based Iteration (Explicit)

```
var i = 0
while i < xs.len() {
    out.writeln(xs[i])
    i += 1
}
```

Explicit indexing is always valid.

---

## 11. Grammar Extension (Normative for Parsing)

This section updates `drift-lang-grammar.md` to include `for pattern in expr`.

### 11.1 Add `ForEachStmt` to statement grammar

```
Stmt          ::= ForEachStmt
                | WhileStmt
                | ValDecl | VarDecl | ExprStmt
                | IfStmt
                | ReturnStmt | BreakStmt | ContinueStmt
                | TryStmt | ThrowStmt
```

```
ForEachStmt   ::= "for" Pattern "in" Expr Block
```

### 11.2 Reserve `in` as a keyword

Add `"in"` to the reserved keyword list.

### 11.3 Pattern grammar (supports tuples and variants)

```
Pattern        ::= SimplePattern

SimplePattern  ::= Ident
                 | "_"
                 | Literal
                 | TuplePattern
                 | VariantPattern

TuplePattern   ::= "(" Pattern ("," Pattern)+ ")"

VariantPattern ::= Ident "(" PatternList? ")"

PatternList    ::= Pattern ("," Pattern)*
                 | FieldPattern ("," FieldPattern)*

FieldPattern   ::= Ident "=" Pattern
```

This grammar supports:
- `(x, y)`
- `Some(x)`
- `Some((k, v))`
- `Some(value = x)`
- nested destructuring

### 11.4 Iterator trait requirement (semantic)

Semantic validation ensures:

- `expr` implements `std.iter::IntoIterator<Item, Iter>`
- `Iter` implements `std.iter::Iterator<Item>`

---

## 12. Summary

- `for pattern in expr` is Drift’s canonical loop.
- Powered by `std.iter::Iterator` and `std.iter::IntoIterator`, available via `std.prelude`.
- Desugaring defines precise semantics.
- Full destructuring supported.
- Grammar formally extended with `ForEachStmt`.

