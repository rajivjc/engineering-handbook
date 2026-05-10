# Stripe idempotency via audit dedup

**Category:** web (specifically Stripe webhooks; pattern generalizes to any webhook source that retries)
**Applies to:** webhook endpoints that receive events from Stripe (or similar) where the same event may be delivered more than once.

## Problem

Stripe (and many other webhook providers) deliver events with at-least-once semantics. Retries happen on network failures, on slow endpoint responses, on certain error codes. The same `customer.subscription.updated` event might arrive twice. The same `invoice.paid` might arrive twice.

If your handler is naive — for each event, apply the change to your database — you double-process. A subscription update applied twice probably converges (idempotent at the database level if the new state is the same). A credits-issued event applied twice means the customer gets credit twice. A “payment confirmed” event applied twice means the order ships twice.

The fix is at the handler layer: before processing, check whether you’ve already processed this event ID. If yes, skip. If no, process and record the event ID.

## Mechanism

Use the audit log (or a dedicated dedup table) as the source of truth for “have I seen this event ID before?” The check is part of the same transaction as the processing, so the dedup is atomic with the work.

```ts
// src/app/api/webhooks/stripe/route.ts
import { NextRequest } from 'next/server'
import Stripe from 'stripe'
import { getAdminClient } from '@/lib/supabase/admin'

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, { apiVersion: '2024-09-30.acacia' })

export async function POST(request: NextRequest) {
  const body = await request.text()
  const signature = request.headers.get('stripe-signature')
  if (!signature) return new Response('Missing signature', { status: 400 })

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(body, signature, process.env.STRIPE_WEBHOOK_SECRET!)
  } catch (err) {
    return new Response('Invalid signature', { status: 400 })
  }

  const adminClient = getAdminClient()

  // Idempotency check via audit-log dedup. The audit_log table has a UNIQUE
  // constraint on (kind, target->>'event_id') so the insert fails if we've
  // seen this event before. The atomic insert + check pattern is reliable
  // because the unique constraint is enforced by the database.
  const { error: insertError } = await adminClient
    .from('audit_log')
    .insert({
      kind: 'stripe.webhook_received',
      target: { event_id: event.id, event_type: event.type },
      created_at: new Date().toISOString(),
    })

  if (insertError) {
    if (insertError.code === '23505') {
      // unique_violation — we've seen this event before, skip processing
      console.log(`Duplicate stripe event ${event.id}, skipping`)
      return new Response('Already processed', { status: 200 })
    }
    // Some other error — fail loudly so Stripe retries
    console.error('Audit insert failed:', insertError.message)
    return new Response('Internal error', { status: 500 })
  }

  // First time seeing this event. Process it.
  try {
    switch (event.type) {
      case 'customer.subscription.updated':
        await handleSubscriptionUpdated(event.data.object)
        break
      case 'invoice.paid':
        await handleInvoicePaid(event.data.object)
        break
      // ... other cases
    }
    return new Response('OK', { status: 200 })
  } catch (err) {
    // Processing failed AFTER we recorded the event. Log and return 500
    // so Stripe retries. On retry, the audit insert will hit the unique
    // constraint and we'll skip — but the work didn't complete!
    //
    // This is a real edge case. See "What about retries after partial
    // success?" below for the discipline.
    console.error(`Webhook processing failed for ${event.id}:`, err.message)
    return new Response('Processing failed', { status: 500 })
  }
}
```

The shape:

1. Verify the signature (Stripe gives you tools for this; use them).
1. Try to insert an audit row keyed on the event ID. The unique constraint enforces dedup.
1. If the insert fails with unique_violation, the event has been seen — return 200, don’t process.
1. If the insert succeeds, process the event.
1. If processing succeeds, return 200.
1. If processing fails — see the discipline below.

## What about retries after partial success?

Step 6 is the hard case. You inserted the audit row. You started processing. Processing partially succeeded (say, you charged the customer’s credit account for 100 credits but failed to send the email). You return 500. Stripe retries. The retry’s audit insert fails (already there). You return “already processed” — but the email never went out.

Two strategies:

**Strategy A: Make processing itself atomic.** Push the work into an RPC (see `atomic-state-via-rpc`) so it succeeds entirely or rolls back entirely. The audit insert is part of the RPC’s transaction. Then “audit row exists” implies “work fully completed.” Rare partial-success cases (e.g., a fire-and-forget side effect like email) use the strategy below.

**Strategy B: Idempotent fire-and-forget side effects.** Email sends, push notifications, and other external calls run *after* the database transaction commits. They have their own retry / idempotency. If the email fails, a separate background job re-sends it (and that job has its own idempotency).

