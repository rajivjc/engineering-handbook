# Bootstrapping a new project from this handbook

This guide assumes you’ve cloned or are looking at this handbook and you’re starting a new project. The steps below establish the engineering discipline before you write any feature code.

## Step 1: Decide what kind of project this is

Different patterns apply to different shapes of project:

- **Web app (Next.js + Postgres typical).** See `patterns/web/`. Defense-in-depth authorization, RLS guards, atomic state via RPC, server actions formula all apply.
- **LLM-proxy app.** See `patterns/llm/` and `security/owasp-llm-checklist.md`. Prompt-injection threat model, tool-use authorization, and token-budget patterns are the load-bearing ones.
- **Both.** A web app that also calls LLMs (chatbot UI on top of a Postgres-backed app) needs both pattern sets. Plan for both, don’t pick one and hope.
- **Library or CLI.** Many universal patterns still apply (mock/real parity, single source of truth, deliberate-violation verification). The web/llm/security pattern sets probably don’t.

If the project is genuinely greenfield, write a one-paragraph project sketch before going further. The shape of the project determines which principles you’ll lean on hardest.

If you’re bringing the handbook to a project that’s already running, do a one-time audit pass first. Pick the loudest pattern that applies (often defense-in-depth authorization), retrofit it, and ship the retrofit as its own session. Don’t try to apply every principle in one go; that’s a refactor, not a bootstrap.

## Step 2: Create the canonical agent context file

- Copy `onboarding/CLAUDE.md.template` to `CLAUDE.md` at the new project’s root.
- Fill in placeholders: project name, tech stack, role hierarchy, timezone, route groups (if Next.js), modules (if you have any).
- Include the four-step verification sequence verbatim. Your project gets the same gate.
- If you’re using an agent that reads `AGENTS.md` (some do, some don’t), copy `onboarding/AGENTS.md.template` and fill in framework-version warnings and known agent mistakes for the stack you’re using.

This file is read at the start of every agent session. Keep it tight; everything in it is a hard rule.

## Step 3: Establish the verification sequence

- Add a `package.json` script for each step: `lint`, `build`, `test`, `typecheck`. The exact command depends on your stack (`npx tsc --noEmit`, `npm run build`, `npm run lint`, `npx vitest run` for the typical Next.js shape).
- In your CI, run all four. Fail the build if any fails.
- Document this rule in `CLAUDE.md` under “Mandatory verification sequence.”
- Resist the urge to skip steps for speed. `tsc --noEmit` in particular catches bugs the other three miss; vitest transpiles via esbuild without type-checking, and `next build` doesn’t type-check files outside the app’s import graph.

## Step 4: Pick the principles that apply

Read `principles/` start to finish. Most projects need three of the five immediately:

- [`defense-in-depth-authorization.md`](../principles/defense-in-depth-authorization.md) — any project with auth. Three layers: route, server action, database. Each catches a different class of mistake.
- [`mock-real-parity.md`](../principles/mock-real-parity.md) — any project with external dependencies you don’t want in dev/CI. Every data-layer function has a real branch and a mock branch, both kept in sync.
- [`atomic-state.md`](../principles/atomic-state.md) — any project with multi-row mutations. Mutations live inside a database function; the application calls the function as a single RPC.

The other two layer in when their preconditions show up:

- [`single-source-of-truth.md`](../principles/single-source-of-truth.md) — applies once you have a value flowing to multiple surfaces (PDF + UI, CSV + API, etc.). Compute once, project to every surface.
- [`module-boundary-discipline.md`](../principles/module-boundary-discipline.md) — applies once you have modules. Commit to lift-out-able or host-folded explicitly; “boundary by convention” is the failure mode.

Don’t adopt principles you don’t need. A library or CLI has no auth and no RLS; bolting on defense-in-depth is theater. The handbook’s value is in honest application, not checklist completeness.

## Step 5: Set up convention guard tests

For any “we never do X” rule, write a convention guard test. The handbook’s `patterns/universal/convention-guard-tests.md` (Session 2A) will document the pattern in full. Common ones for a typical web stack:

- Timezone hardcoding — no `new Date()` without explicit timezone handling.
- RLS NULL-coalescence — every RLS policy clause coalesces role-check function calls.
- `server-only` import boundary — every data-layer file starts with `import 'server-only'`.
- Module imports — the grep-based boundary test for any lift-out-able module.

Write these tests early. They’re cheap to add when the codebase is small and expensive to retrofit when it isn’t. Each guard you add should also get a deliberate-violation pass: introduce a fake violation, confirm the guard fails, remove the violation. A guard that hasn’t been deliberate-violated is functionally untested — see [`decisions/examples/deliberate-violation-verification.md`](../decisions/examples/deliberate-violation-verification.md).

## Step 6: Set up the audit workflow

- Decide where audits run. The handbook recommends in chat (a fresh Claude Chat session per audit), not in CI; see `process/audit-methodology.md` (Session 2B). Audits in chat get human judgment on findings classification; audits in CI degrade to “did the build pass.”
- Adopt the audit-prompt template in `onboarding/audit-prompt.template.md`. Run it after every session’s commit.
- Findings classification: critical / medium / lower / observation. Critical and medium block the next session; lower and observation can defer.

## Step 7: Start writing sessions

- Use the spec-prompt template in `onboarding/spec-prompt.template.md`.
- Each session: structured prompt → execute → audit → fix-up.
- Single commit per session. The session number, the deliverables, and the audit findings live in the same git history.
- Keep sessions small enough to fit on one screen. If the objective doesn’t fit in a paragraph, split.
- Write the spec prompt as if you were briefing a new contributor. Source material to mine, deliverables, constraints, out-of-scope. The agent doesn’t have your context until you write it down.
- After the audit, if findings are critical or medium, run a fix-up session with its own commit. Don’t amend. The audit trail is the value.

## Step 8: Maintain ADRs as you go

- When you make a decision that’s not obvious, write an ADR.
- Use the ADR format in [`decisions/adr-format.md`](../decisions/adr-format.md).
- Include negative consequences honestly. The Consequences section that’s all positive is the smell that the ADR isn’t finished yet.
- ADRs are immutable. When a decision is overturned, write a new ADR that supersedes the old one. Don’t edit the original.

The trail of ADRs is what makes the project legible to your future self. The handbook’s [`decisions/examples/`](../decisions/examples/) has three worked examples to crib from.
