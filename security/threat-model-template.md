# Threat model template

A structured way to think about what can go wrong in your application before it does. STRIDE-style — Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege — applied to your specific architecture.

This template is for one-time use per major feature or system. Fill it in, file it with the project's security docs, revisit when the architecture changes meaningfully.

For LLM-specific threats, complement this with `security/owasp-llm-checklist.md`.

## How to use this template

1. Identify the system you're modeling (one feature, one service, or the whole app).
1. List the assets — what data and capabilities are at stake.
1. Draw the trust boundaries — where untrusted input crosses into trusted code, where one user's data crosses into another user's context.
1. For each boundary, walk STRIDE: enumerate threats, identify mitigations (existing or needed), record accepted risks.
1. Produce the summary at the bottom — what's mitigated, what's accepted, what's open.

The template is most useful when written *before* implementation. It scales down: a 30-minute pass produces a usable threat model for a single feature; a multi-hour pass produces a thorough one for a whole system.

## Worked example: an LLM proxy endpoint

The shape of a filled-in template, using a hypothetical LLM proxy endpoint as the system being modeled. Use this shape; substitute your own content.

---

### System under analysis

A web application exposes `/api/llm/summarize`, which accepts user-submitted text and returns an LLM-generated summary. Authentication is required; results are not stored.

### Assets

