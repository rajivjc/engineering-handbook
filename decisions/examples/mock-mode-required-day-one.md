## ADR-002: Mock mode required from day one with full feature parity

**Status:** Accepted
**Date:** 2026-04-11 [date approximate — established in the initial scaffold]

**Context**
The conventional pattern is “build against a development database; add mocks later for unit tests.” This makes onboarding slow, makes development brittle to schema drift, and turns “demo this to a stakeholder” into a deployment task. New developers spending half a day on Supabase setup is a tax on every new contributor.

**Decision**
Every data-layer function in `src/lib/data/` (and the equivalent in each module: `src/competitions/data/`, `src/scheduling/data/`, `src/scheduling/payroll/data/`) checks `isSupabaseConfigured()` and branches between a real Postgres path and an in-memory mock path. Both paths must stay in sync. New features are required to ship working in *both* modes; this is enforced per session prompt and verified during the audit pass.

**Consequences**

- **Onboarding without infrastructure.** Clone, `npm install`, `npm run dev`, log in as a test account. Total setup time: under fifteen minutes. No database, no Supabase project, no Stripe keys required.
- **Demos without infrastructure.** Showing the app to a stakeholder doesn’t require a live deployment or a populated database. Mock fixtures double as the “happy path” data set.
- **Deterministic CI.** Tests run against in-memory fixtures. Test suites are fast, don’t suffer from flakiness, and don’t require an external database.
- **Pressure on data-layer design.** Functions whose mock branch is hard to write usually have too much logic in the data layer. The discipline forces logic up to the action layer where it belongs.
- **Negative: double-implementation cost.** Every data-layer feature carries a recurring tax. Add a column, change four places: schema, real query, mock fixture, type. Across the project lifetime this is a meaningful velocity tax.
- **Negative: silent drift.** A mock branch that’s correct and a real branch that’s broken (or vice versa) won’t be caught by mock-mode tests. Audits routinely spot-check parity for new code; manual testing in real mode after every session is non-negotiable.
- **Negative: behavioural gaps.** Some behaviours are real-only — actual database constraints, actual RLS denials, actual atomicity guarantees. Mock mode passes these; real mode fails or behaves differently. Mitigation: per-feature integration tests against a real database, layered on top of mock-mode parity, not a replacement for it.
