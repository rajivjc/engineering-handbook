# OWASP Top 10 for LLM Applications — handbook mapping

A checklist to walk before shipping any LLM endpoint. For each item, confirm the relevant patterns are in place or explicitly accept the risk in writing. The handbook's pattern docs are linked where they materially mitigate the threat; gaps are called out so you can decide what to add or defer.

This document is calibrated to web-app LLM proxies (a Next.js or similar app calling a hosted LLM provider). Some categories don't apply to that shape; those are noted as such rather than padded.

## How to use this checklist

For every LLM-using endpoint in your project:

1. Walk LLM01 through LLM10 below.
2. For each, identify which handbook patterns apply.
3. Confirm those patterns are implemented and tested.
4. For risks not addressed by any pattern, decide: implement an ad-hoc mitigation, accept the risk (with rationale, written into an ADR), or remove the feature.

The output of the walk is a one-page summary listing each category and its status. Refresh on every significant feature change.

## LLM01: Prompt Injection

**Threat.** An attacker crafts user input that overrides system instructions, exfiltrates the system prompt, or coerces the model into off-task behavior. Direct injection ("ignore previous instructions…") and indirect injection (malicious content in a document the LLM is asked to summarize) are both in scope.

**Handbook coverage.**

- `patterns/llm/prompt-injection-detection.md` — regex-based rejection of common direct-injection shapes, before the model is called.
- `patterns/llm/input-wrapping.md` — delimited blocks signal to the model where user content begins and ends; defends against content that didn't trip the detector.

