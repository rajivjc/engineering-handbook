# Role-write matrix manifest

**Category:** test-correctness
**Applies to:** applications with multi-role authorization where database-level policies and application-level role checks must stay in sync.

## Problem

You have an application with three roles (member, staff, manager). State changes are gated at two layers: the database (RLS policies, fine-grained permissions) and the application (role checks in server actions or API handlers). When you add a new mutation, you must update both layers.

Drift happens. The action layer says “managers can update this record”; the database policy still says “only owners can update this record.” The action runs, the database refuses, the user sees a confusing error. Or the inverse: the action layer forgot to add a check, the database layer accepts the call (because it’s permissive), and a member just edited a manager-only record.

Code review catches some of this. Tests catch some of it. The class of bug — *drift between the two layers* — recurs across projects until you make the matrix explicit.

## Mechanism

For each protected action, declare the expected role(s) explicitly in a manifest. The manifest is the single source of truth for “who can do what.” Tests assert that:

1. Every server action in the manifest has the declared role check at the action layer.
1. Every server action in the manifest is gated by an RLS policy whose `USING` and `WITH CHECK` clauses match the declared roles.
1. Every server action in the codebase appears in the manifest. (No undeclared mutations.)
1. Every RLS policy in the database has a matching action in the manifest. (No orphan policies.)

The manifest itself looks like:

```ts
// tests/security/role-write-matrix.ts
export const ROLE_WRITE_MATRIX = [
  { action: 'createBookingAction', roles: ['member'] },
  { action: 'cancelBookingAction', roles: ['member', 'staff', 'manager'] },
  { action: 'publishWeekAction', roles: ['manager'] },
  { action: 'lockPayrollRunAction', roles: ['owner'] },
  // ... one entry per mutating action
] as const
```

And the test:

```ts
import { describe, it, expect } from 'vitest'
import { ROLE_WRITE_MATRIX } from './role-write-matrix'
import { listAllServerActions } from './helpers/grep-actions'
import { listAllRLSPolicies } from './helpers/parse-migrations'

describe('role-write matrix', () => {
  it('every server action is declared in the matrix', () => {
    const declared = new Set(ROLE_WRITE_MATRIX.map(e => e.action))
    const actual = listAllServerActions()
    const missing = actual.filter(a => !declared.has(a))
    expect(missing).toEqual([])
  })

  it('every action role check matches the declared roles', async () => {
    for (const entry of ROLE_WRITE_MATRIX) {
      const sourceText = readActionSource(entry.action)
      for (const role of entry.roles) {
        expect(sourceText).toMatch(new RegExp(`hasRole\\(.+,\\s*['"]${role}['"]`))
      }
    }
  })

  it('every RLS policy matches the declared roles for its target action', () => {
    const policies = listAllRLSPolicies()
    for (const entry of ROLE_WRITE_MATRIX) {
      const policy = policies.find(p => p.targetAction === entry.action)
      expect(policy).toBeDefined()
      expect(extractRolesFromPolicy(policy)).toEqual(new Set(entry.roles))
    }
  })
})
```

The implementation depends on your stack — grepping action files, parsing migration files, etc. The pattern is the manifest plus the cross-checks, not the specific tooling.

## What this catches

- **A server action is added without a manifest entry.** Test fails: undeclared mutation.
- **A manifest entry is added without an RLS policy.** Test fails: declared role has no database-level enforcement.
- **An RLS policy is added without a manifest entry.** Test fails: orphan policy (probably copy-pasted from elsewhere).
- **A role is added to the action layer but not the database policy.** Test fails: action says manager can do this, RLS still says only owner.
- **A role is added to the database policy but not the action layer.** Test fails: same drift, opposite direction.

This is the load-bearing test for `defense-in-depth-authorization`. Without it, defense-in-depth degrades to defense-in-three-layers-where-one-is-stale.

## Where the manifest lives

In a test file, not in the application code. The manifest is *test* infrastructure — it’s the spec the tests assert against. If you let it drift into the application as a runtime config, you get the worst of both worlds: a runtime check that the application can’t enforce (because the application *is* the thing being checked) and a manifest that’s now load-bearing for production.

## Anti-patterns

**Maintaining the matrix as a comment in the action file.** No automation. Drift happens.

**Asserting the role check via integration tests.** “When a member calls `publishWeekAction`, they get 403.” This is good but doesn’t catch the drift case where the action *and* the policy are both wrong in the same direction (e.g., both have a typo).

**Letting the manifest grow without auditing entries.** Periodically run a deliberate-violation pass: add a fake server action, run the test, confirm it fails. Remove the fake action.

**Treating the manifest as documentation.** It’s not documentation; it’s a contract. When the contract changes, the test changes. Documentation that becomes load-bearing is documentation that drifts.

## Negative consequences

- **The manifest is one more file to maintain.** Every new mutation means one new line in the manifest. The test infrastructure has to keep up with the manifest format.
- **Parsing migrations or action files is fragile.** The grep / regex approach catches most drift but can be defeated by unusual code shapes (decorators, dynamic role names, etc.). Mitigation: code style guidelines that keep the role check in a recognizable shape.
- **The manifest can lie.** Someone can add a manifest entry that doesn’t match what the action actually checks, then add a test exemption. The deliberate-violation discipline is what keeps the manifest honest — periodically violate it and confirm the test catches the violation.

## Where this comes from

After a project shipped a server action whose role check accepted an additional role beyond what the RLS policy allowed (the action said `manager` could do it; the policy said only `owner`), the manifest pattern was added to prevent recurrence. The case study with full details is in `case-studies/01-security-rls-leak.md` (coming in Session 3) — though that incident was more severe than just role drift; it involved the related `rls-null-coalescence-guard` pattern as well.
