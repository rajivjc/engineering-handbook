# Session prompt template

**Category:** process
**Applies to:** any session prompt you’ll hand to a coding agent (Claude Code, Cursor, etc.) where the prompt defines the scope of a session.

## Problem

A session prompt that says “implement feature X” and lists 200 words of detail will produce something. Whether what it produces matches your intent depends on:

- Whether the prompt is specific enough to disambiguate.
- Whether the prompt names files concretely vs. gestures at them.
- Whether the prompt distinguishes “must do” from “nice to have.”
- Whether the prompt makes verification reproducible (the agent and the human can confirm done-ness the same way).

A loose prompt produces a session that drifts. A *tight* prompt — one with the right structure — produces sessions that ship correctly. The structure is the load-bearing piece.

## Mechanism

A template with sections that have explicit purposes. Every prompt fills every section, even if briefly.

```markdown
# Session [N]: [short descriptive name]

## Objective

Two sentences. What this session ships. Why now.

## Precondition

What state the repo must be in for this session to start. Often: previous session is merged, a specific commit hash is the parent, certain dependencies installed. If the precondition isn't met, the agent should STOP and ask, not improvise.

## Why this session

The pressure that forced this work. What's deferred. What this enables (e.g., "after this lands, Session N+1 can proceed").

## Deliverables

The concrete output. Numbered list. For each:

- File path (full, exact)
- Brief description of what changes / what it contains
- Acceptance criterion if non-obvious

If multiple files: group by domain (data layer, action layer, UI layer, etc.). The total count of files is stated explicitly somewhere — "creates 12 files, modifies 3."

## Constraints

The non-obvious rules:

- Patterns to follow (cite the pattern docs by path).
- Existing files NOT to modify (the "do not touch" list).
- Style or naming conventions specific to this session.
- Anti-patterns explicitly forbidden in this session.

## Verification

What proves the session is done:

- The four-step gate must pass: `npx tsc --noEmit && npm run build && npm run lint && npx vitest run`.
- Specific tests that must exist by name or pattern.
- Specific behaviors that must be demonstrated.
- Any deliberate-violation passes that must be performed.

## Audit (post-session)

What will be checked after the agent declares done. (This signals to the agent: don't expect a green build to end the session — these checks are coming.)

## Commit

The expected commit shape:

- Single commit on `main` (or the working branch).
- Suggested commit message body.

## Out of scope

Explicit list of things this session is *not* doing. Each entry has a rationale or a forward reference.

- Feature Y → next session
- Refactor Z → deferred until phase 2
- Performance optimization → measure first; not part of this session
```

That’s the template. Length depends on session complexity; typical sessions are 500–1500 words.

## Why each section exists

- **Objective:** the single source of truth for “did this session do what it was supposed to do?” If you can’t write it in two sentences, the session is too big.
- **Precondition:** prevents wasted execution against a wrong starting state. The agent reads it; if mismatched, it asks.
- **Why this session:** explains the pressure. An agent that knows *why* makes better implementation choices than one that knows only *what*.
- **Deliverables:** the contract. The audit checks the diff against this list.
- **Constraints:** the things that aren’t obvious from the deliverables alone. Without explicit constraints, the agent fills in gaps with defaults that might not match your intent.
- **Verification:** the mechanical check. Reproducible; not subjective.
- **Audit:** the human check. Tells the agent what kinds of issues will be flagged later.
- **Commit:** the format. Single commit, message, branch.
- **Out of scope:** the negative space. Prevents drift.

Skipping any section makes the prompt fragile in a different direction. The section that gets skipped most often is **out of scope** — and that’s where drift creeps in most often.

## Specifying file paths and counts

A spec that says “create the necessary files” produces vague execution. A spec that says:

```
Creates 4 files:
- src/lib/scheduling/coverage-validator.ts
- src/lib/scheduling/__tests__/coverage-validator.spec.ts
- src/lib/scheduling/types.ts
- src/components/manager/CoverageStatusBadge.tsx

Modifies 1 file:
- src/app/(manager)/schedule/page.tsx (import the new badge component)
```

…produces predictable execution. The agent has the list; the audit verifies the list matches the diff.

For sessions that genuinely have variable file counts (e.g., “create one Markdown file per pattern; the count depends on how many patterns we cover”), state the count explicitly even if computed: “creates 17 files (one per pattern listed below).”

## Constraints worth always including

Even when not session-specific:

- **Single-commit-per-session.** Otherwise the agent’s instinct may be to make multiple commits.
- **Verbatim drafting** for content-heavy sessions: the agent does not paraphrase or “improve” embedded content.
- **No new dependencies without authorization.** A session shouldn’t add `package.json` entries the spec didn’t list.
- **No edits outside scope.** Even small “while I’m here” cleanups defer to a next session.
- **No deletion of existing tests.** Even if the test “no longer applies” — call it out, don’t silently delete.

These can live in a project-wide AGENTS.md / CLAUDE.md file referenced by the spec, rather than repeated in every spec.

## Anti-patterns

**Vague deliverables.** “Implement the user dashboard.” → no list of files, no acceptance criteria. The agent guesses.

**Verification that requires judgment.** “The dashboard should look good.” → not reproducible; what’s “good”? The verification should be mechanical (tests pass, build passes, specific files exist with specific shapes).

**Out-of-scope as a single line.** “Don’t break anything else.” → too vague. Be specific: “Do not modify the booking flow; do not change auth helpers; do not touch the database schema.”

**Conflating constraints with deliverables.** A constraint (“follow the data-layer pattern”) in the deliverables list looks like a thing-to-build. Keep them separate.

**Specs without a precondition section.** Sessions that depend on previous sessions’ outputs need to assert the previous session is in place. Otherwise the agent might run against an empty repo and produce nothing meaningful.

**Specs that try to teach.** “Here’s how RLS works in Supabase: …” — if the agent needs to be taught the concept, the agent isn’t ready. Reference existing pattern docs and architecture docs; don’t restate them in every spec.

**Specs longer than 2,000 words.** Strong indicator the session is two sessions. Split.

## Negative consequences

- **Spec writing time.** A good spec takes 20–60 minutes to write. For a 4-hour session, that’s overhead worth it; for a 20-minute session, it’s overkill (use a lighter form).
- **Specs can be over-prescriptive.** A spec that names every internal helper function leaves no judgment for the agent. The right level of prescription: name files and public surface; let the agent decide internals.
- **Specs go stale.** A spec written and then iterated for two days might no longer match the codebase state. Re-read just before handing off; update if needed; re-freeze.
- **The template is rigid.** Some sessions don’t need every section. (A purely-documentation session might have no “Verification” step beyond “files exist.”) Adapt; don’t include sections that have nothing to say.

## Verification

The spec’s quality is verified by the session’s outcome:

- Did the diff match the deliverables list? (If not, either the spec was unclear or the agent drifted.)
- Did the audit find issues that the constraints should have prevented? (If yes, add constraints.)
- Did the session need a fix-up? (If yes, what did the spec miss?)

Use these signals to refine the template over time. Specs are documents that age well only when iterated based on outcomes.

## Related

- `process/spec-execute-audit-loop.md` — the loop the prompt is one phase of.
- `process/audit-pass-checklist.md` — the structural counterpart for audit outputs.
- `process/four-step-verification-gate.md` — what the “Verification” section usually points to.
- `onboarding/new-project-bootstrap.md` (Session 1) — covers AGENTS.md / CLAUDE.md, where project-wide constraints live.
