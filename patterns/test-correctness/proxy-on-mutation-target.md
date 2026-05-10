# Proxy-on-mutation-target

**Category:** test-correctness
**Applies to:** atomicity tests for multi-step mutations, where you need the rollback path to actually run.

## Problem

A typical atomicity test wants to assert: “if step 2 fails, step 1’s mutation should be rolled back.” The instinctive shape is:

```ts
it('rolls back week publish if shift assignment fails', async () => {
  const stub = vi.spyOn(actionsModule, 'assignStaffToShifts').mockImplementation(() => {
    throw new Error('boom')
  })

  await expect(publishWeekAction(weekId)).rejects.toThrow('boom')

  // Assert no published week exists
  const week = await fetchWeek(weekId)
  expect(week.status).toBe('draft')
})
```

This test passes whether the rollback is correct, broken, or absent. The reason: the throw fires before any mutation happens. `assignStaffToShifts` is never *called* in the way that mattered — its internal mutation never ran. There was nothing to roll back.

If you revert the rollback logic (or never wrote it), this test still passes, because the bug class it’s meant to catch never gets exercised.

## Mechanism

Inject the failure *inside* the target of the mutation, not at the function-call boundary. The target — the database client, the HTTP fetcher, whatever actually performs the side effect — gets wrapped in a Proxy that throws on the Nth call to a specific method:

```ts
function proxyMutationTarget<T extends object>(
  target: T,
  config: { failOnNthCall: number; methodName: keyof T }
): T {
  let callCount = 0
  return new Proxy(target, {
    get(obj, prop, receiver) {
      const value = Reflect.get(obj, prop, receiver)
      if (prop === config.methodName && typeof value === 'function') {
        return function (...args: unknown[]) {
          callCount += 1
          if (callCount === config.failOnNthCall) {
            throw new Error(`Injected failure on call ${callCount} to ${String(prop)}`)
          }
          return value.apply(obj, args)
        }
      }
      return value
    },
  })
}
```

Used in a test:

```ts
it('rolls back week publish if shift assignment fails', async () => {
  // Wrap the database client. The first mutation (mark week published) succeeds.
  // The second mutation (insert shift assignments) throws.
  const proxiedClient = proxyMutationTarget(dbClient, {
    failOnNthCall: 2,
    methodName: 'from',
  })

  await expect(
    publishWeekAction(weekId, { client: proxiedClient })
  ).rejects.toThrow(/Injected failure/)

  // Now this assertion is meaningful: the first mutation DID run; the rollback
  // had to execute to make `week.status` come back as 'draft'.
  const week = await fetchWeek(weekId)
  expect(week.status).toBe('draft')
})
```

Now the test exercises the actual rollback path. Revert the rollback logic and the test fails. Add a deliberate violation (skip the rollback entirely) and the test fails. The bug class is now genuinely caught.

## Why the proxy and not just `vi.spyOn`

`vi.spyOn` and similar tools intercept at the function-call boundary. Calling a wrapped function does *not* run any of the function’s body unless the spy explicitly forwards. The proxy approach is different: it wraps the actual mutation target (the database client) and lets calls succeed transparently *until* the chosen call point, where it throws. The first call really mutates; the second throws after the mutation is in flight.

For atomicity tests specifically, this distinction is what makes the test meaningful versus performative.

## When to use this

- **Multi-step mutations where steps share a transaction or rely on application-level “transaction” patterns.** The test for “if step N fails, steps 1..N-1 are rolled back” needs steps 1..N-1 to actually have run.
- **External-side-effect tests where you want the prior side effects to commit before the failure.** “If the Stripe charge fails after the database row is inserted, does the row get marked failed?” needs the row insert to complete.
- **Idempotency tests where the second call needs to find the first call’s traces.** “If we crash mid-way and retry, do we double-charge?” The proxy lets the first attempt commit before throwing.

## Anti-patterns

**Mocking the entire database client to return canned responses.** The mock doesn’t actually mutate anything, so subsequent assertions are reading the mock’s internal state, not the database’s. The “rollback” is a no-op against a no-op. The test asserts symbols, not behaviour.

**Throwing in the action under test directly.** “Make `publishWeekAction` throw at line 47” — but you can’t, because that requires modifying production code for the test. The proxy approach injects the failure from outside, leaving production code untouched.

**Using the proxy to throw on the first call.** That’s the same as throwing at the boundary; no prior mutation runs. The Nth-call discipline is the load-bearing detail.

## Negative consequences

- The proxy adds 30-40 lines of test infrastructure. Worth it for the load-bearing atomicity tests; overkill for tests that don’t engage the rollback path.
- Proxies are subtle. A reader unfamiliar with the pattern needs to understand that the wrapped call really does mutate; this is an unusual shape for a test fixture. Inline comments help.
- This pattern doesn’t catch bugs in the rollback *direction* (e.g., rollback that runs the wrong SQL). For that, you also need an integration test against a real database. Layer them.

## Verification

This pattern is one of the canonical examples for `deliberate-violation-verification`. After writing a test using the proxy, revert the rollback logic, run the test, and confirm it fails with a message about the partially-applied state. Restore. Then mutate the proxy to fail on call 1 instead of call N — confirm the test still passes (because no rollback was needed) — to prove the proxy’s call-count parameter is doing real work.
