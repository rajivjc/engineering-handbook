# Multi-layer rate limiting

**Category:** llm
**Applies to:** any HTTP endpoint that proxies an LLM call (or any expensive third-party API call) where you pay per request and need to bound your exposure.

## Problem

A single rate-limit layer is rarely enough for an LLM proxy. The threats look like this:

- **Casual abuse from a known user.** A signed-in user opens 30 tabs and hits the endpoint repeatedly. Per-user limits handle this.
- **Coordinated abuse from one IP.** A bot framework runs many fake accounts from one IP. Per-user limits don’t help; per-IP limits do.
- **Distributed abuse from many IPs.** A botnet hits the endpoint with one request per IP from thousands of IPs. Per-IP limits don’t help; a global limit does.
- **Burst from legitimate traffic.** A product launch tweet drives a 10x spike. Per-user and per-IP limits don’t help; a global limit prevents your provider bill from running away.

A proxy with only a per-user limit is wide open to the second, third, and fourth cases. A proxy with only a global limit is wide open to a single user burning everyone else’s quota. The defenses layer.

## Mechanism

Three independent counters, all consulted before forwarding the request to the LLM provider. The most restrictive layer wins.

```ts
// src/lib/rate-limit.ts
import { kvGet, kvIncrPxAt, kvDel } from '@/lib/kv'  // any KV store with TTL

interface RateLimitResult {
  ok: boolean
  layer?: 'user' | 'ip' | 'global'
  retryAfterSeconds?: number
}

const LIMITS = {
  user:   { max: 20,    windowSeconds: 60 },     // 20 req/min/user
  ip:     { max: 60,    windowSeconds: 60 },     // 60 req/min/IP (covers households)
  global: { max: 1_000, windowSeconds: 60 },     // 1000 req/min site-wide
}

async function consume(
  key: string,
  limit: { max: number; windowSeconds: number }
): Promise<{ ok: boolean; retryAfter: number }> {
  // Atomic increment with TTL on first set. Pseudocode for the KV pattern:
  // if not exists: set to 1 with PX = windowSeconds * 1000
  // else: increment
  const count = await kvIncrPxAt(key, limit.windowSeconds * 1000)
  if (count > limit.max) {
    const ttl = await kvGet(`${key}:ttl`)
    return { ok: false, retryAfter: ttl ?? limit.windowSeconds }
  }
  return { ok: true, retryAfter: 0 }
}

export async function checkRateLimit(
  userId: string | null,
  ip: string
): Promise<RateLimitResult> {
  // Global first — cheapest to reject if everyone is over
  const globalResult = await consume('rl:global', LIMITS.global)
  if (!globalResult.ok) {
    return { ok: false, layer: 'global', retryAfterSeconds: globalResult.retryAfter }
  }

  // Then IP — protects against per-user-spoofing
  const ipResult = await consume(`rl:ip:${ip}`, LIMITS.ip)
  if (!ipResult.ok) {
    return { ok: false, layer: 'ip', retryAfterSeconds: ipResult.retryAfter }
  }

  // Then user (if authenticated) — finest-grained
  if (userId) {
    const userResult = await consume(`rl:user:${userId}`, LIMITS.user)
    if (!userResult.ok) {
      return { ok: false, layer: 'user', retryAfterSeconds: userResult.retryAfter }
    }
  }

  return { ok: true }
}
```

Used in the proxy endpoint:

```ts
// src/app/api/llm/route.ts
import { checkRateLimit } from '@/lib/rate-limit'
import { isOriginAllowed } from '@/lib/security/origin-validation'

export async function POST(request: Request) {
  if (!isOriginAllowed(request)) {
    return new Response('Forbidden', { status: 403 })
  }

  const userId = await getUserIdOrNull(request)
  const ip = getClientIp(request)

  const rl = await checkRateLimit(userId, ip)
  if (!rl.ok) {
    return new Response(
      JSON.stringify({ error: 'rate_limited', layer: rl.layer }),
      {
        status: 429,
        headers: {
          'Content-Type': 'application/json',
          'Retry-After': String(rl.retryAfterSeconds ?? 60),
        },
      }
    )
  }

  // ... forward to LLM provider
}
```

## Why three layers and not just one

