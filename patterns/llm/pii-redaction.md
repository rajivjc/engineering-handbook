# PII redaction

**Category:** llm
**Applies to:** any LLM endpoint where user input might contain personally-identifiable information that you’d rather not send to a third-party provider.

## Problem

LLM provider APIs are governed by their terms of service. Most providers commit to not training on API traffic by default, but the data still:

- Travels across your network and theirs.
- Sits in their logs for some retention window (often 30 days).
- Is accessible to provider staff under specific circumstances.
- May be subject to compliance requirements (HIPAA, GDPR, SOC 2) you’ve taken on for your own users that the provider hasn’t taken on for you.

For some applications this is fine. For others — anything healthcare, financial, government, or with strong privacy commitments — it isn’t. You promised your user that their email address, phone number, or government ID stays in your system. Once it’s in a provider’s logs, that promise is partial.

The fix: detect and redact common PII shapes from user input *before* sending to the provider. The redacted version goes to the LLM; a mapping kept server-side lets you re-insert the original values into the model’s response if needed.

## Mechanism

A redaction function with a small set of well-tuned patterns and a server-side mapping:

```ts
// src/lib/llm/redact-pii.ts
import 'server-only'
import crypto from 'node:crypto'

interface RedactionResult {
  redacted: string                    // text to send to LLM
  mapping: Map<string, string>        // placeholder -> original
}

const PATTERNS: { name: string; pattern: RegExp; replace: (match: string, idx: number) => string }[] = [
  {
    name: 'email',
    pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
    replace: (_, i) => `[EMAIL_${i}]`,
  },
  {
    name: 'phone',
    pattern: /\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}\b/g,
    replace: (_, i) => `[PHONE_${i}]`,
  },
  {
    name: 'credit_card',
    pattern: /\b(?:\d{4}[\s-]?){3}\d{4}\b/g,
    replace: (_, i) => `[CARD_${i}]`,
  },
  {
    name: 'ssn',
    pattern: /\b\d{3}-\d{2}-\d{4}\b/g,
    replace: (_, i) => `[SSN_${i}]`,
  },
  {
    name: 'ipv4',
    pattern: /\b(?:\d{1,3}\.){3}\d{1,3}\b/g,
    replace: (_, i) => `[IPV4_${i}]`,
  },
  // Add country-specific shapes as needed (IC numbers, NHS numbers, etc.)
]

export function redactPII(input: string): RedactionResult {
  const mapping = new Map<string, string>()
  let result = input
  let counter = 0

  for (const { pattern, replace } of PATTERNS) {
    result = result.replace(pattern, (match) => {
      const placeholder = replace(match, counter++)
      mapping.set(placeholder, match)
      return placeholder
    })
  }

  return { redacted: result, mapping }
}

export function unredact(text: string, mapping: Map<string, string>): string {
  let result = text
  for (const [placeholder, original] of mapping) {
    result = result.split(placeholder).join(original)
  }
  return result
}
```

Used in the proxy:

```ts
import { redactPII, unredact } from '@/lib/llm/redact-pii'

export async function POST(request: Request) {
  // ... origin validation, rate limiting, size limit, injection detection
  const userInput = await request.text()

  const { redacted, mapping } = redactPII(userInput)

  const result = await llm.complete({
    system: SYSTEM_PROMPT,
    messages: [{ role: 'user', content: redacted }],
  })

  // If the model echoes the placeholders back, restore the original values
  // for the user. The model never sees the originals.
  const finalText = unredact(result.text, mapping)

  return new Response(JSON.stringify({ text: finalText }), { status: 200 })
}
```

## What goes in the LLM, what stays on your server

The provider sees:

```
Hello, my email is [EMAIL_0] and my phone is [PHONE_1]. Can you draft a reply?
```

Your server keeps the mapping:

```
[EMAIL_0] -> alice@example.com
[PHONE_1] -> 555-1234
```

The model’s response might be:

```
Sure. Reply: "Hi Alice, thanks for reaching out. I'll send details to [EMAIL_0] shortly..."
```

After unredaction, the user sees:

```
"Hi Alice, thanks for reaching out. I'll send details to alice@example.com shortly..."
```

The PII never reached the provider. The user gets a useful response with the right values restored.

## Patterns to include vs. patterns to skip

**Worth catching:**

- Email addresses (high-confidence regex; nearly always want to redact).
- Phone numbers (multiple country shapes; tune for your user base).
- Credit card numbers (a Luhn check makes false positives near-zero).
- Government IDs in your jurisdiction (US SSN, UK NI numbers, Singapore IC, India PAN).
- IPv4 / IPv6 addresses.

**Not worth catching with regex:**

- Names. Far too many false positives (every capitalized word). Use NER (named entity recognition) only if you really need to, and even then expect noise.
- Addresses. Too varied across countries and formats. Whole-line redaction is too aggressive; structured detection is fragile.
- Birthdates. Date formats are wildly varied; false positives are constant.

