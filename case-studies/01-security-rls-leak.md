# Case study 01: A row-level security leak hidden behind a NULL

**Category:** security
**Patterns referenced:** `patterns/web/rls-null-coalescence-guard.md`, `principles/defense-in-depth-authorization.md`
**Severity:** High (cross-tenant data exposure)
**Time to detect:** ~6 weeks after the buggy code shipped
**Time to fix once detected:** Under an hour

## Context

A multi-tenant content management application uses Postgres with row-level security (RLS) to isolate tenants. Each row in every relevant table has a `tenant_id` column, and every table has an RLS policy that boils down to "you can only see rows where `tenant_id` matches yours."

The application is built on Supabase. The user's tenant is stored in a JWT claim, retrievable in SQL via a custom function:

```sql
create or replace function public.current_tenant_id()
returns uuid
language sql
stable
as $$
  select nullif(
    current_setting('request.jwt.claims', true)::json->>'tenant_id',
    ''
  )::uuid
$$;
```

The RLS policy on the `documents` table:

```sql
create policy documents_select on documents
  for select
  to authenticated
  using (tenant_id = public.current_tenant_id());
```

Looks correct. Tested by hand. Shipped.

## The symptom

Six weeks after shipping, a customer's support ticket described seeing a document they didn't own. The document title that appeared in their dashboard search results didn't match anything they had created. The customer was confused; the support engineer assumed it was a UI glitch.

A few days later, a second customer reported the same. Then a third. Engineering opened an investigation.

Reproduction was inconsistent. Most queries returned correct data. Occasionally, an unrelated document would surface. The pattern didn't match obvious explanations (cache poisoning, ID collisions, search index drift).

## The bug

After a few hours of probing, an engineer ran a query that exposed it:

```sql
-- Simulate a request where the JWT has no tenant_id claim
set local "request.jwt.claims" = '{}';
select id, title, tenant_id from documents limit 5;
```

Five rows returned. The user had no tenant context, yet five documents from various tenants appeared.

The cause: `public.current_tenant_id()` returned NULL when the JWT didn't have a `tenant_id` claim (it had been written defensively with `nullif(..., '')` to handle missing claims gracefully). The RLS policy compared `tenant_id = NULL`, which in three-valued logic evaluates to NULL — not FALSE. The policy *didn't reject* the row; it returned NULL, and the Postgres RLS engine interpreted "didn't return TRUE" as "no access," which behaved correctly for the *current* row.

