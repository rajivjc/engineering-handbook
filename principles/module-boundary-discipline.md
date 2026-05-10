# Principle: Module boundary discipline

A “module” is a body of code that has a declared boundary with the rest of the application. The boundary is enforced by automated tests, not by convention or comment.

Boundaries earn their keep when:

- The module might be extracted as a standalone product later.
- The module has its own domain language and deserves a vocabulary the rest of the codebase doesn’t intrude on.
- The module is large enough that uncontrolled coupling would slow future change.

Boundaries are dead weight when:

- The module is small.
- The module fundamentally depends on host primitives (identity, audit, cross-cutting infrastructure).
- The “boundary” exists only because someone read about modular monoliths.

The discipline is to be explicit about which case applies and to enforce the answer. Modules either *have* a boundary that’s automated-test-enforced, or they don’t have a boundary at all and code can flow freely.

## Two valid stances

**Lift-out-able.** The module has commercial or technical value as a standalone unit. The boundary is enforced strictly:

- All imports between the module and the rest of the application go through a small set of declared integration files.
- Database tables are prefixed with the module’s namespace.
- Audit events are prefixed with the module’s namespace.
- A grep-based boundary test fails CI if a new import path is introduced without updating the integration set.
- The boundary test is paired with deliberate-violation verification — periodically, a fake violation is added to confirm the test catches it.

**Host-folded.** The module has no plausible extraction path. It reuses host primitives top to bottom:

- No boundary test, no allow-list, no rules about which files can import what.
- Tables are still prefixed by domain (so they’re searchable) but there’s no rule about who can join across the prefix.
- Audit events are still prefixed (for retention and querying), but no rule about who can emit them.
- The only rule is that *unrelated* modules don’t import each other — i.e., if there are two host-folded modules, code shouldn’t flow between them, but each can flow into and out of the host freely.

## What’s not allowed

The failure mode is a third stance: “we have a boundary by convention.” This means:

- The boundary is declared in a README or comment.
- The boundary is enforced by code review, sometimes.
- The boundary erodes silently as new features land under deadline pressure.
- After two years, the boundary exists only in the README.

This stance has the cost of explicit boundary discipline (you have to think about cross-module imports) without the benefit (you don’t actually catch violations). Pick one of the two valid stances and live with the consequences.

## What this looks like in practice

For a lift-out-able module, the boundary test is a grep-based check:

```ts
// tests/competitions/boundary.test.ts

const ALLOWED_OUTSIDE_TO_INSIDE = [
  'src/app/(community)/competitions',  // route pages
  'src/app/(community)/leagues',       // route pages
  'src/components/ui/StaffSidebar.tsx', // nav entry
]

const ALLOWED_INSIDE_TO_OUTSIDE = [
  'src/competitions/data/players.ts',  // identity adapter
  'src/competitions/audit.ts',          // audit wrapper
  'src/competitions/events.ts',         // event hook
]

describe('competitions module boundary', () => {
  it('outside files do not import from src/competitions/ unless allowlisted', () => {
    const imports = greppedImportsFromOutsideToInside()
    const violations = imports.filter(i => !ALLOWED_OUTSIDE_TO_INSIDE.some(p => i.file.startsWith(p)))
    expect(violations).toEqual([])
  })

  it('inside files do not import host code unless allowlisted', () => {
    const imports = greppedImportsFromInsideToOutside()
    const violations = imports.filter(i => !ALLOWED_INSIDE_TO_OUTSIDE.some(p => i.file.startsWith(p)))
    expect(violations).toEqual([])
  })
})
```

The implementation is mechanical: grep the source tree for `import` statements, classify each by whether the source and destination are inside or outside the module, filter against the allowlists, fail if any violations remain.

The deliberate-violation step: periodically, add an unauthorized import (e.g., a host file importing from inside the module) and confirm the test fails. Then remove the violation. This proves the test is actually engaging.

## Anti-patterns

- **Boundary in a comment.** Doesn’t survive the next refactor.
- **Boundary in a code review checklist.** Survives until the third tired Friday.
- **Boundary tests that match by file pattern but don’t grep imports.** “Files in src/competitions/ should not import from outside” — but if you’re testing by file location, you can’t enforce per-file allowlists. The grep approach lets you say “this specific file is allowed, that one isn’t.”
- **Allow-list with no documented reasons.** When the next person sees an entry, they don’t know if it’s load-bearing or accidental. Every entry should have a comment naming the integration point.
- **Module that imports the host’s auth context as if it’s a primitive.** The module needs identity. Fine. Get it through an adapter (`data/players.ts`), not by importing the host’s `AuthContext` directly. Then the adapter is the only file the boundary test needs to reason about.

## When to upgrade host-folded → lift-out-able

When the module starts to have its own product narrative. If you find yourself talking about the module as a thing — “the scheduling module” not “the scheduling code” — that’s an early signal. If the module reaches a point where you’d consider extracting it (commercial pressure, technical reuse), upgrade the boundary discipline before you do anything else. Adding a boundary test to a module that’s already deeply coupled is harder than adding one to a fresh module.

## Negative consequences

- Boundary tests have maintenance cost. Adding a new integration point requires updating the allow-list and writing the rationale comment. This is *good* — it forces a moment of “do I really want to add this coupling?” — but it’s a real cost.
- Modules with strict boundaries sometimes duplicate patterns that already exist in the host. This is the cost of isolation. Pay it deliberately.
- Module-internal naming conventions create a small dialect. Cross-module reading is slower than within-module reading. Worth it for the modules that earn the boundary; not worth it for the ones that don’t.

## Where this is enforced

[`patterns/universal/module-boundary-tests-with-grep.md`](../patterns/universal/module-boundary-tests-with-grep.md) is the implementation pattern. The deliberate-violation step is in [`patterns/test-correctness/deliberate-violation-verification.md`](../patterns/test-correctness/deliberate-violation-verification.md).
