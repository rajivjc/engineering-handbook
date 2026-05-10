# Pure-function test isolation

**Category:** universal
**Applies to:** any computation worth testing — totals, formatters, validators, business-rule evaluators, schedulers.

## Problem

A typical “test” for a business rule looks like:

```ts
it('publishes a week with valid coverage', async () => {
  // Setup: create users, shifts, availabilities
  await db.users.insert({ ... })
  await db.shifts.insert({ ... })
  await db.availabilities.insert({ ... })

  const result = await publishWeekAction(weekId)

  expect(result.success).toBe(true)
  // Plus a dozen assertions about the database state afterwards
})
```

This is an integration test in a unit test’s clothing. It’s slow (requires database setup), brittle (any schema change breaks it), and tests two things at once: the *rule* (does the coverage validator accept this configuration?) and the *plumbing* (does the action layer correctly call the validator and write to the database?). When it fails, you learn that “something is broken” without learning what.

The fix: make the rule a pure function. Test the function in isolation. Test the plumbing separately, far less exhaustively.

## Mechanism

For any business rule that takes inputs and produces a verdict:

```ts
// src/lib/scheduling/coverage-validator.ts
export function validateCoverage(
  shifts: Shift[],
  assignments: Assignment[],
  requirements: CoverageRequirement[]
): CoverageReport {
  // Pure function. No side effects, no dependencies, no `await`s.
  // Given the same inputs, returns the same outputs forever.

  const violations: CoverageViolation[] = []
  for (const req of requirements) {
    const coveringAssignments = assignments.filter(a =>
      shifts.some(s => s.id === a.shiftId && s.dayOfWeek === req.dayOfWeek)
    )
    if (coveringAssignments.length < req.minCount) {
      violations.push({ requirement: req, found: coveringAssignments.length })
    }
  }
  return { ok: violations.length === 0, violations }
}
```

And the test:

```ts
import { validateCoverage } from '@/lib/scheduling/coverage-validator'

describe('validateCoverage', () => {
  it('accepts a fully-staffed week', () => {
    const shifts = [{ id: 's1', dayOfWeek: 'mon' }, { id: 's2', dayOfWeek: 'tue' }]
    const assignments = [{ shiftId: 's1', userId: 'u1' }, { shiftId: 's2', userId: 'u2' }]
    const requirements = [{ dayOfWeek: 'mon', minCount: 1 }, { dayOfWeek: 'tue', minCount: 1 }]
    expect(validateCoverage(shifts, assignments, requirements)).toEqual({ ok: true, violations: [] })
  })

  it('reports a missing-coverage violation on Tuesday', () => {
    const shifts = [{ id: 's1', dayOfWeek: 'mon' }]
    const assignments = [{ shiftId: 's1', userId: 'u1' }]
    const requirements = [{ dayOfWeek: 'mon', minCount: 1 }, { dayOfWeek: 'tue', minCount: 1 }]
    const result = validateCoverage(shifts, assignments, requirements)
    expect(result.ok).toBe(false)
    expect(result.violations).toHaveLength(1)
    expect(result.violations[0].requirement.dayOfWeek).toBe('tue')
  })

  // ... a dozen more cases, each exercising one rule edge
})
```

These tests run in milliseconds. They don’t require a database. They exercise the rule completely. When one fails, you know exactly which rule case broke.

The action that calls the validator is then a thin shell:

```ts
export async function publishWeekAction(weekId: string): Promise<ActionResult> {
  const user = await getCurrentUser()
  if (!hasRole(user, 'manager')) return { error: 'forbidden' }

  const shifts = await getShiftsForWeek(weekId)
  const assignments = await getAssignmentsForWeek(weekId)
  const requirements = await getCoverageRequirements()

  const report = validateCoverage(shifts, assignments, requirements)
  if (!report.ok) return { error: 'coverage_violation', report }

  await rpcSchedulePublishWeek(weekId)
  return { success: true }
}
```

