# Case study 03: A double-click that spent the same credit twice

**Category:** correctness
**Patterns referenced:** `patterns/web/atomic-state-via-rpc.md`, `patterns/domain/ledger-with-atomic-refund.md`, `principles/atomic-state.md`
**Severity:** Medium-High (financial correctness, customer-impacting)
**Time to detect:** ~10 days after the regression shipped
**Time to fix once detected:** ~3 hours

## Context

A booking application uses a credit balance to pay for reservations. Each user has a balance (held in a ledger; see `patterns/domain/ledger-with-atomic-refund.md`). Creating a booking spends one credit.

The booking creation flow lived in a server action:

```ts
// src/actions/create-booking.ts
'use server'

export async function createBooking(input: BookingInput): Promise<Result> {
  const user = await getCurrentUser()
  if (!user) return { ok: false, error: 'unauthorized' }

  // Step 1: Check the user has at least one credit
  const balance = await getCreditBalance(user.id)
  if (balance < 1) {
    return { ok: false, error: 'insufficient_credits' }
  }

  // Step 2: Create the booking
  const booking = await db.bookings.insert({
    user_id: user.id,
    resource_id: input.resource_id,
    start_time: input.start_time,
    status: 'confirmed',
  })

  // Step 3: Spend the credit by inserting a ledger entry
  await db.creditLedger.insert({
    user_id: user.id,
    amount: -1,
    reason: 'booking_create',
    source_kind: 'booking',
    source_id: booking.id,
  })

  return { ok: true, booking }
}
```

Three operations: check balance, create booking, deduct credit. Looked sequential. Each step had its own test. Code review didn't flag it.

## The symptom