- The LLM provider account and its budget.
- The system prompt (proprietary; identifies the application's purpose).
- User-submitted text (may contain PII).
- Provider API keys (server-side secret).
- The application's reputation if abuse goes public.

### Trust boundaries

- Browser → API endpoint (untrusted client; HTTP boundary).
- API endpoint → LLM provider (trusted server; HTTPS to a third party).
- LLM provider → API endpoint (response; treat as untrusted per LLM02).
- API endpoint → browser (response back to user).

### STRIDE walk

#### Spoofing (S)

|Threat                                                          |Mitigation                                                  |Status                                         |
|----------------------------------------------------------------|------------------------------------------------------------|-----------------------------------------------|
|Anonymous user calls the endpoint pretending to be authenticated|Session auth required; cookies are HttpOnly+SameSite=Lax    |Mitigated                                      |
|Cross-origin form submits the request                           |Origin/Referer validation rejects cross-origin POSTs        |Mitigated (`patterns/web/origin-validation.md`)|
|User A's session is stolen via XSS                              |No model-generated content is rendered as HTML; CSP in place|Mitigated                                      |

#### Tampering (T)

|Threat                                                              |Mitigation                                                                 |Status                                          |
|--------------------------------------------------------------------|---------------------------------------------------------------------------|------------------------------------------------|
|User modifies their request to inject content into the system prompt|Server constructs the prompt; client only provides the user-content portion|Mitigated                                       |
|User submits a malformed request to cause unexpected branching      |Input validation rejects malformed JSON; size limit caps payload           |Mitigated (`patterns/llm/request-size-limit.md`)|
|Network attacker tampers with response in transit                   |HTTPS enforced                                                             |Mitigated                                       |

#### Repudiation (R)

|Threat                                                        |Mitigation                                                                                    |Status   |
|--------------------------------------------------------------|----------------------------------------------------------------------------------------------|---------|
|User claims a request was made by someone else                |All requests logged with user ID, timestamp, and IP                                           |Mitigated|
|User claims their data was sent to the provider when it wasn't|Server logs the prompt sent to the provider (redacted PII per `patterns/llm/pii-redaction.md`)|Mitigated|

#### Information Disclosure (I)

|Threat                                                          |Mitigation                                                                       |Status                                    |
|----------------------------------------------------------------|---------------------------------------------------------------------------------|------------------------------------------|
|Provider error message leaks API key prefix                     |Error sanitization (`patterns/llm/error-sanitization.md`)                        |Mitigated                                 |
|User submits PII; PII appears in provider logs                  |PII redaction (`patterns/llm/pii-redaction.md`)                                  |Partial (regex catches common shapes only)|
|System prompt is extracted via injection ("show me your prompt")|Injection detection rejects common shapes; system prompt contains no true secrets|Partial; accepted risk                    |
|Another user's data is included in the prompt context           |Per-user scoping; the endpoint reads only the current user's data                |Mitigated                                 |
|Server logs leak PII                                            |Log redaction same as prompt redaction                                           |Mitigated                                 |

#### Denial of Service (D)

|Threat                                                                 |Mitigation                                                       |Status   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------|---------|
|One user submits thousands of requests                                 |Per-user rate limit (`patterns/llm/rate-limiting-multi-layer.md`)|Mitigated|
|One IP submits thousands of requests across fake accounts              |Per-IP rate limit                                                |Mitigated|
|Distributed abuse from many IPs exhausts provider budget               |Global rate limit                                                |Mitigated|
|One request submits a huge payload                                     |Request size limit (`patterns/llm/request-size-limit.md`)        |Mitigated|
|Model `max_tokens` not capped; one request consumes large output budget|`max_tokens` set explicitly at ~1000                             |Mitigated|

#### Elevation of Privilege (E)

|Threat                                                                 |Mitigation                                                    |Status   |
|-----------------------------------------------------------------------|--------------------------------------------------------------|---------|
|Anonymous user gains access to authenticated-only data via the endpoint|Auth check at top of handler                                  |Mitigated|
|Regular user gains admin powers via the endpoint                       |Endpoint does not perform privileged actions; LLM has no tools|N/A      |

### Accepted risks

- **Sophisticated prompt injection bypasses regex detection.** Detection is best-effort; we accept residual risk. Periodic review of detection patterns. Considered acceptable because: low blast radius (the endpoint has no tools; the worst case is incorrect summary output, not data corruption or escalation).
- **PII redaction is heuristic.** Names and addresses can pass through. Mitigated by UX: users are warned that submissions may be sent to the provider; consent obtained at sign-up.
- **System prompt is extractable.** No true secrets are placed in the system prompt. Treated as public.

### Open questions

- *(In a real document, list anything you noticed during the walk that doesn't yet have a clear mitigation or acceptance.)* Example: "What's our response if the provider has a data-breach notification? We don't have a runbook yet."

### Summary

This LLM proxy is mitigated against the high-severity threats in S/T/R/D/E. Information disclosure has two partial mitigations (PII heuristics; prompt extractability) which are accepted with rationale. No tooling for LLM07/LLM08-style agentic threats, which is N/A given the endpoint is read-only.

---

## Template (blank — copy and fill in)

```
### System under analysis

[One paragraph: what is the system? What does it do? Where does it sit in the
larger architecture?]

### Assets

[Bulleted list of what's at stake. Data, capabilities, reputation, money.]

### Trust boundaries

[Bulleted list of boundaries. "Untrusted X crosses to trusted Y over Z transport."]

### STRIDE walk

For each of the six categories below, list threats with two columns:
mitigation (or "none yet") and status (mitigated / partial / accepted /
open / N/A).

#### Spoofing
#### Tampering
#### Repudiation
#### Information Disclosure
#### Denial of Service
#### Elevation of Privilege

### Accepted risks

[Threats you've identified but decided to accept. Each has a rationale.]

### Open questions

[Anything that came up during the walk and isn't resolved.]

### Summary

[A few sentences summarizing the threat posture. What's strong, what's
partial, what's accepted. Treat this as the document's executive summary.]
```

## Anti-patterns

**Threat models that read like compliance checklists.** "We considered XSS, CSRF, SQL injection, …" If every line is a generic threat with a generic mitigation, the model wasn't specialized to your system. STRIDE applied *specifically* to your trust boundaries is what makes it useful.

**Threat models written after implementation.** A model written post-hoc tends to ratify the existing code rather than identify gaps. Write it before or during implementation; revise when reality diverges.

**Threat models that never get revisited.** Architectures change. The model that was accurate six months ago may be wrong now. Revisit on every significant change; re-walk STRIDE.

**Accepted risks without rationale.** "Accepted." Why? Six months later, when the person who accepted it is gone, you can't tell if the acceptance was reasoned or lazy. Always state *why* a risk is acceptable.

**Threat models that try to enumerate every conceivable threat.** Pareto applies; the 80% of useful threats come from systematically walking STRIDE for each trust boundary. Trying to be exhaustive produces a document nobody reads.

**Threat models without "open questions."** Real systems have unresolved questions. A model with none is either trivially small or hasn't been examined carefully.

## Negative consequences

- **Time investment.** A thorough threat model for a substantial feature is 2–8 hours of focused work. For small features, scale down.
- **Threat models age.** A model written for the architecture-as-of-Q1 isn't the model for the architecture-as-of-Q3 if there have been significant changes. Treat the model as a living document; the cost of re-walking is bounded by the cost of the original walk.
- **The model is only as good as its author's imagination.** Threats not enumerated aren't mitigated. STRIDE provides structure; it doesn't guarantee completeness. Pair-modeling (two engineers walk together) catches more than solo modeling.
- **False confidence.** "We have a threat model" doesn't mean "we're secure." The model identifies threats; mitigations have to be implemented and tested. Don't confuse the artifact with the work.

## Related

- `security/owasp-llm-checklist.md` — complements this template for LLM-using systems.
- `principles/defense-in-depth-authorization.md` — the philosophy behind layering mitigations.
- `case-studies/01-security-rls-leak.md` — a worked example of how a threat model might (or might not) have caught a real bug.
- `decisions/adr-format.md` (Session 1) — accepted risks often warrant ADRs documenting the decision.