The action’s tests assert plumbing only: “if coverage validation fails, the action returns the error and doesn’t call the RPC.” One or two cases, fast, focused.

## Why this earns its keep

- **Tests run fast enough to run on save.** A coverage validator with 20 test cases takes ~50ms. The integration version takes 2 seconds.
- **Tests survive refactors.** Change the database schema, the action, the controller, the UI — the validator’s tests still pass. The validator is the stable core.
- **Tests document the rule.** A table of cases is the clearest specification of what the rule does. When a contributor argues “the rule should treat Monday differently,” the test cases are the contract.
- **Bugs surface early.** A pure-function test that fails localizes the bug to one function. Compare: an integration test that fails could be the validator, the database setup, the action, the role check, the RPC, or any of a dozen other moving parts.

## What “pure” means in practice

A pure function:

- Returns the same output for the same input, every time.
- Has no side effects (no I/O, no `Date.now()`, no `Math.random()`, no logging, no database calls).
- Doesn’t read mutable global state.
- Doesn’t mutate its arguments.

If your function depends on the current time, take time as a parameter. If it depends on random numbers, take a seed or pass an RNG. If it depends on configuration, take config as a parameter. The function becomes testable without mocking.

```ts
// Bad: depends on Date.now()
function isExpired(token: Token): boolean {
  return token.expiresAt < Date.now()
}

// Good: time is an argument
function isExpired(token: Token, now: number = Date.now()): boolean {
  return token.expiresAt < now
}
// Tests can pass a fixed `now` and verify behaviour at the boundary.
```

## Anti-patterns

**A “pure” function that calls a global logger.** The function is testable in the happy path but fails in a CI environment where the logger isn’t mocked. Either the logger is genuinely a side effect (move it to the action layer) or it’s structured logging that’s part of the contract (return the log entries from the function).

**Functions that do too much.** A “validate coverage” function that also writes to the database isn’t pure. Split it: one function validates, one function writes. Test the validator in isolation; the writer is a thin wrapper.

**Reaching for `vi.mock` instead of refactoring.** If your test needs to mock five things to run, your function isn’t pure. Refactor: extract the pure core, test the core, leave the mocking for the action layer where mocking the database client is appropriate.

**Testing implementation details.** A test that asserts which internal helper was called is testing how the function is structured, not what it does. When you refactor the implementation (without changing behaviour), the test breaks. Test outputs, not implementation.

## What can’t be a pure function

Some logic genuinely depends on side effects:

- The action layer (calls the database).
- HTTP handlers (read the request, write the response).
- Cron triggers (run on a schedule, write to the database).
- The UI layer (renders state to the DOM).

These have their own testing patterns — integration tests, snapshot tests, end-to-end tests. The discipline is to push business rules *out* of these layers and into pure functions, leaving the impure layers as thin shells.

## Negative consequences

- **More files.** A pure-function approach produces more, smaller files than a “do everything in the action” approach. This is mostly upside (each file is focused) but a real readability cost (you have to navigate to find the rule).
- **Argument lists grow.** A pure function takes everything as parameters. If the rule needs ten inputs, the function has ten parameters. Mitigation: group related parameters into objects, or accept that the rule is genuinely complex and the parameter count reflects that.
- **Performance cost from defensive copying.** A function that doesn’t mutate its arguments either trusts callers to clone, or clones on entry. For hot paths, this matters. For business rules that run dozens of times per request, it doesn’t.
- **The discipline doesn’t apply uniformly.** Some code is *intrinsically* about side effects (logging, file I/O). Forcing those to be pure either creates fictional purity or breaks the abstraction. Apply the pattern where the rule is genuinely a function of inputs.

## Related

- `single-source-of-truth-transformer` — a pure function that builds a canonical document for multiple surfaces.
- `principles/mock-real-parity.md` — pure functions are easier to mock-test because there’s nothing to mock.
