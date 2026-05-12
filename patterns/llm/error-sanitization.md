# Error sanitization

**Category:** llm
**Applies to:** any endpoint that calls an external API (LLM provider, payment processor, third-party service) and returns a response to a browser-facing client.

## Problem

When a third-party API call fails, the error you receive is verbose and informative — by design. It often includes:

- The exact API endpoint URL.
- The provider’s name and version (`anthropic-version: 2023-06-01`).
- The request ID (sometimes useful for debugging, sometimes a side-channel).
- Internal model names and configuration.
- Stack traces from the provider’s SDK.
- Hints about the API key (last 4 characters, account ID, organization ID).
- Quota information (remaining tokens, billing tier).

If you forward this error to the browser, you’ve leaked all of it. Casual abuse of your endpoint now has a roadmap: which provider you use, what model, what your account is, what your quota looks like, what error patterns might bypass your defenses. Even just “Anthropic” or “OpenAI” in an error message tells abuse tooling which exploits to try.

## Mechanism

A sanitization layer between the upstream error and the response. Every error path goes through it; the original error is logged server-side, a generic version goes to the client.

```ts
// src/lib/llm/sanitize-error.ts
import 'server-only'

interface SanitizedError {
  status: number
  body: { error: string; code?: string }
}

const PROVIDER_INDICATORS = [
  'anthropic',
  'openai',
  'cohere',
  'sk-',           // API key prefix
  'X-API-Key',
  'organization',
  'request_id',
  'request-id',
  'x-request-id',
]

export function sanitizeUpstreamError(err: unknown): SanitizedError {
  // Always log the full error server-side. The client gets the safe version.
  console.error('Upstream error:', err)

  // Categorize by HTTP status if we have one, otherwise generic 500
  const status = extractStatus(err)
  const upstreamMessage = extractMessage(err).toLowerCase()

  // Map known categories to safe codes the client can react to
  if (status === 401 || status === 403) {
    return { status: 500, body: { error: 'Service temporarily unavailable', code: 'upstream_auth' } }
  }
  if (status === 429 || upstreamMessage.includes('rate limit') || upstreamMessage.includes('quota')) {
    return { status: 503, body: { error: 'Service is currently busy. Please try again later.', code: 'upstream_busy' } }
  }
  if (status >= 500 && status < 600) {
    return { status: 502, body: { error: 'Service temporarily unavailable', code: 'upstream_error' } }
  }
  if (status === 400) {
    // The user's input was rejected by the upstream. We can hint at this without
    // exposing why.
    return { status: 400, body: { error: 'Request could not be processed', code: 'invalid_request' } }
  }

  return { status: 500, body: { error: 'Service temporarily unavailable', code: 'unknown' } }
}

function extractStatus(err: unknown): number {
  if (err && typeof err === 'object' && 'status' in err && typeof err.status === 'number') {
    return err.status
  }
  return 500
}

function extractMessage(err: unknown): string {
  if (err && typeof err === 'object' && 'message' in err && typeof err.message === 'string') {
    return err.message
  }
  return ''
}
```

Used in the proxy endpoint:

```ts
// src/app/api/llm/route.ts
import { sanitizeUpstreamError } from '@/lib/llm/sanitize-error'

export async function POST(request: Request) {
  // ... origin validation, rate limiting, input validation

  try {
    const result = await callProvider(prompt)
    return new Response(JSON.stringify({ result }), { status: 200 })
  } catch (err) {
    const sanitized = sanitizeUpstreamError(err)
    return new Response(JSON.stringify(sanitized.body), {
      status: sanitized.status,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
```

## What goes in the sanitized response vs. the server log

**To the client:** a stable error code (so the client can render different UI for “busy” vs. “invalid input” vs. “unavailable”), a human-readable message that’s neutral to the provider, and the appropriate HTTP status. Nothing else.

**To the server log:** everything. The full upstream error, the original message, the request ID, the user’s session, the prompt that triggered it (if not subject to PII rules — see `pii-redaction`). When a user reports “the AI feature broke,” you need the full picture to diagnose, and the only safe place to keep it is server-side.

## A guard test for the sanitization layer

