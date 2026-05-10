# Spec/execute/audit loop

**Category:** process
**Applies to:** any project where work is done in discrete sessions, especially when an AI coding agent is the executor and a human directs.

## Problem

The default mode of working with a coding agent is conversational: “Build me feature X.” The agent attempts; the human reads what came out; the human asks for changes; iterate. This works for small tasks. For substantial work — a multi-file feature, a migration, a refactor with security implications — conversational mode produces:

- **Scope drift.** “Add feature X” becomes “feature X plus a few cleanups I noticed plus a bit of refactoring.” Each addition individually feels right; the cumulative effect is a session that’s hard to review.
- **Missing verification.** The agent finishes, the human glances, they merge. The agent didn’t run tests; the human didn’t run tests. Bugs ship.
- **Lost context between sessions.** Each conversation starts cold. The agent re-discovers the codebase; the human re-explains constraints. Time wasted; context drifts.
- **Diffuse accountability.** When something breaks, the trail is “we discussed it in chat” — not auditable, not searchable, not a basis for learning.

The fix is structure: every session has three phases — spec, execute, audit — each with a defined output. The spec is written before execution starts. The execute phase happens against a frozen spec. The audit happens against the diff, with the spec as the contract.

## Mechanism

### Phase 1: Spec (in chat or notes)

A document with explicit headings:

- **Objective.** What this session ships, in two sentences.
- **Why this session.** What pressure forced the work; what’s deferred.
- **Deliverables.** Specific files, specific changes, specific outcomes. Numbered or bulleted.
- **Constraints.** Patterns to follow, files not to modify, scope boundaries.
- **Verification.** What proves the session is done — usually the four-step gate plus session-specific checks.
- **Out of scope.** What this session is *not* doing, even though it could.

The spec is dense but bounded — most fit in 1,000 words. Long specs (5,000+) are usually doing too much; split into multiple sessions.

### Phase 2: Execute (in the agent)

The agent receives the spec, executes against it, produces commits. The agent is *not* expected to:

- Add scope beyond the spec (“while I’m here, let me also fix…”).
- Skip verification steps the spec mandates.
- Modify files the spec lists as out of scope.
- Make decisions the spec didn’t authorize.

When the agent encounters something the spec didn’t anticipate (a structural issue, a missing dependency, an ambiguous requirement), it asks. The human can either expand the spec or defer to a future session.

The execution outputs a single commit (see `single-commit-per-session`) with a clear message and a passing four-step gate.

### Phase 3: Audit (back in chat or notes)

The human (or another agent in audit mode) inspects the diff *against the spec*. The questions:

- Does the diff match the spec’s deliverables? (Files specified vs. files actually changed.)
- Are there changes outside the spec’s scope? (Even small cleanups; flag them.)
- Did verification pass? (Gate output, test counts, lint warnings.)
- Are there findings — bugs, smells, concerns — that warrant fix-up before declaring the session done?

The audit produces a list of findings, classified as: blocker (must fix before merge), nit (worth fixing eventually), or accepted (known issue, deferred).

If blockers are found, a fix-up spec (or a continuation spec) addresses them. The cycle restarts: tighter spec, focused execution, follow-up audit. Most sessions don’t need fix-ups; the discipline is that *if* they do, the same loop applies.

## Why each phase exists

- **Spec.** Forces scope clarity *before* the work starts. The spec is the contract; the agent’s job is to fulfill it. Drift happens against a written contract less often than against a chat conversation.
- **Execute.** The agent operates on a frozen target. No “while you’re at it” requests during execution; those are the next session’s spec. This keeps the diff comprehensible.
- **Audit.** The diff is reviewed in the small, against the spec. Issues are identified and either fixed (in this session or a fix-up) or accepted (logged for later). Nothing falls through the cracks.

The three phases are deliberately separated. Mixing them — speccing while executing, executing while auditing — collapses to conversational mode and the failure modes return.

## What goes in the spec vs. what gets discovered in execution

**Spec ahead of time:**

