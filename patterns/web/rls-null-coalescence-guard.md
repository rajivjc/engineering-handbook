# RLS NULL-coalescence guard

**Category:** web (Postgres + Row-Level Security)
**Applies to:** any Postgres-backed application using RLS to enforce authorization at the database layer.

## Problem

A common RLS policy shape uses a helper function to check the caller’s role:

```sql
create policy "managers can update records"
  on records for update
  using (public.get_user_role() = 'manager');
```

This works correctly when `get_user_role()` returns a value. The problem is when it returns NULL.

In Postgres, `NULL = 'manager'` evaluates to `NULL`, not to `false`. NULL in a USING clause means “the row is filtered out” — but NULL combined with `OR` propagates differently than people expect.

Consider a policy like:

```sql
create policy "managers can update or anyone can update giveaway records"
  on records for update
  using (
    public.get_user_role() = 'manager'
    or kind = 'giveaway'
  );
```

For a non-staff caller (`get_user_role()` returns NULL), this evaluates to:

```
NULL OR (kind = 'giveaway')
```

Postgres’s three-valued logic: `NULL OR true = true`. So *any* caller — authenticated or not — can update *any row* where `kind = 'giveaway'`, regardless of their role. The policy authors usually intended “managers can update anything, plus a special carve-out for giveaway records that even non-managers can claim.” The actual policy lets everyone update giveaway records.

This is a real class of leak. It’s not theoretical; it’s been shipped to production by competent teams who reviewed the policy.

## Mechanism

Two layers of defense:

### Layer 1: write the policy defensively

Always coalesce NULL to a known-bad value before comparing:

```sql
create policy "managers can update or anyone can update giveaway records"
  on records for update
  using (
    coalesce(public.get_user_role(), '') = 'manager'
    or kind = 'giveaway'
  );
```

Or use IS DISTINCT FROM:

```sql
... using (
  public.get_user_role() = 'manager'
  or (kind = 'giveaway' and current_setting('request.jwt.claim.sub', true) is not null)
)
```

The second form additionally requires the caller to be authenticated (Supabase puts the user ID in the JWT claim). For Tigress and similar Supabase apps, this is often what you actually want.

### Layer 2: a convention guard test catches policies that don’t follow the rule

```ts
// tests/security/rls-null-coalescence-guard.test.ts
import { readMigrationFiles, parsePolicies } from './helpers/migrations'

const ALLOWED_BARE_FUNCTION_REFERENCES = [
  // Files where bare `get_user_role() = ...` is reviewed and known safe.
  // Typically: policies where the function call is the only condition (no OR
  // branches) AND the function has been verified to never return NULL for
  // authenticated users.
  { policy: 'admin_full_access', reason: 'function never returns NULL for service-role calls' },
]

describe('RLS NULL-coalescence guard', () => {
  it('every role-checking function call in an OR branch is coalesced', () => {
    const policies = parsePolicies(readMigrationFiles())

    const violations: string[] = []
    for (const policy of policies) {
      // Look for `get_user_role()` (or similar) without coalesce/IS DISTINCT FROM
      // when the policy contains an OR.
      if (!hasOrBranch(policy.using)) continue
      const bareReferences = findBareFunctionReferences(policy.using)
      for (const ref of bareReferences) {
        const isAllowed = ALLOWED_BARE_FUNCTION_REFERENCES.some(
          a => a.policy === policy.name
        )
        if (isAllowed) continue
        violations.push(`${policy.name}: ${ref}`)
      }
    }

    if (violations.length === 0) return

    const message = [
      `RLS NULL-coalescence violations (${violations.length}):`,
      ...violations.map(v => `  ${v}`),
      '',
      'Bare role-function references in OR branches can leak when the function returns NULL.',
      'Wrap with coalesce(<fn>(), \'\') = ... or use IS DISTINCT FROM.',
      'See patterns/web/rls-null-coalescence-guard.md.',
    ].join('\n')
    throw new Error(message)
  })
})
```

The implementation depends on your migration format and how you can parse SQL. A naive regex catches most cases:

