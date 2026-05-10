# Session handover discipline

**Category:** universal
**Applies to:** any project where work is done in discrete sessions (with an AI agent or otherwise) and where context from one session needs to flow to the next.

## Problem

You work on a project across multiple sessions. Each session ships some code, makes some decisions, and leaves a context trail in your head. When you come back the next day (or the next week), some of that context is fresh; some of it is gone. When a teammate joins the project, none of it is theirs.

Without a deliberate handover, the next session starts by re-reading code, re-discovering the context, and sometimes re-making decisions that were already settled. Each re-discovery costs time. Each re-made decision risks contradicting the previous one.

The fix is to write the context down at the end of each session. Not exhaustively — that becomes a chore nobody does. The goal is the minimum that lets a future session pick up without rebuilding mental state.

## Mechanism

At the end of each session, write a short handover document. The shape:

```markdown
# Session N handover — YYYY-MM-DD

## What shipped

- Brief summary of what was completed in this session.
- Commits: list of commit hashes and titles.
- Tests added: count or list of new test files.

## What was decided

- Any non-trivial decision made during the session.
- Format: "Decided X. Rationale: Y. Alternative considered: Z. Recorded as ADR-NNN if applicable."

## What's still open

- Things noticed during the session that aren't fixed.
- Format: "Issue. Why it's deferred. Suggested fix or session for it."

## What the next session should pick up

- The single most important thing to do next.
- Or: "Nothing pressing — wait for new pressure."

## Context the next session needs

- One or two paragraphs of state that isn't obvious from the code.
- Why the current shape is what it is.
- Anything tried and abandoned.
```

This takes 10-15 minutes to write. It saves 30-60 minutes the next time you (or someone else) opens the project.

## What this enables

- **Picking up cold.** A future session opens the latest handover, reads it in two minutes, and is ready to work. No “let me dig through the commit history” phase.
- **Onboarding.** A new contributor reads the most recent handover plus the engineering docs (`CLAUDE.md`, `docs/ARCHITECTURE.md`, etc.) and is ready to ship. No “schedule a knowledge-transfer call” required.
- **Sanity check.** Writing the handover forces you to articulate what you did. If you can’t, the session probably wasn’t focused enough; the handover surfaces the lack of focus.
- **Trail of decisions.** Decisions buried in commit messages or chat history aren’t searchable. Decisions in handovers are.

## What handovers are NOT

- **Not project documentation.** They’re snapshots in time. A handover from three months ago doesn’t describe the current state of the project; it describes the state at session N. The current state is in the code and the four canonical docs (architecture, decisions, patterns, process).
- **Not a substitute for ADRs.** A handover might mention a decision; the ADR is where the decision is *recorded canonically*. If a decision is worth keeping, write the ADR.
- **Not exhaustive.** Don’t try to capture everything. Capture what the next session needs.

## When to update vs. archive

After you write the next session’s handover, the previous one becomes a period document. It still exists, it’s still committed, but you don’t update it. You don’t fix typos in it. You don’t reflect changed decisions in it.

Periodically (every few months, or at phase boundaries), archive older handovers to a subdirectory like `docs/_handovers/`. This keeps the repo’s top-level clean while preserving the trail. The handover from the most recent session lives at the root or in chat context (if it’s recent enough); older handovers live in the archive.

## Where handovers live

Two reasonable choices:

1. **In the chat or notes app where you work.** Lower friction. Easier to write. Doesn’t survive losing access to the chat / app. Suitable for solo work where you’re confident the chat history is preserved.
1. **In the repo, at `docs/_handovers/NN-summary.md`.** Higher friction. Survives the chat going away. Required for team projects.

Pick one and stick with it. Mixing creates the worst of both worlds: handovers some places and not others, future readers don’t know where to look.

## Anti-patterns

**Handovers that read like commit messages.** “Added X, fixed Y” doesn’t capture context. Why was X added? What pressure forced Y to be fixed now? What was tried and rejected?

**Handovers that read like resumes.** “Successfully delivered N features.” Marketing language. Useless for the next session. Be plain about what you did and what’s still rough.

**Handovers nobody reads.** If the discipline is to write handovers but never read them, the discipline is wasted. The next session must start by reading the previous handover. Make this part of the spec-prompt template.

**Excessively long handovers.** A handover that takes 30 minutes to write and 10 minutes to read is too long. Aim for 15 minutes to write, 2-3 minutes to read.

**Handovers that lie.** “What was decided: X.” But X was actually compromise of two competing wants. Be honest. The next session needs to know it was a compromise, because the trade-offs may matter again.

**Handovers that hide problems.** “All tests pass.” But three of them are flaky. Say so. Future-you will be grateful.

## What goes in vs. what doesn’t

**In:**

- Decisions made during the session.
- Things tried and abandoned, with the reason for abandonment.
- Surprises (the thing you didn’t expect, that took longer than planned).
- Open issues you noticed but didn’t fix.
- Critical state the next session needs to understand the current shape.
- Time-sensitive context (e.g., “the Stripe webhook is in test mode; switch to live mode before launch”).

**Out:**

- Detailed technical explanations that belong in `docs/`.
- ADR-style decision records (those go in `decisions/`).
- Code snippets longer than five lines (link to the file/commit instead).
- Restating what’s in the commit messages.
- Marketing language about what got done.

## Negative consequences

- **The discipline costs time.** 10-15 minutes per session is a real tax. Worth it for sessions of an hour or more; overhead for short sessions.
- **Handovers can become a crutch.** If the codebase is unreadable without the handover, the codebase is the problem, not the lack of handovers. The four canonical docs (architecture, decisions, patterns, process) are the long-term context; handovers are tactical bridges.
- **Solo handovers can drift to “notes to self” mode.** Keep them in the structure described above. If they degrade to stream-of-consciousness, future-you will skip them.

## Verification

A handover is good if a fresh reader (or future-you) can pick up the project from the handover alone (plus the canonical docs) without any other context. Test this periodically: take a handover from a few weeks ago, read it cold, see if you can reconstruct what was happening. If you can’t, the handover is too thin.

## Related

- `process/spec-execute-audit-loop.md` (Session 2B) — the loop that handovers fit into.
- `decisions/adr-format.md` — for decisions that deserve to be canonized rather than just noted in a handover.