For names and addresses, the better strategy is *pre-filtering at the application level* — don’t accept these fields into the LLM endpoint at all, or use a structured form that separates PII from free text.

## Anti-patterns

**Hashing instead of placeholder-with-mapping.** A hash gives no roundtrip; the model can’t refer to the entity meaningfully, and you can’t restore the original on output. Mapping with reversible placeholders is the right approach for typical use cases.

**Unique placeholder per occurrence.** `[EMAIL_0]`, `[EMAIL_1]`, `[EMAIL_2]` for three different emails is correct. But `[EMAIL_0]` for *all* emails in the same input means the model can’t tell them apart; if Alice and Bob both appear, the response treats them as one person.

**Same placeholder reused across different request sessions.** A naive global counter ages; restart and `[EMAIL_0]` now means a different value. Scope counters per request.

**Logging the mapping.** Defeats the purpose. The mapping is the very thing you’re protecting; it lives in memory for the duration of the request and is not persisted.

**Trusting the regex set to be complete.** “We redact emails, so we’re GDPR-compliant.” False. The regex catches common shapes; sophisticated PII (long-form addresses, narrative descriptions of identifying details) gets through. The pattern is risk reduction, not compliance certification.

**Forgetting to redact on retry.** If your endpoint retries on transient errors, each retry must redact independently — using the original text, not the previous redacted version (lest placeholders accumulate).

## Negative consequences

- **The redaction set ages.** New PII categories emerge as products evolve. The set needs review when adding new countries, new compliance domains, new data types your users handle.
- **False positives.** A regex for credit cards (16 digits with separators) catches some product codes and order IDs. The Luhn check helps; perfect accuracy is impossible.
- **False negatives.** PII that doesn’t fit a regex shape — a name, an address described in prose, a sensitive fact like “the patient with diabetes who lives near the bakery” — passes through. Regex is partial defense.
- **Loss of context.** “I work at [COMPANY_0]” is less useful to the LLM than “I work at Anthropic” — the model can’t reason about the specifics. Some tasks degrade in quality with redaction. Decide upfront whether the loss is acceptable.
- **The mapping must stay in memory only.** Persisting mappings (e.g., to recover from retries) creates the very risk the redaction was meant to prevent. Keep mappings ephemeral; rebuild from the original text if needed.

## When NOT to use this pattern

- The endpoint deliberately processes PII (e.g., a patient-record summarizer) and the user has consented and the provider has signed appropriate agreements. Redaction defeats the use case.
- The application is internal-only and the LLM is self-hosted. The data never leaves your infrastructure.
- The regulatory regime requires bytewise control of where data flows; redaction is partial mitigation but doesn’t satisfy strict requirements. Use a self-hosted model.

The pattern is for the typical case: third-party LLM, public-internet user-generated content, plausible-but-not-certain presence of PII, and you’d rather err on the side of not sending it.

## Verification

```ts
describe('redactPII', () => {
  it('replaces emails with placeholders and preserves the mapping', () => {
    const { redacted, mapping } = redactPII('Email me at alice@example.com')
    expect(redacted).not.toContain('alice@example.com')
    expect(redacted).toMatch(/\[EMAIL_\d+\]/)
    
    const placeholder = Array.from(mapping.keys())[0]
    expect(mapping.get(placeholder)).toBe('alice@example.com')
  })

  it('handles multiple PII types in one input', () => {
    const input = 'Reach me at alice@example.com or 555-123-4567'
    const { redacted, mapping } = redactPII(input)
    expect(mapping.size).toBe(2)
    expect(redacted).toMatch(/\[EMAIL_\d+\]/)
    expect(redacted).toMatch(/\[PHONE_\d+\]/)
  })

  it('unredact reverses the substitution', () => {
    const original = 'Email: bob@example.com, Phone: 555-9999'
    const { redacted, mapping } = redactPII(original)
    expect(unredact(redacted, mapping)).toBe(original)
  })

  it('does not mishandle text that contains no PII', () => {
    const benign = 'What is the capital of France?'
    const { redacted, mapping } = redactPII(benign)
    expect(redacted).toBe(benign)
    expect(mapping.size).toBe(0)
  })
})
```

The fourth test is the load-bearing one for false positives. If a benign input gets transformed, your application’s behavior degrades for everyone, not just users who include PII.

A deliberate-violation pass: temporarily disable the email pattern, run the suite, confirm the email-specific test fails. Restore.

## Related

- `patterns/llm/error-sanitization.md` — companion pattern for the response side; redact data in *errors* you log.
- `patterns/llm/input-wrapping.md` — runs after redaction; the wrapped input is the redacted version.
- `security/owasp-llm-checklist.md` (Session 3) — covers LLM06 (sensitive information disclosure) which this pattern partially addresses.
