# Module boundary tests with grep

**Category:** universal
**Applies to:** modules within a monorepo or single repo that have an explicit “lift-out-able” stance — i.e., the module declares an extraction-friendly boundary with the host application.

This is the implementation pattern for the `principles/module-boundary-discipline.md` stance “lift-out-able.” Modules that are host-folded don’t need this; the principle file covers when each stance applies.

## The shape

Two grep-based tests that run as part of the test suite. They scan every source file in the codebase, find imports, classify each import as inside-the-module or outside-the-module, and fail if any import crosses the boundary except via the declared integration points.

```ts
// tests/competitions/boundary.test.ts
import { execSync } from 'node:child_process'
import path from 'node:path'

const MODULE_PATH = 'src/competitions/'

// Files outside the module that ARE allowed to import from inside the module.
// Each entry must have a reason — anonymous allow-list entries rot.
const OUTSIDE_TO_INSIDE_ALLOWED = [
  { path: 'src/app/(community)/competitions', reason: 'route pages render module UI' },
  { path: 'src/app/(community)/leagues',      reason: 'route pages render module UI' },
  { path: 'src/components/ui/StaffSidebar.tsx', reason: 'navigation entry' },
]

// Files inside the module that ARE allowed to import from outside the module.
// These are the integration adapters — the only points where the module
// touches host primitives.
const INSIDE_TO_OUTSIDE_ALLOWED = [
  { path: 'src/competitions/data/players.ts', reason: 'identity adapter' },
  { path: 'src/competitions/audit.ts',         reason: 'audit log adapter' },
  { path: 'src/competitions/events.ts',        reason: 'event hook adapter' },
]

interface Import {
  fromFile: string
  toModule: string
  line: number
}

function listAllImports(): Import[] {
  // Match: import ... from 'X'  or  import 'X'
  // (Adjust for your build system if it accepts more shapes.)
  const cmd = `grep -rn -E "from ['\\\"]@?/" src/ --include='*.ts' --include='*.tsx' || true`
  const output = execSync(cmd, { encoding: 'utf-8' }).trim()
  if (!output) return []
  return output.split('\n').map(line => {
    const [fromFile, lineStr, ...rest] = line.split(':')
    const text = rest.join(':')
    const match = text.match(/from\s+['"]([^'"]+)['"]/)
    return {
      fromFile,
      toModule: match?.[1] ?? '',
      line: parseInt(lineStr),
    }
  }).filter(i => i.toModule)
}

function isInsideModule(filePath: string): boolean {
  return filePath.startsWith(MODULE_PATH)
}

function importTargetIsInsideModule(toModule: string): boolean {
  // Resolve the import path against your alias config.
  // Here we assume `@/competitions/...` and `src/competitions/...` both count.
  return toModule.startsWith('@/competitions/') || toModule.includes('competitions/')
}

describe('competitions module boundary', () => {
  const imports = listAllImports()

  it('outside files do not import from inside the module unless allow-listed', () => {
    const violations = imports.filter(i => {
      if (isInsideModule(i.fromFile)) return false
      if (!importTargetIsInsideModule(i.toModule)) return false
      const allowed = OUTSIDE_TO_INSIDE_ALLOWED.some(
        entry => i.fromFile.startsWith(entry.path)
      )
      return !allowed
    })

    if (violations.length === 0) return

    const message = [
      `Found ${violations.length} unauthorized import(s) from host into competitions module:`,
      ...violations.map(v => `  ${v.fromFile}:${v.line} → ${v.toModule}`),
      '',
      'How to fix:',
      '  - Route this through one of the existing integration adapters in INSIDE_TO_OUTSIDE_ALLOWED',
      '  - OR if a new integration point is justified, add an entry to OUTSIDE_TO_INSIDE_ALLOWED with a reason',
      '',
    ].join('\n')
    throw new Error(message)
  })

  it('inside files do not import host code unless allow-listed as integration adapter', () => {
    const violations = imports.filter(i => {
      if (!isInsideModule(i.fromFile)) return false
      if (importTargetIsInsideModule(i.toModule)) return false
      // Skip third-party imports (no `@/` prefix and no relative path).
      if (!i.toModule.startsWith('@/') && !i.toModule.startsWith('.')) return false
      const allowed = INSIDE_TO_OUTSIDE_ALLOWED.some(
        entry => i.fromFile.startsWith(entry.path)
      )
      return !allowed
    })

    if (violations.length === 0) return

    const message = [
      `Found ${violations.length} unauthorized import(s) from competitions module into host:`,
      ...violations.map(v => `  ${v.fromFile}:${v.line} → ${v.toModule}`),
      '',
      'Modules with the lift-out-able stance import host code only via the declared',
      'adapter files. To add a new integration point, add to INSIDE_TO_OUTSIDE_ALLOWED',
      'with a justification.',
      '',
    ].join('\n')
    throw new Error(message)
  })
})
```

