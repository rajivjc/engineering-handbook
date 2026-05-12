# Ledger with atomic refund

**Category:** domain
**Applies to:** any application with a virtual currency, credit balance, points system, or other monotonic accounting that must reconcile.

## Problem

A naive credits implementation stores a single balance:

```sql
create table users (
  id uuid primary key,
  credits integer not null default 0
);
```

A spend operation decrements; a refund increments. This is wrong for any system that needs to answer questions like:

- “Why does this user have 47 credits when last month they had 50 and only used 1?”
- “A booking was canceled — was it refunded? When? By whom?”
- “Two of our staff applied a manual credit adjustment in the same minute. What happened?”

A balance is a derived value. The truth is the *sequence of events* that produced the balance. Without the sequence, you can’t audit, can’t reconcile, can’t recover from corruption, can’t answer support tickets reliably.

The fix is a ledger: an append-only table where every credit movement is a row. The balance is computed (or cached) from the rows. Refunds are paired with the original spend by reference, not by adjusting a balance.

## Mechanism

### The ledger schema

```sql
create table credit_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  amount integer not null,                            -- positive = grant, negative = spend
  reason text not null,                               -- 'booking_create', 'booking_refund', 'manual_grant', 'monthly_topup', etc.
  source_kind text,                                   -- 'booking', 'subscription', 'manual_adjustment'
  source_id uuid,                                     -- FK reference into the source table (e.g., bookings.id)
  paired_ledger_id uuid references credit_ledger(id), -- for refunds: points to the original spend row
  acting_user_id uuid references users(id),           -- who triggered this entry (the user themselves, a staff override, the system)
  created_at timestamptz not null default now()
);

create index credit_ledger_user_idx on credit_ledger (user_id, created_at desc);

-- For deriving the current balance:
create view user_credit_balance as
  select user_id, sum(amount) as balance
  from credit_ledger
  group by user_id;
```

### The atomic spend-with-source pattern

Every spend writes a ledger row in the same transaction as the source mutation. The ledger row references the source by ID, making refund logic trivial.

```sql
-- supabase/migrations/0010_create_booking_with_ledger.sql

create or replace function public.create_booking_with_credit_spend(
  p_user_id uuid,
  p_resource_id uuid,
  p_start_time timestamptz,
  p_credit_cost integer,
  p_acting_user_id uuid
)
returns table(ok boolean, reason text, booking_id uuid, ledger_id uuid)
language plpgsql
security invoker
as $$
declare
  v_balance integer;
  v_booking_id uuid;
  v_ledger_id uuid;
begin
  -- Authorization at the database level (defense in depth)
  if p_user_id != p_acting_user_id and not exists (
    select 1 from users where id = p_acting_user_id and role in ('staff', 'manager')
  ) then
    return query select false, 'forbidden'::text, null::uuid, null::uuid;
    return;
  end if;

  -- Lock the user's row to prevent concurrent overdrafts
  perform 1 from users where id = p_user_id for update;

  -- Compute current balance from the ledger (always derived, never trusted as a stored value)
  select coalesce(sum(amount), 0) into v_balance
    from credit_ledger
    where user_id = p_user_id;

  if v_balance < p_credit_cost then
    return query select false, 'insufficient_credits'::text, null::uuid, null::uuid;
    return;
  end if;

  -- Insert the source row
  insert into bookings (user_id, resource_id, start_time, status, created_at)
    values (p_user_id, p_resource_id, p_start_time, 'confirmed', now())
    returning id into v_booking_id;

  -- Insert the paired ledger row, referencing the source
  insert into credit_ledger (user_id, amount, reason, source_kind, source_id, acting_user_id)
    values (p_user_id, -p_credit_cost, 'booking_create', 'booking', v_booking_id, p_acting_user_id)
    returning id into v_ledger_id;

  return query select true, ''::text, v_booking_id, v_ledger_id;
end;
$$;
```

### The atomic refund-by-pairing pattern

Refunding looks up the original spend, asserts it hasn’t already been refunded, and inserts a paired refund row.

```sql
create or replace function public.refund_booking(
  p_booking_id uuid,
  p_acting_user_id uuid
)
returns table(ok boolean, reason text, refund_ledger_id uuid)
language plpgsql
security invoker
as $$
declare
  v_booking record;
  v_original_ledger record;
  v_already_refunded boolean;
  v_refund_ledger_id uuid;
begin
  select * into v_booking from bookings where id = p_booking_id for update;
  if v_booking is null then
    return query select false, 'booking_not_found'::text, null::uuid;
    return;
  end if;

  -- Find the original spend
  select * into v_original_ledger
    from credit_ledger
    where source_kind = 'booking' and source_id = p_booking_id and amount < 0
    order by created_at asc
    limit 1;

  if v_original_ledger is null then
    return query select false, 'no_original_spend'::text, null::uuid;
    return;
  end if;

  -- Check whether a refund already exists pointing at this original ledger row
  select exists (
    select 1 from credit_ledger
    where paired_ledger_id = v_original_ledger.id
  ) into v_already_refunded;

  if v_already_refunded then
    return query select false, 'already_refunded'::text, null::uuid;
    return;
  end if;

  -- Insert the refund
  insert into credit_ledger (
    user_id, amount, reason, source_kind, source_id, paired_ledger_id, acting_user_id
  ) values (
    v_booking.user_id,
    -v_original_ledger.amount,                    -- inverse of the spend
    'booking_refund',
    'booking',
    p_booking_id,
    v_original_ledger.id,                         -- <-- the pairing
    p_acting_user_id
  ) returning id into v_refund_ledger_id;

  -- Mark the source as refunded
  update bookings set status = 'refunded', refunded_at = now() where id = p_booking_id;

  return query select true, ''::text, v_refund_ledger_id;
end;
$$;
```

