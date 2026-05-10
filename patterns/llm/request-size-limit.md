# Request size limit

**Category:** llm
**Applies to:** any endpoint that forwards user content to a paid LLM provider, or that performs expensive processing per byte of input.

## Problem

LLM providers charge per token. A token is roughly 4 characters of English text. A 100KB request — easily achievable by pasting a few PDFs’ worth of content — is around 25,000 input tokens. At provider list prices, that’s a non-trivial cost per request.

Without a size limit, a single user (or attacker) can:

- Burn through your daily budget in a few minutes by submitting maximum-sized requests.
- Crash your endpoint by submitting requests larger than your runtime can handle (memory limits, transport timeouts).
- Trigger provider-side errors that you then have to handle and possibly pay for partial completions.
- Send injection attacks with maximum payload to maximize the chance one variant slips past detection.

The fix is bounded: cap the number of bytes the endpoint will accept, *before* you do anything else with the request.

## Mechanism

A check at the very top of the route, before parsing, validation, or any other processing.

```ts
// src/lib/llm/limit-request-size.ts
import 'server-only'

export const MAX_REQUEST_BYTES = 32 * 1024  // 32 KB
export const MAX_PROMPT_TOKENS = 8_000      // ~32KB at 4 chars/token

export class RequestTooLargeError extends Error {
  constructor(public actualBytes: number) {
    super(`Request body too large: ${actualBytes} bytes`)
  }
}

export async function readBodyWithLimit(request: Request): Promise<string> {
  const contentLength = request.headers.get('content-length')
  
  // Cheap rejection if the header is honest
  if (contentLength) {
    const declared = parseInt(contentLength, 10)
    if (Number.isFinite(declared) && declared > MAX_REQUEST_BYTES) {
      throw new RequestTooLargeError(declared)
    }
  }

  // Header could be missing or wrong; enforce while reading
  const reader = request.body?.getReader()
  if (!reader) return ''

  const chunks: Uint8Array[] = []
  let totalBytes = 0
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    if (!value) continue
    
    totalBytes += value.byteLength
    if (totalBytes > MAX_REQUEST_BYTES) {
      reader.cancel()
      throw new RequestTooLargeError(totalBytes)
    }
    chunks.push(value)
  }

  return new TextDecoder().decode(concatChunks(chunks))
}

function concatChunks(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, c) => sum + c.byteLength, 0)
  const result = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    result.set(chunk, offset)
    offset += chunk.byteLength
  }
  return result
}
```

Used at the top of the route:

```ts
// src/app/api/llm/route.ts
import { readBodyWithLimit, RequestTooLargeError } from '@/lib/llm/limit-request-size'

export async function POST(request: Request) {
  // ... origin validation, rate limiting

  let body: string
  try {
    body = await readBodyWithLimit(request)
  } catch (err) {
    if (err instanceof RequestTooLargeError) {
      return new Response(
        JSON.stringify({ error: 'Request too large', code: 'request_too_large', maxBytes: 32768 }),
        { status: 413, headers: { 'Content-Type': 'application/json' } }
      )
    }
    throw err
  }

  // body is now guaranteed to be under MAX_REQUEST_BYTES bytes
  // ... continue to validation, prompt injection detection, etc.
}
```

## Why both header check and stream check

The `Content-Length` header is sometimes absent (chunked transfer) and is unreliable when present (the client controls it; an attacker can lie). The stream check enforces the limit even if the header is wrong. The header check is a cheap optimization for honest clients — most rejections happen before reading any body bytes.

## What about the prompt token count?

A 32 KB request is bounded in *bytes*, not *tokens*. Different content tokenizes differently — code is denser than English, certain languages tokenize less efficiently. After parsing the body, count tokens and reject again if the user’s content exceeds the prompt budget:

```ts
import { encode } from '@/lib/llm/tokenizer'  // your provider's tokenizer

const userPrompt = parseAndExtract(body)
const tokens = encode(userPrompt).length

if (tokens > MAX_PROMPT_TOKENS) {
  return new Response(
    JSON.stringify({ error: 'Prompt too long', code: 'prompt_too_long', maxTokens: MAX_PROMPT_TOKENS }),
    { status: 413, headers: { 'Content-Type': 'application/json' } }
  )
}
```