The exact mechanics depend on your build system (path aliases, module resolution). The pattern is the same: grep, classify, allow-list with reasons, fail with a clear message.

## What the allow-list captures

The allow-list isn’t a list of files that bypass the rule. It’s a list of files that *are* the integration points. There’s a difference: every entry in the allow-list represents a deliberate architectural choice that someone could later extract or replace. An undisciplined allow-list (entries added casually as new features land) reads the same as a disciplined one — until you try to extract the module and discover the boundary’s been eroded.

The discipline: every allow-list entry has a one-line reason. When a contributor wants to add an entry, the PR review asks whether the reason is real. If the answer is “I just need this to compile,” the answer is to refactor, not to add to the allow-list.

## What this catches

- A new feature that imports a module-internal helper from a host page. Test fails: route the access through the adapter or add a new integration point with rationale.
- A module file that imports a host’s shared utility. Test fails: either the utility belongs in the module too, or the module needs an adapter to use the host’s utility.
- A future maintainer who doesn’t know the module is lift-out-able and adds imports freely. Test fails on their PR.
- A refactor that moves a host file into the module’s directory but doesn’t update its imports. Test fails: the file is now “inside” but imports as if it were outside.

## When to use this vs. just a directory convention

The rule “files in `src/competitions/` shouldn’t import from outside” can be enforced by code review alone. Sometimes that’s enough. The grep test earns its keep when:

- The module has commercial value as a standalone unit (you might extract it).
- Multiple contributors work on the codebase.
- The codebase has been around long enough that the original intent could be forgotten.
- The module has its own domain language and accidentally importing host concepts pollutes it.

For a small module with one contributor and no extraction plans, the grep test is overkill. For everything else, it’s the discipline that prevents the boundary from rotting silently.

## Anti-patterns

**Allow-list with no reasons.** Adding entries becomes free. The boundary erodes as fast as anyone adds entries.

**Allow-listing entire directories.** “All files in `src/components/` can import from inside the module.” This is the boundary giving up. If multiple files genuinely need to integrate, define a single new adapter and route them through it.

**Tests that pass by accident.** Run a deliberate-violation pass: deliberately add an unauthorized import, run the test, confirm it fails. If the test passes, the regex isn’t catching the shape you think it is.

**Module that imports the host’s auth context as if it’s a primitive.** The module needs identity. Fine. Build a `data/players.ts` adapter that resolves a player from the host’s identity system. Then `players.ts` is the only file that imports the auth context. Don’t allow-list the auth context everywhere it’s used.

**Forgetting to scan for `import type`.** TypeScript-only imports (`import type { X } from '@/foo'`) are sometimes excluded from the regex. They’re still architectural coupling. Include them.

## Negative consequences

- **Maintenance cost on the allow-list.** When a file is renamed or refactored, the allow-list might reference a stale path and stop catching real violations. Mitigation: the test should verify each allow-list entry resolves to an actual file (delete or fix entries that don’t).
- **Slower test suite.** Grepping the source tree adds 1-3 seconds to the test run. For a fast project, this is noticeable. Mitigation: run boundary tests in a separate suite that doesn’t run on every save.
- **False positives from edge syntax.** `import('@/competitions/foo')` (dynamic import) might be missed by a regex that expects `import ... from ...`. Catch all the shapes you actually use; document the rest.
- **The pattern doesn’t apply to host-folded modules.** If your module reaches into host primitives freely (because that’s the stance you chose), the boundary test would generate dozens of legitimate violations. Don’t add the test for host-folded modules; the stance choice is the discipline.

## Verification

After setting up a boundary test, run a deliberate-violation pass:

1. Add an unauthorized import (e.g., a host page importing a module-internal helper directly, not through the adapter).
2. Run the test. Confirm it fails with a message naming the import.
3. Remove the violation. Confirm green.
4. Add an unauthorized import to an allow-listed file. Confirm green (the allow-list works).

This proves the test catches what it claims to catch. Without the deliberate-violation pass, you have a test that might pass for the wrong reasons.

## Related

- `principles/module-boundary-discipline.md` — when to choose lift-out-able vs. host-folded.
- `convention-guard-tests` — the general pattern this is a specialization of.
- `deliberate-violation-verification` — proving the boundary test catches real violations.