- File names that will be created.
- Schema changes (table names, column names, constraint names).
- Public-facing API surface (function signatures, response shapes).
- Acceptance criteria (what tests must exist, what behaviors are required).
- Out-of-scope items (what’s deliberately *not* done).

**Discovered in execution (acceptable):**

- Internal helper function names.
- Implementation details within a function.
- Specific code patterns chosen from a set the spec authorized.
- Minor refactors fully contained within a file the spec named.

**Discovered in execution (escalate to spec, do not just decide):**

- New schema changes not mentioned in the spec.
- New dependencies in `package.json`.
- New API endpoints.
- Files outside the spec’s named scope.
- New environment variables.

The pattern: the agent decides *how*; the human (via the spec) decides *what* and *what bounds*.

## A typical loop

1. Human writes spec for Session N. Posts to chat. Reviews, edits, finalizes.
1. Spec handed to the agent (often a different chat or a different tool — Claude Code, etc.).
1. Agent executes. Asks clarifying questions if needed. Produces a single commit. Posts a session summary back.
1. Human (in chat) audits the diff. Identifies any findings.
1. If findings are blockers → write fix-up spec → loop. If clean → close session.
1. Optional: write a handover document (see `patterns/universal/session-handover-discipline.md`) capturing the session’s outcome and what’s next.

The total time is variable. For a small session, all three phases fit in 30 minutes. For a substantial one, an hour each. The structure is what makes the time spent productive.

## Anti-patterns

**Specs that are too long.** A 10,000-word spec is two or three sessions disguised as one. Split. Indicators: more than 3 distinct outcomes; more than ~15 files; multiple unrelated concerns.

**Specs that are too short.** A two-sentence spec is conversational mode in disguise. The agent will guess. The audit will find drift. Force yourself to write the deliverables list.

**Skipping the audit.** “It’s just a small session, I’ll skip the audit.” Often fine; sometimes the bug that ships is in the un-audited session. Calibrate to risk; for security-sensitive work, audit always.

**Auditing without the spec in hand.** “Does this diff look good?” — without the spec, you’re reading the diff cold. The spec is what makes the diff *evaluable*.

**Cycling more than twice on one session.** If a session has had two fix-up rounds and isn’t done, the spec was wrong. Pause, rewrite the spec, restart. Don’t grind through.

**Letting the spec change during execution.** Once handed to the agent, the spec is frozen. Mid-execution edits invalidate the contract. If the spec is wrong, abort the session and rewrite.

## Negative consequences

- **More overhead than conversational.** A 30-minute task might take 60 minutes with the loop. Worth it for substantial work; overkill for trivial.
- **Spec quality is the bottleneck.** Bad specs produce bad sessions, even from a capable agent. Improving spec quality is its own skill (see `session-prompt-template`).
- **Auditor needs context.** The audit is read against the spec, which assumes the auditor read the spec. For team work, this means specs are public artifacts (shared chat, shared doc, in-repo session log).
- **The loop assumes a one-step hand-off between spec and execution.** Streaming agents that conversationally iterate during execution don’t fit cleanly. For those, the spec/audit framing still applies; “execution” just runs longer.

## Verification

The loop verifies itself: a session is done when audit confirms the spec is satisfied. There’s no separate verification step.

What you can verify periodically:

- **Spec quality:** specs from 2 weeks ago — were they specific enough? Could a different agent execute them? If not, your spec template needs work.
- **Audit coverage:** findings from the past month — what classes of issue are recurring? They might be candidates for new patterns or convention guards.
- **Loop discipline:** sessions that skipped the audit. Did any of them ship bugs? Calibrate.

## Related

- `process/session-prompt-template.md` — the structural template for spec documents.
- `process/audit-pass-checklist.md` — the structural template for audit outputs.
- `process/four-step-verification-gate.md` — the mechanical check that’s part of every “execute” phase.
- `process/single-commit-per-session.md` — how the execution phase produces a reviewable commit.
- `patterns/universal/session-handover-discipline.md` — how to capture the *between-sessions* state.