In practice, you mix: critical state goes in the RPC; tangential side effects fire-and-forget after commit.

## Why this is the right shape

- **Database-enforced uniqueness.** Application-level “have I seen this?” checks have a race window. Two webhook deliveries arriving in parallel each check the audit table, see no row, both proceed. The unique constraint serializes the insert; only one wins.
- **The audit row is the proof of work.** The audit log already exists for compliance / debugging reasons. Reusing it for dedup is free; you’d be writing the row anyway.
- **Returns 200 fast for duplicates.** Stripe stops retrying when it gets 200. A duplicate event is processed in the time of one row insert + one error check. No CPU, no API calls, no chance of re-doing the work.

## What goes in the audit row

At minimum: `kind` (event type, used to scope the unique constraint), `target` (a JSONB column containing the event ID), `created_at`. Optionally: actor (system), payload reference (don’t store the full payload — Stripe lets you retrieve it).

The unique constraint:

```sql
create unique index audit_log_stripe_event_dedup
  on audit_log ((target ->> 'event_id'))
  where kind = 'stripe.webhook_received';
```

The partial index scopes the unique constraint to webhook events specifically, so other audit kinds (which legitimately share IDs across types) aren’t affected.

## Anti-patterns

**Application-level “have I seen this?” check.**

```ts
// Wrong — race condition
const seen = await adminClient.from('audit_log').select('id').eq('event_id', event.id).single()
if (seen) return new Response('OK', { status: 200 })
await processEvent(event)
await adminClient.from('audit_log').insert({ event_id: event.id, ... })
```

Two parallel deliveries both find no existing audit row, both process, both insert. The insert won’t double-fail (one will hit unique constraint), but the *processing* already double-ran.

**Trusting the application to call the dedup helper.** If dedup is a function someone has to remember to call, someone forgets. Make it part of the route’s structure: every webhook route does the audit-insert-or-skip dance at the top.

**Using a non-database dedup mechanism.** “We’ll cache event IDs in Redis.” Now you have two systems — Redis and Postgres — and dedup correctness depends on both. The unique constraint approach uses one system and inherits its consistency guarantees.

**Forgetting the unique constraint.** Without it, the dedup is just an audit log; nothing prevents the same event from being processed twice. The constraint is the load-bearing piece.

**Returning 4xx for duplicates.** Stripe interprets non-2xx as failure and retries. Returning 200 for “already processed” is correct (the work is done, even if not by this delivery).

## Negative consequences

- **The audit table grows linearly with webhook volume.** Mitigation: archive or prune old entries. Keep at least the last 30 days (Stripe’s typical retry window).
- **The handler must be careful about what it considers “processed.”** If the audit insert succeeds but the rest fails, the retry is a no-op — the partial state is now permanent until manually fixed. Strategy A (atomic RPC) handles this; Strategy B requires the side-effect retries to be idempotent.
- **Webhook ordering is still your problem.** Dedup ensures each event is processed once. It doesn’t ensure events are processed in the order Stripe sent them. A `subscription.updated` and a `subscription.deleted` arriving out of order can produce wrong state. Mitigation: include the event timestamp in the processing logic; reject events older than the current state.
- **Doesn’t help with semantically-duplicate events.** Stripe sometimes sends two genuinely different events that should produce the same effect (e.g., a `payment_intent.succeeded` and an `invoice.paid` for the same charge). Dedup-by-event-ID treats these as different. The application has to decide which to act on; the dedup pattern is about Stripe’s at-least-once delivery, not about semantic deduplication.

## Verification

Test cases:

1. **Single delivery happy path.** Deliver event X; assert row inserted, processing ran, response 200.
1. **Duplicate delivery.** Deliver event X; let it complete. Deliver X again; assert no second row insert, no second processing run, response 200.
1. **Concurrent delivery.** Deliver X twice in parallel; assert exactly one row, exactly one processing run, both responses 200.
1. **Processing failure.** Deliver event Y; mock the processor to throw. Assert row IS inserted, response 500. Re-deliver Y; assert no second processing attempt, response 200.

The third test is the load-bearing one. It’s also the hardest — you need to actually drive concurrent requests against the endpoint. Integration tests against a real database catch this; unit tests with a mocked database client don’t.

## Related

- `atomic-state-via-rpc` — the pattern for making the processing itself atomic so partial failure can’t strand the system.
- `fire-and-forget-side-effects` (Session 2B) — the pattern for external side effects that should not gate webhook processing.