```ts
import { sanitizeUpstreamError } from '@/lib/llm/sanitize-error'

describe('sanitizeUpstreamError', () => {
  it('returns generic message regardless of upstream details', () => {
    const errs = [
      new Error('Anthropic API returned 401: Invalid API key sk-ant-abc...'),
      new Error('OpenAI request_id req_7f2k: model gpt-4 not available'),
      { status: 429, message: 'rate_limit_exceeded: 1000 RPM cap on tier 3' },
      new Error('connection to api.anthropic.com timed out'),
    ]
    for (const err of errs) {
      const result = sanitizeUpstreamError(err)
      const body = JSON.stringify(result.body).toLowerCase()
      // None of the provider indicators should appear in the response
      expect(body).not.toMatch(/anthropic|openai|cohere|sk-|request_id|api\.anthropic|gpt-4/)
    }
  })

  it('preserves status category mapping', () => {
    expect(sanitizeUpstreamError({ status: 401 }).body.code).toBe('upstream_auth')
    expect(sanitizeUpstreamError({ status: 429 }).body.code).toBe('upstream_busy')
    expect(sanitizeUpstreamError({ status: 503 }).body.code).toBe('upstream_error')
  })
})
```

The first test is the load-bearing one: it asserts that *no* provider name, key, request ID, or model name appears in the sanitized output, regardless of what the upstream said. Add a deliberate-violation pass: temporarily change `sanitizeUpstreamError` to return `{ status: 500, body: { error: err.message } }` and confirm the test fails.

## Anti-patterns

**Catching at the route level and returning `err.message`.**

```ts
// Wrong
catch (err) {
  return new Response(JSON.stringify({ error: err.message }), { status: 500 })
}
```

This is the leak in its most common form. Every provider detail goes straight to the browser.

**Sanitizing only the message but keeping the status code.** If your endpoint returns 401 because the upstream returned 401, you’ve signaled “API key problem” without saying it. Map the status too: an upstream auth failure becomes a 500 from your endpoint (it’s your service that failed to authenticate, not the user’s request that lacks auth).

**Using error codes that mirror provider terminology.** `code: 'anthropic_overloaded'` defeats the sanitization. Use neutral codes (`upstream_busy`).

**Returning request IDs from the upstream.** Tempting to “let the user share this with support.” But the request ID can identify your account, and a sequence of request IDs reveals throughput. If you want a debugging handle, generate your *own* ID, log the mapping server-side, and return only your ID to the user.

**Inconsistent sanitization across paths.** The happy path goes through `sanitizeUpstreamError`; a fallback path manually returns `err.toString()`. The leak is one path away. The discipline is “every error path goes through the sanitizer,” enforced by code review or convention guard.

**Leaking through stack traces in production.** Some frameworks return stack traces in error responses by default in development mode. Make sure production builds suppress this — or, better, never trust the framework: catch and sanitize explicitly.

## Negative consequences

- **Genuine debugging is harder for users.** They see “Service temporarily unavailable” and don’t know whether to retry, wait, or contact support. Mitigate with stable error codes the UI can map to specific guidance.
- **Support burden shifts to your logs.** When a user reports a problem, the only way to diagnose is to find their request in your logs. Make sure logs are searchable by user ID and timestamp.
- **The sanitizer can over-fire.** A genuinely informative error from your *own* code might get mapped to a generic upstream error if it’s not classified correctly. Mitigate: distinguish your-code errors (let through with sanitization for sensitive fields only) from upstream errors (always map to generic).
- **The mapping table needs maintenance.** New provider error shapes appear over time. Monitor for “unknown” codes in your logs; each one is a hint that the mapping needs an update.

## Verification

For every endpoint that proxies an external API:

1. Trigger each known error class from the upstream (auth fail, rate limit, malformed input, timeout, 5xx).
2. Inspect the response. Confirm none of the upstream details appear.
3. Inspect the server log. Confirm the full upstream error is captured.
4. Run the deliberate-violation pass on the sanitizer test.

For new endpoints, the sanitizer must be in place *before* the endpoint is exposed. Adding it later means every error before the fix has potentially leaked.

## Related

- `patterns/llm/rate-limiting-multi-layer.md` — pairs naturally; the rate-limit response itself uses sanitized codes.
- `patterns/llm/pii-redaction.md` — sanitization for the prompt content; this pattern is for the error path.
- `patterns/web/origin-validation.md` — first-line defense; the sanitizer is the inner layer.
