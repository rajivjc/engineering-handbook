# N+1 spy regression guards

**Category:** test-correctness
**Applies to:** any code path that was rewritten from a per-row loop to a batched query, where future contributors might accidentally regress to the loop.

## Problem

You ship a feature that loads 50 records. The first cut iterates: for each record, query the database for its details. 50 records → 51 queries (the original + 50 details). Performance is fine in development with two records.

In production, with thousands of records, the page times out. You diagnose, fix it (single batched query that returns all the data joined), and ship. Now you’re done.

Three months later, someone adds a new column to the rendered output. The batched query doesn’t include the column, so they reach for the old per-row query function — it’s still in the codebase — and call it for each row. The page is now N+1 again. Tests pass; the previous regression test passed because the *output is correct*.

The bug recurs because nothing in the codebase prevents it.

## Mechanism

After fixing an N+1, add a regression spy that asserts the per-row function is **never called** during the rendering of the parent. The spy doesn’t check the output; it checks the call shape:

```ts
import { vi } from 'vitest'
import * as detailsModule from '@/lib/data/payslip-details'

it('summary action does not call per-record details function', async () => {
  const spy = vi.spyOn(detailsModule, 'getPayslipDetailsForRecord')

  const result = await getPayslipsSummaryAction(runId)

  expect(result.error).toBeUndefined()
  expect(result.payslips.length).toBeGreaterThan(0)

  // The load-bearing assertion: the per-record function must NEVER be called
  // during the summary path. If a future change reaches for it, this fails.
  expect(spy).not.toHaveBeenCalled()
})
```

The test fails the moment anyone re-introduces the per-row pattern, even if the output looks correct. The cost of a false alarm (someone deliberately wants to call the per-record function) is one comment in the test explaining why this case is allowed.

## Why this earns its keep

- **It’s a future-proofing test.** It doesn’t catch bugs that exist; it catches bugs that don’t exist yet. This is the same shape as a security guard or a convention guard.
- **It survives refactors that the obvious test doesn’t.** A test that asserts “the page renders correctly” passes whether the data was fetched in one query or 50. The spy specifically catches *how* the data was fetched.
- **It’s enforceable mechanically.** Code review catches some N+1 regressions, but not all. A test that runs in CI catches all of them.

## What to spy on

The spy goes on the **per-row function**, not the batched function. The assertion is *negative* (the per-row function is never called), not positive (the batched function is called). Spying on the batched function is fine but doesn’t catch the regression — a contributor could call both, and the positive assertion still passes.

If the per-row function is genuinely needed elsewhere in the codebase (e.g., a single-record API endpoint), keep it. The spy is scoped to the specific call path that should never use it. Multiple spies in different test files cover multiple paths.

## Anti-patterns

**Spying on the batched function and asserting it was called.** Doesn’t catch a contributor adding a per-row call alongside the batched call.

**Removing the per-row function entirely.** Sometimes the right answer. If the only legitimate use was the (now-batched) summary path, delete the per-row function and let TypeScript catch any future re-introduction. The spy approach is for when the per-row function legitimately exists for other use cases.

**Asserting query count instead of function calls.** “Assert the test made ≤ 1 database query” — but every framework has its own query-counting infrastructure, and most don’t expose it cleanly to tests. The function-call spy is portable.

**Forgetting the deliberate-violation pass.** The spy is a `deliberate-violation-verification` candidate: revert the batched fix, run the test, confirm it now reports `expected spy not to have been called, but it was called N times`. If it still passes, the spy is set up wrong (often: `vi.spyOn` on the wrong import path).

## Where this is enforced

After every N+1 fix, the regression spy is added in the same commit as the fix. The commit message explicitly notes the deliberate-violation pass, e.g., “Verified: reverting the batched fix produces N spy calls and fails the test.”

## Negative consequences

- **The spy is brittle to import refactors.** If someone moves the per-row function to a new file, `vi.spyOn(detailsModule, 'getPayslipDetailsForRecord')` silently stops working — the spy is on a different module than the one being called. Mitigation: prefer dependency injection where feasible, or include a test fixture that proves the spy is on the right target.
- **Spies don’t catch indirection.** If the per-row function is called via a wrapper, the spy on the wrapper passes; the spy on the underlying function fires. Pick the layer that’s load-bearing for the regression you care about.
- **The pattern is N+1-specific.** It doesn’t generalize to all performance regressions. For “this query should use the index,” the right test is an EXPLAIN-based assertion, not a spy. For “this endpoint should respond in <200ms,” the right test is a benchmark, not a spy. Use the right tool.

## Verification

For any N+1 spy, do the deliberate-violation pass: revert the batched fix, run the test, confirm it fails with a “spy was called N times” message. Restore the fix. Document this in the commit.