A single layer is always wrong against at least one threat:

- Per-user only → IP-level abuse with disposable accounts blows past the limit.
- Per-IP only → a household sharing one IP gets penalized for one misbehaving member; one user burning the global quota is also unconstrained.
- Global only → one user can consume everyone’s budget.

Three layers in increasing specificity (global → IP → user) means each request is checked against the most restrictive bound that applies. The defense is in depth: a single counter being permissive doesn’t open the system; all three would have to be permissive simultaneously.

## What goes in each layer’s limits

The numbers depend on your traffic and your wallet. Some heuristics:

- **Per-user:** Calibrated to “what does a power user actually need?” plus headroom. If a single user hitting the endpoint 50 times per minute is implausible for any legitimate workflow, set the limit at 20.
- **Per-IP:** Roughly 2–3x the per-user limit, accounting for households and offices. Too tight blocks legitimate shared-IP traffic; too loose misses bot abuse.
- **Global:** Set against your provider’s per-second cap or your daily budget. If your LLM bill caps at $X/day, work backwards from there to a per-minute request rate.

Watch the global rate carefully on launch days. A 10x spike that’s legitimate is your problem to handle (usually by raising the limit temporarily); a 10x spike that’s abuse should hit the limit and stop.

## Anti-patterns

**Storing counters in application memory.** Works in single-process development, fails on any horizontally scaled deployment. Use Redis, Upstash KV, or any external store.

**Reading the counter without atomic increment.** A `get-then-set` pattern races. Use `INCR` with TTL on first set (Redis), or your KV’s atomic equivalent.

**Layers that count the same request multiple times against the same budget.** Each layer must use independent keys. `rl:global`, `rl:ip:<ip>`, `rl:user:<userId>` — never the same key for two layers.

**Returning a generic 429 with no retry guidance.** The `Retry-After` header tells well-behaved clients when to come back. Without it, retries hammer your endpoint and may permanently lock the user out of their window.

**Forgetting to rate-limit the unauthenticated case.** If anonymous users can call the endpoint, the user layer is skipped — IP becomes the only fine-grained defense. Make sure the IP limit is calibrated to that case (probably tighter than for authenticated users).

**Treating IPv6 as if it’s IPv4.** A single user behind IPv6 has effectively a /64 of unique IPs available. Per-IP limits keyed on the full v6 address are useless. Truncate to /64.

**Layer ordering that makes debugging hard.** Reject the global limit *first* — it’s cheapest, and a global rejection means the system is overloaded, not that this user is bad. Reject user-specific limits last so the rejection message tells you which user is the problem.

## Negative consequences

- **Three KV calls per request.** Each adds latency. Mitigate with a Lua script (Redis) or single-call pipelining if your KV supports it. For an LLM proxy where the call itself takes 500ms+, 3 KV calls of 1ms each are noise.
- **The KV store becomes a critical dependency.** If the KV is down, you have to choose: fail open (allow all requests, risk overspend) or fail closed (reject all requests, take a partial outage). Decide upfront and document.
- **False positives in the per-IP layer.** Universities, offices, and CGNAT-affected mobile users share IPs. They will hit the limit faster than individual users do. Mitigate by raising the per-IP limit, or by treating authenticated users separately (per-IP limit only applies to anonymous traffic).
- **Tuning is empirical.** The right numbers come from watching real traffic, not from theory. Plan for a few rounds of tightening or loosening after launch.

## Verification

For each layer, write tests that:

1. Confirm the limit fires at the right count.
2. Confirm requests under the limit pass.
3. Confirm the layer correctly identifies which limit was hit.
4. Confirm reset after the window elapses.

Plus a deliberate-violation pass: temporarily lower the limits to 1, confirm the second request gets a 429 with the right `layer` field. Restore.

For the global limit specifically, run a load test occasionally (off hours) to confirm the limit actually fires under load — easy to assume it works without verifying.

## Related

- `patterns/web/origin-validation.md` — the layer that runs before rate limiting; rejects cross-origin abuse cheaply.
- `patterns/llm/request-size-limit.md` — bounds the cost per allowed request, complementing the count limit.
- `patterns/llm/error-sanitization.md` — the rate-limit response itself shouldn’t leak provider details.