**Not covered.** Sophisticated adversarial attacks (encoded payloads, language switching, multi-turn social engineering of the model itself) bypass regex and wrapping. For high-stakes applications, additional defenses include: narrow task scoping (don't accept free-form input where a constrained form would do), authentication and per-user accountability, and post-hoc review of model outputs.

**Verification.** The detection pattern's test suite must include known attack samples. Run a deliberate-violation pass on the detector. For wrapping: confirm the wrapped form is what reaches the model (log a sample request in development; inspect).

## LLM02: Insecure Output Handling

**Threat.** The model's output is treated as trusted input by a downstream system. Examples: rendering model output as HTML (XSS); executing model-generated SQL; following model-emitted URLs server-side; writing model output to a database without sanitization.

**Handbook coverage.**

- `patterns/llm/error-sanitization.md` — partial; covers the *error* path, not the success path. The pattern's discipline (treat output as potentially adversarial) generalizes.
- `principles/defense-in-depth-authorization.md` — informs the broader stance: don't rely on the model to enforce constraints; the post-LLM code path validates.

**Not covered explicitly.** Output-side patterns (sanitize-before-render, validate-before-execute, allowlist URLs) are general web-app patterns rather than LLM-specific. The handbook doesn't dedicate a pattern to them because they predate LLMs by decades; treat any LLM output exactly as you'd treat any user-controlled string.

**Verification.** For each downstream consumer of model output, audit: is the output rendered as HTML? Used in a SQL query? Sent to an external API? Written to a file? Each "yes" needs a sanitization step. For HTML rendering: confirm `dangerouslySetInnerHTML` (React) or equivalent is never used with model output without sanitization. For SQL: parameterized queries only; never string concatenation.

## LLM03: Training Data Poisoning

**Threat.** Malicious or biased data is introduced into a model's training data, causing systematic flaws in the model's behavior.

**Applicability to web-app LLM proxies.** Low. If you use a hosted model (Anthropic, OpenAI, Cohere), the provider controls training data. Your exposure is to the provider's choices, not your own training pipeline. If you fine-tune on user-contributed data, the threat applies and requires careful data curation; this is out of scope for this handbook.

**Verification.** Document which models you use and whether you fine-tune. If you fine-tune, define what data is included, who reviews it, and how poisoning would be detected. If you don't fine-tune, note this and revisit if the architecture changes.

## LLM04: Model Denial of Service

**Threat.** An attacker submits expensive requests to exhaust your LLM provider quota, drain your budget, or degrade service for legitimate users.

**Handbook coverage.**

- `patterns/llm/rate-limiting-multi-layer.md` — per-user, per-IP, and global request count limits.
- `patterns/llm/request-size-limit.md` — bounds per-request cost (bytes and tokens).
- `patterns/web/origin-validation.md` — rejects cross-origin abuse before counting.

**Not covered.** The model's *output* tokens can also be expensive (some providers charge more per output token than input). Cap the model's `max_tokens` parameter explicitly; don't trust defaults. Streaming endpoints need additional thinking: a request that completes in 30 seconds costs the same as one that completes in 30 minutes if the model is slow.

**Verification.** For each LLM endpoint, confirm: rate-limit layers in place, request-size limit enforced, `max_tokens` cap set. Test the limits fire — temporarily lower them to 1 and confirm the second request rejects.

## LLM05: Supply Chain Vulnerabilities

**Threat.** A compromised dependency (an npm package, a Python library, a model provider's SDK) introduces unauthorized behavior or exfiltrates data.

**Handbook coverage.**

- `patterns/universal/pin-exact-dependency-versions.md` — exact pins prevent silent dependency updates from introducing compromise.
- `process/four-step-verification-gate.md` — the gate runs after dependency changes; tests catch regressions in dependency behavior.

**Not covered explicitly.** Dependency scanning tooling (npm audit, Snyk, Dependabot) is project-level infrastructure, not a pattern. Run something. The handbook doesn't recommend one over another.

**Verification.** Confirm `package.json` and `package-lock.json` (or equivalent) are committed and pinned. Run dependency audit periodically. For LLM provider SDKs specifically, monitor the provider's security advisories.

## LLM06: Sensitive Information Disclosure

**Threat.** The LLM endpoint leaks information it shouldn't — PII in logs, system prompts in error messages, provider credentials in stack traces, customer data sent to a third party without consent.

**Handbook coverage.**

- `patterns/llm/pii-redaction.md` — strips common PII shapes from user input before sending to the provider.
- `patterns/llm/error-sanitization.md` — strips provider details, API keys, request IDs from error responses.
- `patterns/web/server-only-import-boundary.md` — the `'server-only'` annotation prevents secrets-bearing modules from being imported into client code.

**Not covered.** The model's *output* can also leak information — if you concatenate other users' data into the prompt (a multi-tenant RAG pipeline, for instance), the model can echo it back. Per-user isolation of the prompt context is a higher-level concern; ensure each user's request only includes their own data.

**Verification.** For each LLM endpoint: review the prompt assembly code; confirm the only user-data inputs are the current user's. Review the error path; trigger known error classes and inspect responses for leaks. Review server logs; confirm no API keys or full request bodies are logged in plaintext.

## LLM07: Insecure Plugin Design

**Threat.** Tool-use or function-calling integrations let the LLM trigger actions in external systems. A compromised model output (via injection or otherwise) triggers unintended actions: deleting data, transferring funds, calling external APIs with attacker-controlled arguments.

**Applicability to web-app LLM proxies.** Variable. A read-only LLM (summarizes documents; chats) has no plugins and no exposure. An agentic LLM (writes to your database; calls external APIs; sends emails) has significant exposure.

**Not covered explicitly by handbook patterns,** because agentic LLM patterns are nascent and project-specific. General guidance:

- Treat every tool call as user-initiated. The LLM is the user; the tools are subject to the same authorization as if a user clicked.
- Allowlist tool actions and their arguments. If the LLM can write to the database, restrict to specific tables and column ranges.
- Confirm destructive actions out-of-band. The LLM proposes; the user confirms.
- Log every tool call with the prompt that triggered it for post-hoc review.

**Verification.** Audit each tool exposed to the LLM. For each, confirm: authorization is enforced (the same rules as for a user action), arguments are validated (not trusted from the model), destructive actions require explicit user confirmation, all calls are logged.

## LLM08: Excessive Agency

**Threat.** The LLM is given broader permissions or autonomy than its task requires; a failure mode in the model causes unintended consequences in connected systems.

**Applicability and mitigation.** Closely related to LLM07. The mitigation is the same shape: principle of least privilege applied to the LLM's tools, scope, and authorization.

**Not covered explicitly by handbook patterns.** Same reasoning as LLM07.

**Verification.** For each LLM endpoint: list what the LLM can affect (data writes, external API calls, user-visible state). Confirm each is necessary for the endpoint's task. Remove or scope down anything that isn't.

## LLM09: Overreliance

**Threat.** Users (or downstream systems) treat LLM output as authoritative when it isn't. Hallucinations are presented as facts; incorrect code is shipped to production; misinformation is rendered in trusted UI surfaces.

**Applicability.** This is a UX and product-design concern more than a security one. Mitigations are editorial:

- Mark model-generated content clearly so users know it's AI-generated.
- For high-stakes outputs (medical, legal, financial), require human review.
- Avoid framing LLM output as a "source of truth"; frame it as a draft, a suggestion, a starting point.
- For code suggestions: don't auto-execute; let the user review.

**Not covered explicitly by handbook patterns.** Editorial guidance, not engineering pattern.

**Verification.** For each LLM-generated surface: confirm the user can tell it's AI-generated. For high-stakes outputs: confirm a human-in-the-loop step exists.

## LLM10: Model Theft

**Threat.** Unauthorized access to model weights, prompts, or training data; extraction of proprietary information via repeated queries (model extraction attacks).

**Applicability to web-app LLM proxies.** Low for the weights (the provider holds them). Moderate for prompts (a sophisticated attacker can probe to reverse-engineer your system prompt).

**Handbook coverage.**

- `patterns/llm/prompt-injection-detection.md` — partial defense against the "show me your prompt" attack class.
- `patterns/llm/rate-limiting-multi-layer.md` — slows down extraction-via-many-queries attempts.

**Not covered.** Watermarking, prompt obfuscation, and model-extraction-specific defenses are research-stage. For most applications: minimize the secret value of the system prompt (don't put true secrets in it; assume it's extractable).

**Verification.** Audit your system prompt for true secrets (API keys, customer-specific data). Remove them; put them in environment variables read at request time, not embedded in the prompt.

## Summary template

For your project's documentation, produce a table like this:

|Category                              |Status   |Patterns in place                                |Accepted risks             |Notes                                   |
|--------------------------------------|---------|-------------------------------------------------|---------------------------|----------------------------------------|
|LLM01 Prompt Injection                |mitigated|injection-detection, input-wrapping              |None                       |Re-audit detector quarterly             |
|LLM02 Insecure Output Handling        |mitigated|error-sanitization                               |None                       |Output not rendered as HTML             |
|LLM03 Training Data Poisoning         |N/A      |—                                                |We don't fine-tune         |Revisit if fine-tuning is added         |
|LLM04 Model DoS                       |mitigated|rate-limiting, request-size-limit, max_tokens cap|None                       |Tested at 10x normal load               |
|LLM05 Supply Chain                    |mitigated|pin-exact-versions, Dependabot                   |None                       |Quarterly review                        |
|LLM06 Sensitive Information Disclosure|partial  |pii-redaction, error-sanitization                |Name detection is heuristic|UX warns users                          |
|LLM07 Insecure Plugin Design          |N/A      |—                                                |We have no tools           |Revisit if tools added                  |
|LLM08 Excessive Agency                |N/A      |—                                                |Read-only LLM              |Revisit if agentic flow added           |
|LLM09 Overreliance                    |mitigated|UX labels output as AI                           |None                       |High-stakes outputs require confirmation|
|LLM10 Model Theft                     |partial  |rate-limiting                                    |System prompt not secret   |Acceptable for our use case             |

The table is the audit artifact. File it with the project's security docs; revisit on every major change.

## Related

- `security/threat-model-template.md` — STRIDE-based template that complements this checklist.
- `principles/defense-in-depth-authorization.md` — the broader stance these patterns instantiate.
- `case-studies/01-security-rls-leak.md` — a worked example of a security issue that bypassed multiple layers; instructive for calibrating "is one defense enough?" thinking.