The `paired_ledger_id` column is the load-bearing piece. It makes “is this booking refunded?” a simple existence check, not a calculation across the ledger.

## Why pairing and not separate refund tables

You could store refunds in a separate table. The pairing approach has three advantages:

1. **The balance is one query.** `select sum(amount) from credit_ledger where user_id = X` produces the truth. No joining across tables.
2. **The audit trail is one table.** Every credit movement is in `credit_ledger`, in chronological order. Filing this in two tables makes “what happened to this user’s credits?” a multi-table reconstruction.
3. **Refunds reference originals explicitly.** “Find all refunds” is `where paired_ledger_id is not null`. “Find unrefunded spends” is `select id from credit_ledger where amount < 0 and not exists (select 1 from credit_ledger r where r.paired_ledger_id = credit_ledger.id)`. Both are simple.

## Anti-patterns

**Storing the balance in a column on `users`.** Every spend updates the column. Every refund updates the column. The column is a denormalized cache; the ledger is the truth. When they disagree (because of a bug, a missed update, a race), the column is wrong and you can’t tell. Either don’t store the balance at all, or store it with a constraint that ties it to the ledger.

**Refunds that adjust the balance without writing a ledger row.** The audit trail is gone. “Why was this user’s balance corrected by 50 last Tuesday?” has no answer.

**Allowing the same source to be refunded twice.** Without the existence check on `paired_ledger_id`, a buggy retry or a UI double-click can double-refund. The check is a uniqueness constraint in shape; if you use a unique index on `paired_ledger_id`, the database enforces it.

**Allowing partial refunds without explicit semantics.** “Refund 50 of the 100 credits” is sometimes valid. If you allow it, write the partial refund as a separate ledger row pointing at the same original; check the cumulative refund amount against the original spend.

**Computing the balance for every page load.** A user with thousands of ledger rows performs an aggregation on every read. Mitigate with a materialized view, a periodic snapshot, or a triggered cache. Don’t store the balance as a “primary” column, but caching it as a “derived” column with a refresh rule is fine.

**Letting non-ledger paths mutate balances.** A direct `update users set credits = credits + 10` somewhere in the codebase is a backdoor. Mitigate with a convention guard test that flags any UPDATE on the (deprecated) credits column outside of a small allow-list of ledger functions.

## Negative consequences

- **More writes.** Every credit movement is an insert into the ledger plus the source mutation. For a high-throughput system this matters; for typical applications the cost is negligible compared to the audit value.
- **Harder to “manually fix” balances.** A staff member who wants to “just add 10 credits” must do it through a ledger entry (`reason: 'manual_grant'`). That’s the right discipline; it just feels heavier than `UPDATE users SET credits = credits + 10`.
- **Reconciliation is necessary.** If you do cache a balance on the user row, you need a periodic check that the cache matches the ledger sum. A nightly job that flags discrepancies catches drift before it spreads.
- **Schema migrations are sticky.** Adding a new credit movement type is a new `reason` value (cheap). Changing the structure of the ledger is expensive — the table is append-only and grows. Get the schema right early.

## Verification

For the spend path:

1. Happy path: insufficient balance → returns `insufficient_credits`, no booking, no ledger row.
2. Happy path: sufficient balance → booking created, ledger row created, balance reduced.
3. Concurrency: two parallel calls with just-enough balance for one of them — exactly one succeeds, balance correct after.

For the refund path:

1. Refund a valid booking → ledger row inserted, paired_ledger_id matches the original, balance restored.
2. Refund an already-refunded booking → returns `already_refunded`, no second row.
3. Concurrent double-click on refund button → exactly one refund row inserted (use the unique index on paired_ledger_id).

The third test in each set is the load-bearing concurrency check. Use the proxy-on-mutation-target pattern (or real database integration tests) to engage with the actual locking and uniqueness behavior.

## Related

- `patterns/web/atomic-state-via-rpc.md` — the underlying pattern for the multi-step mutations.
- `patterns/test-correctness/proxy-on-mutation-target.md` — how to test the atomicity and pairing properties.
- `principles/atomic-state.md` — the principle this pattern instantiates.
