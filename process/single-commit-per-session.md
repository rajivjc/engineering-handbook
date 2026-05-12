# Single commit per session

**Category:** process
**Applies to:** any session-based workflow where a unit of work spans multiple files and needs to be reviewable as a coherent change.

## Problem

A session of work touches twelve files. Three commits fall out of execution naturally:

- “Add new schema migration”
- “Implement service layer”
- “Wire up UI”

Each looks fine in isolation. The problem is downstream:

- **Bisecting a bug becomes harder.** If a regression appeared between commits 1 and 3 of a single session, `git bisect` can land on commit 2 — a state the developer never tested in. The migration is in but the service isn’t using it; the build passes but the feature is broken; the bisect is misleading.
- **Reviewing the diff is harder.** Three commits in a PR mean the reviewer mentally reconstructs “what was the cumulative effect” from per-commit diffs. With one commit, the diff *is* the change.
- **Reverting is fragile.** Reverting one of the three commits leaves the other two in a state nobody tested. Reverting all three is a multi-step operation prone to conflicts.
- **The session’s narrative gets lost.** The commit message becomes “implement service layer” — descriptive of *what changed in this commit* but not *why this session happened*. The audit trail loses the larger story.

The fix: each session produces exactly one commit. The commit’s diff is the entire session’s work. The commit message tells the session’s story.

## Mechanism

### Squash on merge (recommended)

Develop on a feature branch. Make as many WIP commits as you want during execution — one per logical step is fine. When the session is done, open a PR and merge with squash. The squashed commit on `main` is the single commit; the WIP history disappears.

The PR description carries the session’s narrative. The squash-commit message carries the same content (or a summary):

```
Patterns 2/3: LLM, domain, process (Session 2B)

Adds 16 pattern files across three subdirectories:

- patterns/llm/ (6): rate-limiting-multi-layer, error-sanitization,
  prompt-injection-detection, input-wrapping, request-size-limit,
  pii-redaction
- patterns/domain/ (4): ledger-with-atomic-refund, polymorphic-authorship,
  single-elimination-bracket-with-lazy-rounds, unimplemented-config-error-pattern
- process/ (6): four-step-verification-gate, spec-execute-audit-loop,
  session-prompt-template, single-commit-per-session, audit-pass-checklist,
  migration-ordering-discipline

Resolves the 4 forward references from Session 2A (process/four-step,
process/spec-execute, llm/rate-limiting, llm/error-sanitization).

Session 2 of 4 (part B).
```

This format works equally well for a solo developer (own PR, own merge) and a team (PR review, squash on approval).

### Direct-to-main with deliberate squash (alternative)

For solo work where PRs feel like overhead, work on `main` directly with WIP commits, then squash before declaring done:

```bash
# WIP commits during execution
git commit -m "WIP: scaffolded files"
git commit -m "WIP: filled in content"
git commit -m "WIP: fixed lint"

# Before declaring done, squash to one commit
git reset --soft HEAD~3
git commit -m "Patterns 2/3: LLM, domain, process (Session 2B) ..."
```

Less common but valid for fast solo iteration. The tradeoff: you lose the per-WIP-commit history. For most sessions this is fine; for sessions where the WIP history might be referenced later (e.g., debugging a strange execution path), prefer the PR approach.

## What goes in the commit message

A good commit message has three parts:

1. **Subject line.** Short, scannable, follows project convention (e.g., conventional commits: `feat(X): ...` or `chore: ...`). Names the session.
2. **Body.** What this session did, in 3–6 lines. List the major deliverables (file groups, not every file). State what’s resolved or unblocked.
3. **Cross-references.** Forward references being resolved, prior sessions being built upon, related issues if any.

What’s NOT in the commit message:

- The full file list. That’s in the diff stat.
- Implementation details. Those are in the code.
- Decisions or rationale. Those go in ADRs.
- “Fixes” without context. Be specific.