Ten days after the feature shipped, a support ticket reported a customer with one credit who had two confirmed bookings. The customer was happy (they didn't expect both to succeed) but the team was puzzled.

Looking at the database:

```sql
select * from bookings where user_id = 'customer-id'
  order by created_at desc limit 5;

-- Two rows, both confirmed, both created within 80ms of each other.
```

```sql
select * from credit_ledger where user_id = 'customer-id'
  order by created_at desc limit 5;

-- Two rows, both -1, both created within 100ms of each other.
```

The customer's current balance was negative (-1). They had spent two credits when they only had one to start with.

Looking further: a few other customers had the same shape. Always the same trigger — two bookings created within ~100ms of each other, balance went negative, customer noticed (or didn't), team didn't catch it.

## The bug

The trigger was a user double-clicking the "Confirm booking" button. Two requests fired in quick succession. Both hit the server action.

Walking through the race:

```
Time 0ms:  Request A arrives.  Step 1: getCreditBalance(user.id) returns 1.
Time 5ms:  Request B arrives.  Step 1: getCreditBalance(user.id) returns 1.
Time 30ms: Request A finishes step 2: booking row inserted.
Time 35ms: Request B finishes step 2: booking row inserted.
Time 50ms: Request A finishes step 3: ledger row inserted (-1).
Time 60ms: Request B finishes step 3: ledger row inserted (-1).
```

Both requests saw a balance of 1 (because neither had yet committed the deduction). Both proceeded. Final state: two bookings, two deductions, negative balance.

The bug is a **time-of-check / time-of-use** race. The check (step 1) and the use (step 3) are not atomic. Between them, another request can run.

Front-end button debouncing was inconsistent — some pages debounced, the booking page didn't. Network conditions (the customer was on mobile data) made the double-click more likely to produce two real requests rather than the browser collapsing them.

## Root cause

The three-step server action was non-atomic. There's no SQL transaction wrapping the check, the insert, and the deduction. Even if there were a transaction, two concurrent transactions running the same flow would both see the original balance (without locking), proceed independently, and both succeed.

Two fixes available:

1. **Pessimistic locking** — start a transaction, `select ... for update` on the user row, then check balance, insert booking, deduct credit. Concurrent calls block until the first one commits. The second one sees the deducted balance and rejects.
1. **Optimistic atomic operation** — push the entire check-and-deduct into a single Postgres function (RPC) where the database engine guarantees atomicity.

The team chose option 2 because it generalized — other state changes had the same shape and the RPC pattern was about to be adopted project-wide.

## The fix

A Postgres function that does check, insert, and deduct atomically:

```sql
-- supabase/migrations/0021_create_booking_with_credit_atomic.sql

create or replace function public.create_booking_atomic(
  p_user_id uuid,
  p_resource_id uuid,
  p_start_time timestamptz
)
returns table(ok boolean, error text, booking_id uuid)
language plpgsql
security invoker
as $$
declare
  v_balance integer;
  v_booking_id uuid;
begin
  -- Lock the user's row for the duration of the transaction
  perform 1 from users where id = p_user_id for update;

  -- Compute balance from the ledger
  select coalesce(sum(amount), 0) into v_balance
    from credit_ledger
    where user_id = p_user_id;

  if v_balance < 1 then
    return query select false, 'insufficient_credits'::text, null::uuid;
    return;
  end if;

  -- Insert booking and ledger entry in the same transaction
  insert into bookings (user_id, resource_id, start_time, status)
    values (p_user_id, p_resource_id, p_start_time, 'confirmed')
    returning id into v_booking_id;

  insert into credit_ledger (user_id, amount, reason, source_kind, source_id)
    values (p_user_id, -1, 'booking_create', 'booking', v_booking_id);

  return query select true, ''::text, v_booking_id;
end;
$$;
```

The server action becomes a one-line wrapper:

```ts
export async function createBooking(input: BookingInput): Promise<Result> {
  const user = await getCurrentUser()
  if (!user) return { ok: false, error: 'unauthorized' }

  const result = await db.rpc('create_booking_atomic', {
    p_user_id: user.id,
    p_resource_id: input.resource_id,
    p_start_time: input.start_time,
  })

  if (!result.ok) return { ok: false, error: result.error }
  return { ok: true, booking_id: result.booking_id }
}
```

The `for update` on the users row serializes concurrent calls for the same user. The second call blocks until the first commits, then sees the updated balance (0 after deduction), and returns `insufficient_credits`. The race is gone.

A test that exercises the race:

```ts
import { describe, it, expect } from 'vitest'

describe('createBooking', () => {
  it('rejects concurrent double-spend', async () => {
    const userId = await createUserWithCredits(1)  // exactly one credit

    // Fire two requests in parallel
    const [a, b] = await Promise.all([
      createBooking({ user_id: userId, resource_id: 'r1', start_time: '...' }),
      createBooking({ user_id: userId, resource_id: 'r2', start_time: '...' }),
    ])

    // Exactly one succeeds
    const successes = [a, b].filter(r => r.ok).length
    expect(successes).toBe(1)

    // Final ledger has exactly one deduction
    const ledgerRows = await db.creditLedger.findMany({ where: { user_id: userId } })
    const deductions = ledgerRows.filter(r => r.amount < 0)
    expect(deductions).toHaveLength(1)

    // Final balance is zero
    const balance = ledgerRows.reduce((sum, r) => sum + r.amount, 0)
    expect(balance).toBe(0)
  })
})
```

A deliberate-violation pass: remove the `for update` line from the function. Run the test. Confirm it fails (sometimes — races are nondeterministic, so the test might pass occasionally; running it 50 times should produce some failures). Restore.

## Reconciling existing data

The fix prevented future double-spends. Existing affected accounts needed correction:

```sql
-- Find users with negative balances
select user_id, sum(amount) as balance
from credit_ledger
group by user_id
having sum(amount) < 0;
```

For each: contact the customer, decide between (a) refunding one of the duplicate bookings or (b) crediting their account to restore balance to zero. The team chose (b) for simplicity — customers kept both bookings; the team absorbed the cost of the extra credit.

The team also reviewed every server action that had the check-then-mutate shape. Three other places had the same vulnerability (book a class, redeem a coupon, claim a free month). All were converted to atomic RPCs.

## What got better afterward

1. **The atomic-state-via-RPC pattern became the default.** Any server action that reads state and then mutates it gets pushed into a Postgres function. Code review enforces.
1. **The button-debouncing on the front-end was made consistent.** This was a secondary defense — the *real* fix is server-side atomicity, but reducing the rate of duplicate requests is still worth doing. The shared `useDebouncedAction` hook was added.
1. **Concurrency tests became part of the discipline.** Every atomic RPC ships with a "fire two requests in parallel; exactly one wins" test. The race might not fail on every run, but with 50 iterations it will.
1. **Negative balances became impossible at the schema level.** A check constraint on the running balance view was added: `check (sum(amount) >= 0)`. Belt-and-suspenders; the atomic RPC enforces it logically, the constraint enforces it physically.

## Lessons

- **"Check then act" is always a race.** If the check is in code and the act is in code, with a network round-trip between them, the check is stale by the time the act fires. The check and the act must be in the same atomic operation.
- **Front-end debouncing is not a fix.** It reduces the probability of the bug, not the possibility. A debouncing UI on a server-side race condition is hope, not engineering.
- **Pure unit tests don't catch races.** Each step had a unit test. The test for "step 1 returns the balance" passed; the test for "step 2 inserts a booking" passed; the test for "step 3 inserts a ledger entry" passed. The race only appears when steps 1 of two requests interleave with steps 2 and 3 of each other. Concurrency tests are a different category.
- **Postgres `for update` does the heavy lifting.** Pessimistic locking on the user row is a one-line addition that turns a race into a serial sequence. The cost (slightly slower for legitimate sequential use) is invisible; the benefit is correctness.
- **The patterns existed before the bug; the discipline of applying them is what matters.** The handbook had `atomic-state-via-rpc` from day one; the team had read it. The booking flow didn't use it because at the time of writing, the team hadn't internalized "check-then-mutate" as a code shape to recognize. Pattern-matching skill grows with practice.

## Related

- `patterns/web/atomic-state-via-rpc.md` — the pattern that prevents this class of bug.
- `patterns/domain/ledger-with-atomic-refund.md` — the broader pattern this case study illustrates a specific failure mode of.
- `principles/atomic-state.md` — the principle these patterns instantiate.
- `patterns/test-correctness/proxy-on-mutation-target.md` — the test discipline that catches mutation races.
