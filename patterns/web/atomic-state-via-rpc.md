# Atomic state via Postgres RPC

**Category:** web (Next.js + Postgres / Supabase shape; generalizes to any application talking to Postgres)
**Applies to:** server actions or API handlers that mutate multiple rows where atomicity matters.

This is the implementation pattern for the principle in `principles/atomic-state.md`. The principle covers *why* atomicity belongs in the database. This file covers *how* — the specific shape of pushing the multi-step mutation into a Postgres function and calling it from a server action as a single RPC.

## The shape

### Step 1: write the SQL function

```sql
-- supabase/migrations/0001_publish_week_function.sql

create or replace function public.schedule_publish_week(
  p_week_id uuid,
  p_acting_user_id uuid
)
returns table(ok boolean, reason text)
language plpgsql
security invoker
as $$
declare
  v_status text;
begin
  -- Authorization: ensure the calling user has the right role.
  -- (Defense in depth; the action layer also checks. This is the database
  -- floor.)
  if not exists (
    select 1 from users where id = p_acting_user_id and role in ('manager', 'owner')
  ) then
    return query select false, 'forbidden'::text;
    return;
  end if;

  -- Step 1: ensure the week exists and is in 'draft' state.
  select status into v_status
    from schedule_weeks
    where id = p_week_id
    for update;  -- row lock to prevent racing publishers

  if v_status is null then
    return query select false, 'week_not_found'::text;
    return;
  end if;
  if v_status != 'draft' then
    return query select false, 'week_not_draft'::text;
    return;
  end if;

  -- Step 2: insert assignments for full-time staff with standing schedules.
  insert into schedule_shift_assignments (shift_id, user_id, kind, created_at)
  select s.id, ft.user_id, 'standing', now()
    from schedule_shifts s
    join schedule_ft_assignments ft on ft.day_of_week = s.day_of_week
    where s.week_id = p_week_id
  on conflict (shift_id, user_id) do nothing;

  -- Step 3: insert assignments for part-time availabilities the manager picked.
  insert into schedule_shift_assignments (shift_id, user_id, kind, created_at)
  select s.id, pt.user_id, 'pt_picked', now()
    from schedule_shifts s
    join schedule_pt_picks pt on pt.shift_id = s.id
    where s.week_id = p_week_id
  on conflict (shift_id, user_id) do nothing;

  -- Step 4: mark the week as published with timestamp.
  update schedule_weeks
    set status = 'published',
        published_at = now(),
        published_by = p_acting_user_id
    where id = p_week_id;

  -- Step 5: write an audit row.
  insert into audit_log (kind, actor_id, target, created_at)
    values ('schedule.week_published', p_acting_user_id,
            jsonb_build_object('week_id', p_week_id), now());

  return query select true, ''::text;
end;
$$;
```

If any step throws, the whole transaction rolls back. The function returns a discriminated result (ok / reason) instead of throwing for *known* failure cases (forbidden, not found, wrong state) so the caller can branch cleanly.

### Step 2: call from a server action

```ts
// src/app/actions/schedule.ts
'use server'

import { getServerClient } from '@/lib/supabase/server'
import { getCurrentUser } from '@/lib/auth'
import { hasRole } from '@/lib/auth/roles'
import { revalidatePath } from 'next/cache'
import { sendPushToAssignedStaff } from '@/lib/push/schedule'

export interface ActionResult {
  success?: true
  error?: string
}

export async function publishWeekAction(weekId: string): Promise<ActionResult> {
  const user = await getCurrentUser()
  if (!user) return { error: 'unauthenticated' }
  if (!hasRole(user, 'manager')) return { error: 'forbidden' }

  const supabase = await getServerClient()

  // The mutation. Single RPC, atomic, all-or-nothing.
  const { data, error } = await supabase.rpc('schedule_publish_week', {
    p_week_id: weekId,
    p_acting_user_id: user.id,
  })

  if (error) {
    // Unexpected database error — log and report.
    console.error('publishWeekAction RPC error:', error.message)
    return { error: 'internal' }
  }

  const result = data?.[0]
  if (!result || !result.ok) {
    return { error: result?.reason ?? 'unknown' }
  }

  revalidatePath(`/manager/schedule/${weekId}`)

  // Side effect AFTER the database commit. Fire-and-forget; the action
  // doesn't fail if push delivery fails. See fire-and-forget-side-effects.
  sendPushToAssignedStaff(weekId).catch(err =>
    console.error('push delivery failed (non-fatal):', err.message)
  )

  return { success: true }
}
```

Three things to notice:

1. **Authentication and role check happen at the action layer.** Even though the SQL function also checks the role (defense in depth), the action layer is the first gate.
2. **Push delivery happens AFTER the database commit.** A push notification fired during the transaction might be sent before the row is actually committed; if the transaction rolls back, the push has already gone out for a state that didn’t happen. Always defer external side effects until after commit. See `fire-and-forget-side-effects` for the full discipline.
3. **The RPC’s failure modes are typed in the result.** `forbidden`, `week_not_found`, `week_not_draft` — each is a discrete case the action layer can map to a UI error message.

## When this is the right tool

- **Multi-row mutations across more than one table.** Single-row updates don’t need an RPC; the implicit transaction around a single statement is enough.
- **Order-dependent mutations.** Step 2 reads what step 1 wrote.
- **Mutations that need a row lock.** `for update` inside the function prevents two callers from racing on the same row.
- **Mutations where partial success is dangerous.** A “published week” with no shift assignments is a state no business rule recognizes.

For single-statement mutations, the RPC is overkill. Use the supabase-js client directly:

```ts
const { error } = await supabase
  .from('bookings')
  .update({ status: 'cancelled', cancelled_at: new Date().toISOString() })
  .eq('id', bookingId)
```

This is already atomic at the row level. No RPC needed.

## What goes in the function vs. the action

**In the function:**

- All mutations.
- Row locks.
- Database-level authorization (defense in depth).
- Failure-mode result codes the caller branches on.

**In the action:**

- Authentication (resolving the current user).
- Authorization (role check).
- Validation (zod or equivalent).
- Calling the RPC.
- Branching on the RPC result.
- Revalidation (`revalidatePath`).
- Fire-and-forget side effects (push, audit log if not in the function).

The action is a thin shell. The function is the load-bearing piece.

## Anti-patterns

**Multi-step mutation in the action via sequential calls.**

```ts
// Wrong — not atomic
await markWeekPublished(weekId)
await assignStaffToShifts(weekId)
await stampPublishedAt(weekId)
```

If step 2 fails, steps 1 and 3 might or might not have run. The application has no recourse. Use an RPC.

**RPC that calls out to external services.** Postgres functions can’t reliably call HTTP services (some can via extensions, but the latency, reliability, and transaction semantics are wrong). Keep external calls in the application code, after the database commit.

**RPC without typed results.** A function that throws on every failure case forces the caller to parse error messages. Worse: a function that returns `void` and silently fails. Always return a discriminated result.

**Function written without `for update`.** Two callers run the same RPC simultaneously. Both read the row in `draft` state. Both proceed to publish. The second one corrupts the first one’s work. Use row locks.

**Function that’s too big.** A 200-line plpgsql function is hard to test and harder to debug. If your RPC is doing a lot, consider whether it’s actually one operation. Sometimes yes (a payroll lock that aggregates dozens of records is unavoidably big). Sometimes no (split into smaller functions, compose at the action layer if the steps don’t need to share a transaction).

**Defense-in-depth role check that diverges from the action’s role check.** The function and the action must agree on who’s allowed. See `role-write-matrix-manifest` for the test that prevents this drift.

## Negative consequences

- **Higher friction than application code.** Plpgsql is a different language. Migrations carry the function. Debugging is harder than stepping through TypeScript. The friction is the point — it pushes you to think about whether the multi-step nature is essential.
- **Functions don’t compose well across services.** If your atomic operation crosses service boundaries (a message queue, an external API), the function pattern doesn’t apply directly. Use saga-style coordination, accept eventual consistency, or design the operation differently.
- **Testing functions is harder than testing application code.** Worth doing for the load-bearing ones; the cost is real. Pure-function tests in TypeScript run in milliseconds; tests against a function require a real database connection and take seconds.
- **The function’s failure modes are the action’s failure modes.** Adding a new failure case to the function means adding a new branch to the action. Two places to update; mitigation is the role-write-matrix manifest if you want automated drift detection.

## Verification

For every RPC, test:

1. **Happy path.** All steps succeed; the function returns ok.
2. **Each known failure mode.** `forbidden`, `not_found`, etc. — assert the function returns the expected reason without mutating anything.
3. **Atomicity (using `proxy-on-mutation-target`).** Inject a failure mid-function (or use a database that simulates it), assert that none of the prior steps’ mutations are visible after the rollback.
4. **Concurrency (using a real database).** Two parallel calls to the RPC; assert that one wins and the other gets a clean failure (not a corrupt state).

The third test is what makes this pattern’s atomicity guarantee real. Without it, you’re trusting Postgres’s transaction semantics blindly. Trust is fine; verification is better.

## Related

- `principles/atomic-state.md` — the principle behind this pattern.
- `proxy-on-mutation-target` — the test pattern that verifies atomicity engages.
- `fire-and-forget-side-effects` — the pattern for external side effects after the RPC commits.
- `role-write-matrix-manifest` — the test that prevents action-layer and database-layer authorization from drifting apart.
