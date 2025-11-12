# Drift Playground Snippets

Each `.drift` file here is a focused syntax sample you can run with `./drift.py playground/<name>.drift`.

- `basics.drift` – imports `sys.console.out`, binds locals with `val`, and writes to the console.
- `functions.drift` – multiple functions using the `returns` keyword and sharing `String` values.
- `effects.drift` – demonstrates constructing and throwing `error(...)` values.
- `mutable_bindings.drift` – shows `var` locals (future mutation) and console output helpers.
- `logic.drift` – demonstrates boolean operators (`and`, `or`, comparison chains) on `Bool`/`Int64` values.
- `arrays.drift` – infers `Array<T>` from literals and shows the explicit annotation form.

Feel free to duplicate and tweak these while iterating on syntax ideas.
