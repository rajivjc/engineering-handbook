# Mock/real parity

**Category:** universal
**Applies to:** any application with an external dependency (database, API, queue) where development without that dependency is desirable.

This is the implementation pattern for the principle of the same name. The principle (`principles/mock-real-parity.md`) covers the *why*. This file covers the *how*.

## The shape

Every data-layer function has the same skeleton:

```ts
// src/lib/data/bookings.ts
import 'server-only'
import { isSupabaseConfigured } from '@/lib/supabase/env'
import { getServerClient } from '@/lib/supabase/server'
import { mockBookings } from './mock-data'

export async function listBookingsForMember(memberId: string): Promise<Booking[]> {
  if (!isSupabaseConfigured()) {
    // Mock branch: filter the in-memory fixtures the same way the SQL would
    return mockBookings
      .filter(b => b.member_id === memberId)
      .sort((a, b) => a.start_time.localeCompare(b.start_time))
  }

  // Real branch
  const supabase = await getServerClient()
  const { data, error } = await supabase
    .from('bookings')
    .select('*')
    .eq('member_id', memberId)
    .order('start_time', { ascending: true })
  if (error) throw error
  return data ?? []
}
```

The branches diverge only in storage. The filter, the sort, the shape of the return — identical. The mock branch is an implementation of the same query against an in-memory list.

## Required infrastructure

**A configuration check.** `isSupabaseConfigured()` returns `false` when env vars are missing or set to placeholder values. Make this check *strict* — empty string is unconfigured, the literal placeholder string `your-supabase-url-here` is unconfigured, anything else is configured. Don’t allow partial configuration.

**A mock fixture set.** A module that exports the in-memory data the application’s mock branch reads from. Treat this as production data: it must satisfy all the integrity rules the real database enforces (foreign keys, unique constraints, etc.). Inconsistent fixtures generate bugs that look like real bugs.

**A mock auth context.** Logging in works against the mock too. Define a small set of mock test accounts (one per role) and treat them as real users — they own real (mock) records, they have real (mock) permissions, they can do everything a real account can.

**A clear toggle.** A reader of the codebase should be able to tell, in five seconds, what determines mock vs. real. The check usually lives at the bottom of a `supabase/env.ts` file and is referenced from every data-layer function. Inlining the check (`if (process.env.NEXT_PUBLIC_SUPABASE_URL)`) at every call site invites drift.

## Side effects in mock mode

The data-layer function is the easy part. Side effects (push notifications, audit logs, payment webhooks) are harder.

- **Audit log writes.** In mock mode, write to an in-memory audit log array. Surface it via a debug page so you can verify side effects fired.
- **Push notifications.** In mock mode, console.log the payload. Don’t hit the real push service.
- **Payment webhooks.** In mock mode, expose a UI button to “simulate webhook” with realistic payload. Don’t try to actually charge.
- **Cron jobs.** In mock mode, expose a manual-trigger button or run on a faster timer.

The discipline: every side-effect path has a mock implementation that lets you verify it would have fired, without it actually firing.

## What to test in each mode

- **Unit tests run against mock mode.** Fast, deterministic, no external dependencies. The default `npm run test` exercises mock paths.
- **Integration tests against a real database.** A separate test suite (`npm run test:integration`) that requires `.env.test` with real Supabase credentials. Run before deploys; not required for every PR.
- **End-to-end tests can run either.** Mock for quick smoke; real for full verification.

The goal isn’t to test only mock or only real. It’s to make mock the default fast path and reserve real for when you need it.

## Anti-patterns

**Mock branches that return canned static data regardless of input.** `listBookingsForMember(memberId)` that always returns the same five bookings even when called with different `memberId` values. The mock is no longer a faithful implementation; it’s a stub. The next time someone tests “filter by member” via mock mode, the filter looks broken because the stub doesn’t filter.

**Mock branches that diverge in business logic.** “In mock mode, skip the duplicate check; in real mode, enforce it.” The application’s behaviour now depends on the configuration. Tests against mock mode pass; production fails for cases the mock didn’t cover.

**Mock branches that don’t go through the same transformer.** If the real branch runs the result through `transformBooking()` and the mock branch returns raw fixture data, you’ve broken `single-source-of-truth`. Run the same transformer in both branches.

**Mock branches that always succeed.** Real databases throw — connection errors, constraint violations, deadlocks. The mock should be able to simulate failure paths. A flag like `MOCK_FAIL_ON=createBooking` lets tests exercise error handling.

**Letting the mock data drift from the schema.** When you add a column to the real schema, you add it to the mock fixtures too. Otherwise the mock branch’s return shape no longer matches the real branch’s return shape, and downstream code that uses the new column breaks in production but not in tests.

## Negative consequences

- **Double-implementation cost.** Every data-layer feature ships in two flavours. Adding a column means schema migration + real query update + mock fixture update + type definition update. The tax compounds.
- **Silent drift.** A mock branch that’s correct and a real branch that’s broken (or vice versa) won’t be caught by mock-mode tests. Audits routinely spot-check parity for new code, and manual testing in real mode after every session is non-negotiable.
- **Behavioural gaps.** Some behaviours are real-only — actual database constraints, actual atomicity, actual race conditions. Mock mode passes; real mode fails or behaves differently. Mitigation: integration tests against a real database, layered on top of mock-mode parity.

## Verification

For any new data-layer function: run the application against mock mode, confirm the feature works. Run against real mode, confirm the feature works the same way. Spot-check the mock branch’s logic mirrors the real branch’s filter/sort/aggregation rules.

For audit-time spot checks: pick a function added in the session being audited, read both branches, confirm they apply the same business rules. If they don’t, the audit logs a finding.

## Related

- `principles/mock-real-parity.md` — the principle behind this pattern.
- `single-source-of-truth-transformer` — the pattern that prevents the mock and real branches from formatting their results differently.
