# exceptions & diagnostics – work progress (step 1)

## Scope

Step 1 is **spec-only**. No compiler or runtime changes. The goal is to align the language documentation with the diagnostic-only exception model:

- `Error` stays `{ event, args: Map<String, String>, ctx_frames, stack }`.
- Every exception argument and `^`-captured local is recorded as a **diagnostic string**; no privileged “first payload”.
- Chapter 14 should stop inlining a specific formatting trait and instead refer to a shared diagnostic-formatting requirement.
- Traits chapter should acknowledge that requirement and point toward a dedicated diagnostic trait (forward-looking), without removing existing traits yet.

## Completed (this pass)

- **Exception model clarified in `drift-lang-spec.md`:**
  - Intro + §14.2 now state that all exception args and `^` locals are stored as diagnostic strings in `Error.args` / `ctx_frames`.
  - Removed the “first `String` payload” wording.
  - §14.3/14.4 reference a diagnostic formatting requirement instead of hard-wiring `Display`.
- **Traits chapter hook added:** §5.13.7 notes the diagnostic-formatting requirement for exceptions/`^` capture and leaves room for a dedicated trait in a later step.
- **This tracker updated** to reflect the narrowed, spec-only scope of step 1.

## Next steps (not started here)

- Formalize a dedicated `Diagnostic` trait and update trait examples (Display/Debuggable) accordingly.
- Extend grammar/DMIR docs once the diagnostic trait and runtime shape are finalized.
- Move implementation/runtime toward the fully string-normalized args/ctx model after the spec is settled.
