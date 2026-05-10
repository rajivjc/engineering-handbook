# Deliberate-violation verification

**Category:** test-correctness
**Applies to:** any test that exists to catch a class of bug — security guards, atomicity tests, regression spies, convention guards.

## Problem

A test that’s supposed to catch a bug only earns trust if you can show it fails when the bug is reintroduced. A test that “always passes” — passes whether the underlying logic is correct, broken, or absent — is functionally untested. The author wrote the test, the test went green, and nothing was actually verified.

This isn’t a hypothetical. Three sessions in a row on a real project shipped tests that passed regardless of whether the underlying fix was working. Each was caught by the discipline below; none would have been caught by reading the test carefully or by code review.

## Mechanism

For any test that exists to catch a class of bug:

1. Land the test alongside the fix.
1. Revert the fix (e.g., `git stash` the fix, comment out the corrected logic, or restore the buggy version inline).
1. Run the test in isolation.
1. **Confirm the test FAILS — and fails for the right reason.** Read the failure message. It should describe the bug, not a tangentially-related symptom.
1. Restore the fix.
1. Run the test again to confirm green.
1. Document the deliberate-violation pass in the commit message or session notes.

If the test passes when the fix is reverted, the test is broken. The fix doesn’t ship. Either rewrite the test, change what it asserts, or change the level at which it runs — until it engages with the actual bug.

## What “the right reason” means

A test can fail for the wrong reason and still look like it caught the bug:

```ts
// A test that's supposed to verify role-based access control:
it('non-managers cannot publish week', async () => {
  const result = await publishWeekAction(weekId, { user: nonManager })
  expect(result.error).toBe('forbidden')
})
```

If you revert the role check and this test fails with `expected 'forbidden' but got 'database_error'` because `nonManager.id` doesn’t exist in the test database, the test “caught” the regression but for a reason unrelated to authorization. Re-introduce the role check with a typo in the role name, and the test stays green for the wrong reason.

The deliberate-violation pass should produce a failure message that names the actual bug class.

## Anti-patterns

**Throw injected too early.** Atomicity tests that throw at the function-call boundary (before any mutation has happened) don’t engage rollback. The throw triggers, no mutation occurred, “rollback” is a no-op. Test passes whether rollback is correct, broken, or absent. See `proxy-on-mutation-target` for the fix.

**Regex matches that pass for irrelevant reasons.** A guard test that checks “does function `X` appear *somewhere* in the body” misses the case where `X` appears in an unrelated branch. The bug ships in a branch the regex didn’t care about.

**Tautological assertions.** `expect(x).toBeTruthy()` after `const x = "hello"`. Always passes. Easy to write accidentally when refactoring.

**Tests that exercise the happy path only.** “I tested that valid input works” doesn’t exercise the bug class “invalid input causes a leak.”

**Snapshot tests as security guards.** A snapshot of a SQL policy will fail if the policy text changes — but won’t tell you whether the change makes the policy stricter or laxer. The snapshot caught a *change*, not a *bug*.

## When this is mandatory vs. nice-to-have

**Mandatory.** Any test for: RLS policies, auth checks, atomicity / rollback behaviour, regression spies (e.g., “this batched function must never call the per-row function”), convention guards (e.g., “no hardcoded timezone strings outside this allow-list”).

**Nice-to-have.** Standard unit tests for pure functions are usually fine without the deliberate-violation step — the test’s failure mode is obvious from the assertion. Apply the discipline when the test exists to catch *future* bugs that don’t exist yet.

## Why this earns its keep despite the cost

The deliberate-violation step itself is fast — under a minute per test. The thinking that goes with it (what to revert, what to leave in place) is the slow part. For security-critical changes, audit time roughly doubles.

The cost is bounded. The cost of a security guard that doesn’t catch its target class is unbounded — that’s how data leaks ship past code review.

## Where this comes from

This pattern was formalized after a project shipped three tests in a row that passed regardless of whether the underlying fix was correct. Documented as a stand-alone discipline in [`decisions/examples/deliberate-violation-verification.md`](../../decisions/examples/deliberate-violation-verification.md). The associated case study with full details of one incident is in `case-studies/01-security-rls-leak.md` (coming in Session 3).
