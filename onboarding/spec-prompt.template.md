This is the session prompt format used across the projects this handbook is extracted from. Replace placeholders in `{{double-curly braces}}` with project specifics. Send the resulting prompt to Claude Code (or your AI coding agent of choice) at session start. The structure is opinionated; the discipline is to use the same shape every session so the agent and the human both know what to look for.

---

# Session {{N}}: {{Title}}

## Objective

{{TODO: One paragraph stating concretely what this session ships. Should fit on one screen. If it spans multiple objectives, split into multiple sessions.}}

## Why this session

{{TODO: 1–3 paragraphs. What pressure motivated this session? What's broken, missing, or about to be? What's the cost of not doing it now? Surface the trade-offs the agent should be aware of.}}

## Source material to mine

{{TODO: Files, prior sessions, external references the agent should read first. Be explicit about paths. Examples:

- `src/lib/data/bookings.ts` — current shape of the data layer for this domain
- `docs/SESSIONS.md` Session 12 — earlier work on the related feature
- `patterns/web/atomic-state-via-rpc.md` — relevant pattern
- External: link to a vendor doc the agent will need
}}

## Deliverables

{{TODO: Concrete file list. Each entry: path + one-line description of what the file does. Prefer a tree to a prose list. Distinguish "create" from "modify".}}

## Inline content

{{TODO: Content the agent should write verbatim, between `<<<FILE_BEGIN>>>` / `<<<FILE_END>>>` markers. Use this for anything where the wording matters (READMEs, ADRs, principle pages). Skip this section if the session is purely code.}}

## Files Claude Code drafts

{{TODO: Files where the agent has latitude. For each, give the structural requirements: required sections (in order), length target, anything explicitly out-of-scope, anti-patterns to avoid. Do not let the agent invent structure on its own.}}

## Constraints

{{TODO: Hard rules for this session. Examples:

- No scope expansion. New patterns out of scope unless explicitly listed in deliverables.
- Do not edit files in `src/legacy/`. Those are scheduled for removal in Session N+2.
- All inline content is written byte-identical. No "improvements" or rewording.
- Single commit on `main`.
}}

## Verification

{{TODO: Numbered list of post-session checks. Always includes the four-step build verification at minimum:

1. `npx tsc --noEmit` is clean.
2. `npm run build` succeeds.
3. `npm run lint` is clean.
4. `npx vitest run` passes.
5. {{Project-specific check: e.g., manual test of the new flow in mock mode and real mode.}}
6. {{Project-specific check: e.g., audit-prompt run against the commit yields no critical findings.}}
}}

## Commit

Single commit. Suggested message:

```
{{TODO: Conventional commit summary, then a short body listing the deliverables. Keep the body skimmable for someone reading `git log` six months later.}}
```

## Out of scope

{{TODO: Explicit list of what NOT to touch. If the agent is tempted to drift, this is the page that pulls them back. Examples:

- New patterns (deferred to Session N+1)
- Refactors of existing modules (separate session)
- Documentation outside the deliverables list
- Anything in `src/legacy/`
}}

---

The `<<<FILE_BEGIN>>>` / `<<<FILE_END>>>` marker convention exists to wrap content that itself contains code fences. Custom delimiters avoid the parsing ambiguity that triple-backtick wrapping introduces.