The token check protects against a worst-case input (e.g., a unicode-dense language that produces many tokens per byte). Layer it after the byte limit, not in place of it.

## Choosing the limit

The right number depends on your use case:

- **Pure conversational endpoint** (a chatbot taking short queries): 4–8 KB. Anything larger is suspicious.
- **Document summary**: 32–128 KB. Still bounded; a 100-page PDF is way more than needed.
- **Code review**: 32–64 KB. Realistic limit for “review this file.”
- **Streaming long content**: harder. If users legitimately need to send large content, consider chunked processing rather than raising the per-request cap.

In every case, the limit is based on *legitimate use cases plus headroom*, not on what the LLM provider will technically accept. A model that accepts 200 KB doesn’t mean your endpoint should.

## Anti-patterns

**Reading the whole body, then checking size.**

```ts
// Wrong — already loaded the full body into memory before checking
const body = await request.text()
if (body.length > MAX_BYTES) return new Response('Too large', { status: 413 })
```

A 100 MB request will allocate 100 MB of memory before being rejected. The streaming check above bounds memory to the limit.

**Trusting `Content-Length` alone.** The header is a hint. An attacker sends `Content-Length: 100` and then 100 MB of body. If you trusted the header to allocate, you’ve already accepted the work.

**Using the framework’s default limit.** Many frameworks have a default request size (often 1 MB or 4 MB). For LLM endpoints this is *way* too high. Override explicitly; don’t trust the default.

**Letting the limit be application-wide.** Different endpoints have different needs. Apply per-endpoint limits, not one global limit.

**Returning a generic 400 instead of 413.** HTTP 413 (Payload Too Large) is the right status. Clients can react specifically; logs and metrics group correctly.

**Forgetting to enforce on the streaming path.** If your endpoint supports streaming responses, the *request* path still needs the check. It’s the request size that costs money, not the response.

## Negative consequences

- **Legitimate users with large content hit the wall.** Document upload features need to handle this gracefully — chunked upload, server-side splitting, or a “your file is too long, summarize chunk by chunk” UX.
- **The byte limit and token limit are duplicative.** Both need to exist (bytes guard against memory abuse; tokens guard against provider cost). Two limits to tune, two error responses.
- **Tokenizer cost.** Encoding the user’s prompt to count tokens adds a few milliseconds and depends on the provider’s tokenizer being available. For high-volume endpoints, consider an estimate (bytes ÷ 3 as a rough lower bound on tokens) for the early rejection path, with the precise count later.
- **Streaming cancellation isn’t always immediate.** Calling `reader.cancel()` doesn’t guarantee the upstream client stops sending; you might receive more bytes after the cancel call. The check should bail on the read loop, not assume cancellation happens instantly.

## Verification

Three test cases:

```ts
describe('readBodyWithLimit', () => {
  it('accepts requests under the limit', async () => {
    const body = 'a'.repeat(1000)
    const req = new Request('http://x/api', { method: 'POST', body })
    const result = await readBodyWithLimit(req)
    expect(result).toBe(body)
  })

  it('rejects requests with declared Content-Length over the limit', async () => {
    const req = new Request('http://x/api', {
      method: 'POST',
      body: 'a'.repeat(100),
      headers: { 'Content-Length': String(MAX_REQUEST_BYTES + 1) },
    })
    await expect(readBodyWithLimit(req)).rejects.toThrow(RequestTooLargeError)
  })

  it('rejects requests where actual bytes exceed limit even with no Content-Length', async () => {
    const body = 'a'.repeat(MAX_REQUEST_BYTES + 1)
    const req = new Request('http://x/api', { method: 'POST', body })
    await expect(readBodyWithLimit(req)).rejects.toThrow(RequestTooLargeError)
  })
})
```

The third test is load-bearing — it verifies the streaming check works regardless of header. Without it, the test passes for honest clients only.

For an integration check, send an actual 100 KB request to the running endpoint and confirm 413 returns *fast* (under 100ms) — proving the rejection happens before reading the whole body, not after.

## Related

- `patterns/llm/rate-limiting-multi-layer.md` — bounds request *count*; this pattern bounds request *size*. Pair them.
- `patterns/llm/prompt-injection-detection.md` — runs after size limit, on the bounded input.
- `patterns/web/origin-validation.md` — runs first, cheapest rejection.