But — and this was the subtle part — the policy was applied per-row. For *some* rows, the `tenant_id` was also NULL (legacy data from before the column was added; a few seed rows that weren't tagged). For those rows, `NULL = NULL` returned NULL, and the engine again said "not TRUE, so no access."

What went wrong was elsewhere. The application also queried views that joined `documents` with `tenant_settings`. The view's RLS evaluation flowed differently — under some join conditions, a NULL match was being coalesced upstream, and the policy ended up permitting the row when both sides were NULL.

The simpler way to describe the bug: **a NULL on either side of the RLS comparison didn't reject; it just failed to assert. When both sides were NULL — which happened for legacy untagged rows when the user had a malformed JWT — the row leaked.**

The trigger condition wasn't common, but two configurations of malformed JWTs (a token issued before a tenant migration, a token where the tenant claim had been removed for a deleted-then-restored user) hit it. A handful of customer accounts had been intermittently seeing each other's data for six weeks.

## Root cause

Two compounding failures:

1. **The RLS policy didn't defend against NULL on either side.** The expression `tenant_id = current_tenant_id()` is unsafe when either side might be NULL. The fix is `coalesce(tenant_id, '') = coalesce(current_tenant_id()::text, '')` or equivalent, which forces a definite TRUE or FALSE — never NULL.
2. **Legacy data hadn't been backfilled.** Old rows with NULL `tenant_id` should have been migrated to a sentinel value or deleted. They were left in place because "RLS will filter them anyway."

The combination — both sides NULL, three-valued logic, no defensive coalescing — produced the leak. Either failure alone would not have been sufficient.

## The fix

Two parts, applied in the same hour:

```sql
-- 1. Add coalescing to the RLS policies
drop policy if exists documents_select on documents;
create policy documents_select on documents
  for select
  to authenticated
  using (
    coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)
    = coalesce(public.current_tenant_id(), '11111111-1111-1111-1111-111111111111'::uuid)
  );

-- The two sentinels are deliberately different — a row with NULL tenant_id will
-- never match a user with NULL tenant claim. NULL on either side fails fast.

-- 2. Backfill the legacy rows
update documents set tenant_id = ... where tenant_id is null;
-- (the actual backfill required per-row research; rows were either assigned
-- to a "system" tenant or deleted as orphaned)

-- 3. Make tenant_id NOT NULL going forward
alter table documents alter column tenant_id set not null;
```

A test was added (which should have existed from day one):

```sql
-- This must return zero rows for every test case
set local "request.jwt.claims" = '{}';
select count(*) as leaked from documents;
-- expect: 0

set local "request.jwt.claims" = '{"tenant_id": ""}';
select count(*) as leaked from documents;
-- expect: 0

set local "request.jwt.claims" = '{"tenant_id": null}';
select count(*) as leaked from documents;
-- expect: 0
```

And then a deliberate-violation pass: remove the coalescing from the policy temporarily, confirm the test fails, restore.

## What the patterns would have caught

`patterns/web/rls-null-coalescence-guard.md` codifies this exact lesson. Had it been in place when the policy was written:

- The pattern's mechanism — `coalesce(...)` on both sides of every comparison — would have been the default. The unsafe `tenant_id = current_tenant_id()` would never have shipped.
- The pattern's verification test — checking that requests with malformed claims return zero rows — would have caught the bug in CI on the day the policy was added.

`principles/defense-in-depth-authorization.md` would also have helped: even with a buggy RLS, an application-layer check (`if (!user.tenant_id) throw new Error('unauthorized')`) would have rejected the bad-token requests before any query ran. That second layer existed in some routes but not others; the affected dashboard endpoint relied on RLS alone.

## What got better afterward

1. **The RLS pattern was elevated to a project-wide convention.** Every policy on every table was audited; coalescing added where missing. A convention guard test was added that greps for unsafe RLS expressions in migrations.
2. **NOT NULL constraints were applied to tenant scoping columns.** A row without a tenant is, by construction, a bug. The database enforces it.
3. **Application-layer authorization was reinstated as a required layer.** RLS is the last line of defense, not the only one. The session-handler middleware now rejects requests with malformed tenant claims before any handler runs.
4. **The customer communications and incident-response runbook were updated.** Six weeks of intermittent leakage required notification to affected customers; the team learned how to do that under regulatory time pressure.

## Lessons

- **Three-valued logic is the enemy of authorization.** NULL is neither TRUE nor FALSE; an authorization check that returns NULL behaves like FALSE most of the time and like TRUE some of the time. Always coerce to two-valued logic at the policy boundary.
- **Defense in depth matters even when one layer "should" be sufficient.** RLS alone was the original design; the team had reasoned that the layer was sound. The reasoning had a gap; a second layer would have made the gap survivable.
- **Legacy data is a security risk, not just an inconvenience.** Untagged rows from before a schema migration sit in the database for years; under the right conditions they leak.
- **Test the negative cases.** "Returns the right data for the right user" is the easy test. "Returns no data for the wrong user, the missing user, the malformed user" is the harder, more important test.
- **Six weeks of leakage is the cost of skipping one pattern.** The fix took an hour; the customer-trust damage took longer.

## Related

- `patterns/web/rls-null-coalescence-guard.md` — the pattern that prevents this class of bug.
- `principles/defense-in-depth-authorization.md` — the principle that calls for application-layer + RLS-layer defense.
- `patterns/test-correctness/role-write-matrix-manifest.md` — the test discipline that exercises authorization from multiple actor perspectives.
- `patterns/universal/convention-guard-tests.md` — the grep-based check that prevents the unsafe pattern from being reintroduced.
