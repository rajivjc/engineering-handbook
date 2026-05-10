# Principle: Mock/real parity

Every external dependency has a mock path and a real path. Both must stay in sync. The application runs end-to-end against either, and switches based on configuration.

This is more than a testing convenience. It’s a design discipline that pressures every data-layer function toward a clean interface and forces every feature to be testable without infrastructure.

## What “in sync” means

If a function exists in the data layer with signature `getX(args): Promise<X>`, both the mock branch and the real branch must:

- Accept the same arguments
- Return data of the same shape
- Apply the same business rules (filtering, sorting, side effects beyond storage)
- Trigger the same side effects (audit log, push notifications, etc.) when those side effects are part of the function’s contract

Drift is silent. A mock branch that returns a different shape than the real branch will work in development and break in production. The discipline that prevents this is per-feature audit and an explicit “verify mock and real produce equivalent output” step in any session that touches the data layer.

## What this looks like in practice

A typical data-layer function:

```ts
// src/lib/data/bookings.ts
import 'server-only'
import { isSupabaseConfigured } from '@/lib/supabase/env'
import { getServerClient } from '@/lib/supabase/server'
import { mockBookings } from './mock-data'

export async function listBookingsForMember(memberId: string): Promise<Booking[]> {
  if (!isSupabaseConfigured()) {
    return mockBookings.filter(b => b.member_id === memberId)
  }
  const supabase = await getServerClient()
  const { data, error } = await supabase
    .from('bookings')
    .select('*')
    .eq('member_id', memberId)
    .order('start_time', { ascending: true })
  if (error) throw error
  return data
}
```

The mock branch is a single line in this case. For functions with more complex business logic, the mock branch grows in proportion. The point is that both branches exist, both are exercised, and both are kept honest.

## Why this earns its keep

- **Onboarding without infrastructure.** A new developer clones the repo, runs `npm install`, runs `npm run dev`, logs in as a test account. No database setup, no Supabase project, no Stripe configuration. The full app is exerciseable in fifteen minutes.
- **Demos without infrastructure.** Showing the app to a stakeholder doesn’t require a live deployment. Mock fixtures double as the happy path data.
- **Deterministic CI.** Tests run against in-memory fixtures. Test suites are fast (milliseconds per test, not seconds), don’t require a database, don’t suffer from flakiness.
- **Pressure on data-layer design.** Functions whose mock branch is hard to write are functions with too much logic in the data layer. The discipline forces logic up to the action layer where it belongs.
- **Pressure on schema design.** A mock branch can’t keep up with overly-clever schema. The discipline pushes back against database designs that are hard to mirror in memory.

## Anti-patterns

- **“We’ll add the mock branch later.”** Later never comes. Once the function ships, every subsequent feature breaks the mock branch incrementally. Within three sessions, mock mode is broken; within ten, it’s been deleted.
- **“This function only makes sense against the real database.”** Then the function has too much database logic. Move the logic up. The data-layer function should be a query, not a workflow.
- **“The mock data is approximate; close enough.”** Approximate is the failure mode. The mock branch should produce the same shape as the real branch for the same input. Approximation is how drift happens.
- **“We’ll skip mock mode for the LLM call.”** Don’t. Mock the LLM response too. Otherwise every test that exercises the LLM path is non-deterministic and slow. Real LLM calls happen in integration tests, not unit tests.
- **“We have a separate test database.”** That’s an alternative. It works, but it’s slower, requires environment management, and doesn’t give the onboarding-without-infrastructure benefit. Mock-mode is cheaper and gives more.

## Negative consequences

- **Double-implementation cost.** Every data-layer feature ships in two flavors. Add a column, change four places: schema, real query, mock fixture, type. This is a recurring tax on velocity.
- **Silent drift.** A mock branch that’s correct and a real branch that’s broken (or vice versa) won’t be caught by tests. Audits routinely spot-check parity for new code, and the discipline of running both modes during manual testing is non-negotiable.
- **Behavioural gaps.** Some behaviours are real-only — actual database constraints, actual RLS denials, actual atomicity guarantees. Mock mode passes these; real mode fails or behaves differently. The mitigation is per-feature integration tests against a real database, but those are layered on top of mock-mode parity, not a replacement for it.

The cost is real. The benefit is bigger. The discipline of double-implementation has stopped being negotiable for me — it shapes every project I start.

## Where this is enforced

In the handbook’s [`patterns/universal/mock-real-parity.md`](../patterns/universal/mock-real-parity.md), the implementation pattern is documented in full. In each project’s CLAUDE.md, the rule is restated as a hard requirement on every session. In the audit methodology, a session that adds a data-layer function without exercising both branches is flagged as a finding.