A commit message that fits on one screen is the right length. Beyond that, you’re drifting toward duplicating ADR or session-summary content; let those carry the load.

## Why this matters more for AI-driven sessions

When a coding agent executes a session, it tends to make many small commits. This is good during execution (each WIP commit is recoverable, easy to inspect). It’s bad post-merge: the resulting branch has 30 micro-commits.

The squash discipline collapses these to one. The merge commit becomes the unit of audit, the unit of revert, the unit of bisect. The agent’s per-step commits are an execution artifact, not a permanent record.

For the human reviewer, this is a load-bearing simplification. Reviewing 30 micro-commits is exhausting; reviewing one squashed diff is normal PR work.

## Anti-patterns

**Multiple non-WIP commits per session.** “Migration commit” + “service commit” + “UI commit” — each looks like a real commit. The history is now session-step-grained instead of session-grained. Future-you will hate this.

**Squashing to a commit message that doesn’t tell the story.** “Update files” or “Implement feature” loses everything. The squash message is the *only* permanent record of what the session did; treat it accordingly.

**Squash that loses important context from intermediate commits.** Sometimes a WIP commit has a key insight in its message (“this approach didn’t work because X”). Capture those insights in the squash message or an ADR; don’t let them vanish.

**Forcing a multi-session change into one commit.** If a session is genuinely two sessions’ worth of work, the commit will be too big. The fix is to *split the session*, not to weasel out of the discipline.

**Pushing WIP commits to main directly.** WIP commits should not be on `main`. Either work on a feature branch and squash-merge, or rebase to a single commit before pushing.

**Forgetting to squash and merging with a merge commit.** A merge commit + N feature commits = the same history mess as direct micro-commits. Configure the repo’s merge button to default to “Squash and merge” if your hosting supports it.

## Negative consequences

- **WIP history is lost.** If you needed to look back at “what did the agent try at step 5 before settling on the final approach?” — you can’t, because the WIP commits were squashed. Mitigate: capture insights in the squash message; refer to PR comments for ephemeral discussion.
- **Long-running branches accumulate work that doesn’t match “session-sized.”** A branch open for two weeks with 50 commits doesn’t squash cleanly into one logical session. Mitigate: keep sessions short (a day or two); don’t let branches age.
- **Bisect granularity is coarser.** If a bug appears between session N and session N+1, you can’t bisect within session N to find which step caused it. This is acceptable: sessions are small enough that “the bug is somewhere in this session’s diff” is a tractable search.
- **Some merge tooling makes squash awkward.** If your hosting’s PR UI defaults to merge commits and you have to manually squash, friction adds up. Configure defaults; if not possible, document the pre-merge squash step.

## When to break the rule

Almost never, but the rare cases:

- **Truly massive but coherent sessions.** A session that legitimately produces 100+ files (e.g., a large code generation) might be split into “schema commit” and “code commit” for readability. Even then, prefer one commit if reviewable.
- **Sessions that include a revert.** “Apply X, realize it’s wrong, revert” — sometimes the revert deserves its own commit so the history shows the experiment. Usually still squashable; case by case.

The default is one commit. Exceptions are explicit choices, not accidents.

## Verification

After every merge, run:

```bash
git log --oneline -10
```

Confirm the most recent commit on `main` is the session’s squashed commit. If you see multiple commits from the session, the squash didn’t happen — fix before the next session.

Periodically: a session every couple of weeks, audit by reading the squash commit’s message and confirming it accurately summarizes what the session did. If commit messages have drifted to “update files” — the discipline has eroded.

## Related

- `process/spec-execute-audit-loop.md` — the loop this commit pattern fits into.
- `process/session-prompt-template.md` — the template includes a “Commit” section that names the expected squash format.
- `process/four-step-verification-gate.md` — the gate runs against the squashed commit’s state, not the WIP commits.
- `patterns/universal/session-handover-discipline.md` — the handover document is *separate* from the commit message; commits are concise, handovers are more detailed.
