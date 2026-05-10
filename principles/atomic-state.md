# Principle: Atomic state

Multi-row state changes go through database-level atomicity primitives, not application code. If three rows must be updated together, they update together inside a transaction or stored procedure — not in three sequential calls from a server action.

This is true even when “it works” in practice. Application-level multi-step mutations are correct only when nothing fails between the steps, which is true 99% of the time and exactly the wrong 1% to bet on.

## What this looks like

The wrong shape:

```ts
// Don't do this
export async function publishWeekAction(weekId: string) {
  await markWeekAsPublished(weekId)        // step 1: mutates `weeks`
  await assignStaffToShifts(weekId)        // step 2: mutates `shifts`
  await stampPublishedAt(weekId)           // step 3: mutates `weeks` again
  await sendPushToAssignedStaff(weekId)    // step 4: side effect
  return { success: true }
}
```

If step 2 fails after step 1 succeeds, the database is in a state that no business rule recognizes: a “published” week with no assigned staff. Recovery is manual. The rollback path is implicit (manual cleanup) and untested.

The right shape:

```ts
// Do this
export async function publishWeekAction(weekId: string) {
  // The RPC does steps 1-3 inside a transaction; either all succeed or all fail.
  const result = await rpcSchedulePublishWeek(weekId)
  if (!result.ok) return { error: result.reason }

  // Step 4 is a fire-and-forget side effect that doesn't gate success.
  // See patterns/domain/fire-and-forget-side-effects.md for the rationale.
  sendPushToAssignedStaff(weekId).catch(logError)

  return { success: true }
}
```

The mutation steps are inside a Postgres function that runs in a single transaction. If any step throws, the whole thing rolls back. The application code is now correct in the failure case as well as the success case.

## Why this is non-negotiable for multi-row mutations

- **Application-level transactions are not real.** Most application code “transactions” are sequences of independent calls. A network blip between calls leaves the database in a state no test exercises and no business rule covers.
- **The failure case is the case you don’t test.** Tests that exercise the happy path are easy. Tests that exercise the “step 2 failed after step 1 succeeded” path are hard, and tend not to exist. Putting the atomicity in the database means the failure case is handled by the database engine, not by code that doesn’t exist.
- **Recovery is unbounded work.** When the database ends up in a state that no rule covers, fixing it is manual SQL. This is fine for one-time accidents and terrible as the steady-state pattern.

## What “via RPC” means in practice

In Postgres + Supabase, this looks like a SQL function:

```sql
create or replace function public.schedule_publish_week(p_week_id uuid)
returns table(ok boolean, reason text)
language plpgsql
security invoker
as $$
begin
  -- Step 1: mark week as published
  update schedule_weeks
    set status = 'published'
    where id = p_week_id;

  if not found then
    return query select false, 'week_not_found'::text;
    return;
  end if;

  -- Step 2: assign staff to shifts
  insert into schedule_shift_assignments (shift_id, user_id, kind)
    select s.id, ft.user_id, 'standing'
    from schedule_shifts s
    join schedule_ft_assignments ft on ft.day_of_week = s.day_of_week
    where s.week_id = p_week_id;

  -- Step 3: stamp published_at
  update schedule_weeks
    set published_at = now()
    where id = p_week_id;

  return query select true, ''::text;
end;
$$;
```

If anything raises, the whole function rolls back. The application calls it as a single RPC and treats the result as either complete success or complete failure.

## Atomicity is layered, not just transactional

Some operations span systems: a database mutation plus a Stripe charge plus a push notification. You can’t put a Stripe API call inside a Postgres transaction. The pattern then is:

1. Identify the source-of-truth system. Usually the database.
1. Make the source-of-truth mutation atomic via the database.
1. Trigger external side effects after the database transaction commits, with retry / idempotency at each external system.
1. Accept that “atomic” means “atomic in the source of truth”; reconciliation across systems is a separate problem with its own patterns (see [`patterns/web/stripe-idempotency-via-audit-dedup.md`](../patterns/web/stripe-idempotency-via-audit-dedup.md)).

## Anti-patterns

- **Application-level “if this fails, rollback the previous step manually.”** This is a transaction, badly. Use a real transaction.
- **Try/catch around the multi-step mutation that calls cleanup functions on failure.** The cleanup functions can also fail. Now you have nested failure modes that nobody tests. Use a real transaction.
- **“It’s fine, this rarely fails.”** Rarely is not never, and the failure case is exactly when atomicity matters. Use a real transaction.
- **Stored procedure that’s just three SQL statements with no transaction wrapper.** In Postgres, every function runs in a transaction by default. But if you’re calling out to other systems from the function, or if you’ve explicitly committed in the middle, atomicity is gone. Read what your database actually does.

## Where this is enforced

[`patterns/web/atomic-state-via-rpc.md`](../patterns/web/atomic-state-via-rpc.md) documents the implementation pattern with multiple worked examples. [`patterns/test-correctness/proxy-on-mutation-target.md`](../patterns/test-correctness/proxy-on-mutation-target.md) documents how to test rollback behaviour correctly — a test that throws on the function-call boundary doesn’t engage the rollback path because no mutation has happened yet.

## Negative consequences

- Stored procedures are more friction than application code. They live in migrations, change less often, are harder to debug. The friction is the point — it pushes you to think about whether the multi-step nature is essential.
- Postgres functions don’t compose well across services. If your atomic operation crosses service boundaries, this pattern doesn’t apply directly; you need saga-style coordination, which is its own complexity. The principle still holds: identify the source of truth, make that atomic, layer external systems on top.
- Testing stored procedures is harder than testing application code. Worth doing for the load-bearing ones; the cost is real.

The trade-off is correctness against ergonomics. Correctness wins for state changes the business cares about.