```ts
// Match a function call to get_user_role / similar that's directly compared
// to a string, NOT wrapped in coalesce or IS DISTINCT FROM.
const BARE_REFERENCE = /\b(get_user_role|get_staff_role|current_role)\s*\(\s*\)\s*=/g
```

Refine the regex for your codebase’s helper function names. The key property: the test fails if anyone adds a bare function comparison in an OR-branched policy without an allow-list entry.

## Why this earns its keep

- **Catches a class of bug that code review misses.** RLS policies are SQL, often with multi-line conditions. Reading a 5-line USING clause and noticing the NULL-coalescence issue is hard. The test catches it mechanically.
- **Pressure on policy design.** When you have to think about NULL coalescence at write-time (because the test is going to fire if you don’t), you write better policies.
- **Pairs with `role-write-matrix-manifest`.** The matrix test catches drift between action-layer and database-layer authorization. This test catches a specific implementation defect within the database layer. Layered.

## What the bug story looks like

A real project shipped a policy that gave non-staff users the ability to update any record where the kind matched a special value. The policy looked correct on review — it had a manager check and an OR-branch carve-out. The leak was the NULL-coalescence issue described above.

The policy guard test that was supposed to catch this was passing because it only checked “does the role-checking function appear *somewhere* in the policy body.” It did. The bug was in *how* it appeared (in an OR branch without coalescence), and the original test didn’t analyze that.

The fix:

1. Strengthen the test to parse the policy condition into AST-like form (or use a regex that catches OR-branched bare references specifically).
1. Add a deliberate-violation pass to the test setup: write a known-leaky policy in a test fixture, confirm the test catches it.
1. Audit existing policies for the pattern; rewrite any that have the same shape.
1. Document this as a pattern (this file).

The case study with full incident details is in `case-studies/01-security-rls-leak.md` (coming in Session 3).

## Anti-patterns

**Trusting that `get_user_role()` always returns a value.** It returns NULL for unauthenticated calls, anonymous calls, and any call where the function’s internal logic hits an unexpected path. Defensively assume NULL is possible.

**Using `=` directly against a function result in any boolean expression.** Not just OR — `(get_user_role() = 'manager') AND (some_condition)` is also affected: if the role function returns NULL, the whole expression is NULL, which is *false* for AND but *true* for the row visibility test in some configurations. Coalesce.

**Writing the test without the deliberate-violation pass.** A test that runs without confirming it would catch the bug is just hopeful regex. Always add a known-bad fixture and assert the test fails on it.

**Allow-listing without inspection.** “Add this policy to the allow-list because the test fires on it” — without confirming the policy is actually safe — defeats the test. Every allow-list entry should explain why the bare reference is safe (e.g., “the function never returns NULL for service-role callers”).

## Negative consequences

- **The test is fragile to migration format changes.** Parsing SQL from migrations requires knowing your migration format. If you switch from raw SQL files to a migration framework that wraps the SQL, the parser needs updating.
- **False positives on policies that are genuinely safe.** Some policies use bare function references in contexts that aren’t OR-branched (e.g., an INSERT policy with a single role check). The test should distinguish these.
- **The convention-guard pattern only catches the shapes you encode.** A novel form of leak (e.g., NULL through a CASE expression) isn’t caught. The pattern catches the most common form; layering with code review catches the rest.

## Verification

Run a deliberate-violation pass on the test:

1. Write a known-leaky policy in a test fixture migration:
   
   ```sql
   create policy "deliberately_unsafe" on test_records for update
     using (get_user_role() = 'manager' or kind = 'public');
   ```
1. Run the test. Confirm it fails with a message naming this policy.
1. Remove the unsafe policy. Confirm green.
1. Add a policy that uses coalesce:
   
   ```sql
   create policy "deliberately_safe" on test_records for update
     using (coalesce(get_user_role(), '') = 'manager' or kind = 'public');
   ```
1. Run the test. Confirm green.

This proves the test is engaging with policy syntax, not passing because nothing matched.

## Related

- `principles/defense-in-depth-authorization.md` — the principle this pattern supports.
- `convention-guard-tests` — the general shape this is a specialization of.
- `role-write-matrix-manifest` — the cross-layer test that catches drift between action and database authorization.
- `deliberate-violation-verification` — the discipline that proves the test catches what it claims to.
