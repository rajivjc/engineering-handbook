# Origin validation

**Category:** web (general — applies to any HTTP API endpoint, not framework-specific)
**Applies to:** API endpoints that should only be called from your own frontend, not from arbitrary origins.

## Problem

A typical web app has an API endpoint at `/api/something` that the frontend calls. The endpoint is publicly reachable; anyone with the URL can issue a request. Most of the time this is fine — the endpoint doesn’t do anything sensitive — but for some endpoints it’s not:

- An endpoint that proxies an LLM API. Without protection, anyone on the internet can use your endpoint as a free LLM proxy, racking up your API bill.
- An endpoint that performs a privileged action (e.g., sending an email through your verified domain).
- An endpoint that’s expensive to call (database-heavy, runs an ML model, etc.) and you want to limit usage to your own users.

You can’t prevent this entirely — anyone can spoof headers from a non-browser client (curl, scripts) — but you can block the most common case: cross-origin browser requests from other websites.

## Mechanism

Validate the `Origin` header (or `Referer` as a fallback) against an allow-list of domains:

```ts
// src/lib/security/origin-validation.ts

const ALLOWED_ORIGINS = [
  'https://yourapp.com',
  'https://yourapp.vercel.app',
  // Add localhost for dev, but only when not in production:
  ...(process.env.NODE_ENV !== 'production'
    ? ['http://localhost:3000', 'http://localhost:3001']
    : []),
]

export function isOriginAllowed(request: Request): boolean {
  const origin = request.headers.get('origin')
  const referer = request.headers.get('referer')

  // Prefer Origin header if present.
  if (origin) {
    return ALLOWED_ORIGINS.includes(origin)
  }

  // Fall back to Referer (less reliable but better than nothing).
  if (referer) {
    try {
      const refererOrigin = new URL(referer).origin
      return ALLOWED_ORIGINS.includes(refererOrigin)
    } catch {
      return false
    }
  }

  // No Origin or Referer — could be a non-browser client (curl, server-side
  // request). Reject by default. Adjust if you have legitimate non-browser
  // callers (e.g., webhooks have their own validation).
  return false
}
```

Used in an API route:

```ts
// src/app/api/analyze/route.ts
import { isOriginAllowed } from '@/lib/security/origin-validation'

export async function POST(request: Request) {
  if (!isOriginAllowed(request)) {
    return new Response('Forbidden', { status: 403 })
  }

  // ... actual handler logic
}
```

## What this catches

- **Casual scraping from another website.** A site that embeds an `<iframe>` or `<script>` calling your endpoint loses immediately. The browser sends the wrong Origin; the request is rejected.
- **Common automated abuse.** Many bot frameworks send recognizable Origin/Referer values that are easy to filter out.
- **Misconfigurations.** A staging deployment that points at production by accident gets rejected; the staging URL isn’t in the allow-list.

## What this does NOT catch

- **Determined attackers.** A custom script can omit Origin or set it to whatever it wants. The validation can’t tell a real browser from a curl request that sets `Origin: https://yourapp.com` manually.
- **Server-side calls from other apps.** If someone’s backend calls your endpoint, they can set whatever headers they want.
- **Replay attacks.** Recording a legitimate request and replaying it later, even from a different origin, may succeed if the request didn’t include freshness markers.

The pattern raises the floor; it doesn’t make the endpoint impervious. For higher security, add: rate limiting, request signing, authentication tokens, request body size limits, CAPTCHAs for bot-detection.

## CSRF as a related-but-separate concern

Origin validation also serves as CSRF defense for state-changing endpoints. CSRF (cross-site request forgery) works because a browser will attach the user’s cookies to a request initiated by another origin (in a `<form>` submission, for example). Origin validation rejects the request before the cookies matter.

For sites using SameSite=Strict cookies, browsers don’t send cookies cross-origin anyway, so CSRF is largely solved by cookie configuration. Origin validation is a defense in depth.

## Anti-patterns

**Allow-listing `*` or any regex that matches everything.** Defeats the purpose. If you want to allow all origins, just don’t validate.

**Allow-listing the wildcard subdomain when you only need exact subdomains.** `*.yourapp.com` allows `attacker-controlled.yourapp.com` if subdomains aren’t tightly controlled. Be specific.

**Trusting the `Host` header instead of `Origin`.** Host is the destination, not the source. A request from a malicious origin will still have `Host: yourapp.com`. Use Origin.

**Origin allow-list in code that’s not committed.** A dev-only allow-list of localhost works only when committed alongside the production allow-list. Don’t gate it behind a `.env.local` value that breaks in CI.

**Forgetting that POST without preflight isn’t always blocked.** A `POST` with `Content-Type: text/plain` doesn’t trigger a CORS preflight, so the browser sends the request and *then* rejects the response. The endpoint still received and processed the request. Origin validation rejects before processing; CORS rejects after. Use both.

## Negative consequences

- **Legitimate users with browser extensions can hit false positives.** Some extensions strip the Origin header or set it to a custom value. Rare but real. Add an explicit error message that helps users diagnose.
- **Allow-list maintenance.** Every new deployment domain (preview deployments on Vercel, staging environments, custom domains) must be added. Mitigation: pattern-match for known-safe domains (e.g., your Vercel preview URLs).
- **Doesn’t help against authenticated abuse.** A signed-in user calling your endpoint with a script bypasses origin validation (they can spoof Origin) and rate limiting (they have valid credentials). The endpoint needs rate limiting per authenticated user too.
- **Edge cases with native apps.** If you ship a mobile app or desktop app that calls your API, those clients won’t send a browser-style Origin. Either give them an alternative authentication method (API key, OAuth) or add a no-Origin allow-list path with token authentication.

## Verification

Test cases for the origin validation:

```ts
describe('origin validation', () => {
  it('accepts allowed origin', () => {
    const req = new Request('https://yourapp.com/api/x', {
      headers: { origin: 'https://yourapp.com' },
    })
    expect(isOriginAllowed(req)).toBe(true)
  })

  it('rejects unknown origin', () => {
    const req = new Request('https://yourapp.com/api/x', {
      headers: { origin: 'https://attacker.com' },
    })
    expect(isOriginAllowed(req)).toBe(false)
  })

  it('rejects request with no origin or referer', () => {
    const req = new Request('https://yourapp.com/api/x')
    expect(isOriginAllowed(req)).toBe(false)
  })

  it('falls back to Referer when Origin is absent', () => {
    const req = new Request('https://yourapp.com/api/x', {
      headers: { referer: 'https://yourapp.com/page' },
    })
    expect(isOriginAllowed(req)).toBe(true)
  })

  it('rejects suspicious Referer', () => {
    const req = new Request('https://yourapp.com/api/x', {
      headers: { referer: 'https://attacker.com/page' },
    })
    expect(isOriginAllowed(req)).toBe(false)
  })
})
```

For a deliberate-violation pass: temporarily remove the `isOriginAllowed` check from the endpoint and confirm a test that simulates a cross-origin request now succeeds (it should fail when the check is restored).

## Related

- `patterns/llm/rate-limiting-multi-layer.md` (Session 2B) — companion pattern for endpoints that proxy expensive LLM calls.
- `patterns/llm/error-sanitization.md` (Session 2B) — for endpoints that might leak internal details in error responses.
