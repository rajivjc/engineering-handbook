---
name: session-prompt-author
description: Write session prompts to hand to a coding agent (Claude Code, Cursor, etc.) for AI-driven engineering work. Use this skill when the user is about to delegate a discrete unit of work to an agent and needs a structured prompt — typically when they say "write me a session prompt," "let's spec the next session," "draft the prompt for X feature," or similar. Produces a markdown document following the template in `process/session-prompt-template.md` of this handbook, with explicit objective, deliverables, constraints, verification, and out-of-scope sections.
---

# Session prompt author

This skill helps draft prompts for coding agents working on substantial pieces of work. The output is a structured markdown document that follows the engineering-handbook's session-prompt template.

## When to use this skill

Use when the user wants to:

- Spec a feature, refactor, migration, or other unit of work for an AI coding agent to execute.
- Write a prompt that will be handed to Claude Code, Cursor, or similar.
- Produce a prompt that's tight enough to prevent scope drift but loose enough to leave implementation judgment to the agent.

Do **not** use when the user wants:

- A general project plan or PRD (those are higher-level).
- A conversational walk-through of a coding task (the user can just ask).
- Documentation of completed work (use a session-summary or handover format instead).

## Workflow

1. **Establish scope.** Ask the user (or infer from context) what the session is meant to accomplish. The objective fits in two sentences; if you can't write those two sentences, the scope isn't ready.
2. **List deliverables.** Identify the concrete output: files to create, files to modify, schema changes, public-facing API surface. Count them. If the count is over ~20 files, suggest splitting into multiple sessions.
3. **Identify constraints.** Ask: which patterns or conventions must be followed? Which files must NOT be modified? What's the project's testing discipline? Refer to the project's AGENTS.md / CLAUDE.md if present.
4. **Define verification.** State explicitly what proves the session is done. Usually: the project's verification gate (typecheck + build + lint + tests), plus session-specific checks (new tests exist, deliberate-violation passes performed, cross-references resolve).
5. **List out-of-scope items.** What this session is *not* doing, even though it could. Include rationale or a forward reference.
6. **Draft the prompt.** Use the template structure below.

## Template

```markdown
# Session [N]: [short descriptive name]

## Objective

[Two sentences. What this session ships. Why now.]

## Precondition

[What state the repo must be in. Often: previous session is merged, a
specific commit is the parent.]

## Why this session

[The pressure that forced this work. What's deferred. What this unblocks.]

## Deliverables

[Numbered list. For each file or output:
- File path (full, exact)
- Brief description of what changes / what it contains
- Acceptance criterion if non-obvious]

## Constraints

[Non-obvious rules:
- Patterns to follow (cite by path)
- Files NOT to modify (explicit list)
- Style or naming conventions specific to this session
- Anti-patterns explicitly forbidden]

## Verification

[What proves the session is done:
- The four-step gate must pass: typecheck, build, lint, tests
- Specific tests that must exist
- Specific behaviors that must be demonstrated
- Deliberate-violation passes if required]

## Audit (post-session)

[What will be checked after the agent declares done.]

## Commit

[Expected commit shape: single commit, suggested message format.]

## Out of scope

[Explicit list of things this session is *not* doing. Each with rationale
or forward reference.]
```

## Quality checks before delivering

Before handing the prompt to the user, verify:

- [ ] Objective fits in two sentences.
- [ ] Deliverables list names exact file paths.
- [ ] Constraints include at least one "do not modify" item.
- [ ] Verification is mechanical (reproducible commands), not subjective.
- [ ] Out-of-scope section exists and has at least one entry.
- [ ] Total length is under 2,000 words (longer signals "this is two sessions").

If any check fails, either revise the prompt or surface the gap to the user.

## Anti-patterns to avoid

- **Vague deliverables** ("implement the user dashboard"). Always concrete files.
- **Verification that requires judgment** ("the dashboard should look good"). Always mechanical.
- **Specs longer than 2,000 words.** Split into multiple sessions.
- **Specs without a precondition section.** Always state what the repo must look like for the session to start.
- **Specs that try to teach the agent.** Reference existing pattern docs; don't restate them.

## Reference patterns

This skill operationalizes:

- `process/session-prompt-template.md` — the canonical template.
- `process/spec-execute-audit-loop.md` — the loop the prompt is one phase of.
- `process/single-commit-per-session.md` — the commit discipline the prompt enforces.
- `process/four-step-verification-gate.md` — what the verification section typically points to.

If the user's project doesn't have these patterns, this skill's output will reference them anyway; the user can adapt or adopt them.

## Example output

For a hypothetical request "spec a session to add password reset to our app," the skill would produce a markdown document with:

- Objective: "Adds a password-reset flow (request → email → token-validated form → password update). Currently users who forget their password have no self-service recovery."
- Precondition: "Session N-1 (email service integration) merged at commit [hash]."
- Deliverables: 5 named files (server actions, page components, email template, migration).
- Constraints: existing auth module not modified; uses the project's email helper; tokens expire in 30min.
- Verification: four-step gate; a new test confirming expired tokens reject; a manual test for the email delivery.
- Out of scope: rate-limiting on the reset endpoint (next session); social-login flows; admin-side password reset.

The user can hand the output directly to their coding agent.
