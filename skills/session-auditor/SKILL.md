---
name: session-auditor
description: Audit a session of work executed by a coding agent. Use this skill when the user has just finished a session (the agent reported done; the PR is open or recently merged) and wants a structured review before declaring the session complete. Performs the standard checks — scope adherence, four-step gate verification, byte-fidelity for embedded content, cross-reference resolution, deliberate-violation status — and produces a verdict: SHIP, FIX-UP, or REWORK. Trigger phrases include "audit this session," "review session N," "did the agent do what we specced," "give me an audit pass on this PR."
---

# Session auditor

This skill performs structured audits of completed coding-agent sessions. The output is a verdict (SHIP / FIX-UP / REWORK) backed by findings classified as BLOCKER, NIT, or ACCEPTED.

## When to use this skill

Use when the user:

- Has just completed a session of agent-driven work and wants a review.
- Hands over a commit hash, PR URL, or branch name with the implicit "tell me if this is done."
- Asks for an audit, review, or check against a spec.

Do **not** use for:

- Generic code review unrelated to a session (use normal code review framing).
- PR review where no spec exists (audit requires a spec to check against).
- Real-time review during execution (this skill is for post-execution audit).

## Required inputs

Before starting the audit, you need:

1. **The commit, PR, or branch** to audit. (A hash, a URL, or "the most recent merge.")
2. **The spec** the session was executed against. If the user doesn't provide it, ask. Auditing without a spec is just code review.
3. **Access to the repo.** Either it's already in the working directory, or it needs to be cloned.

## Workflow

### Step 1: Establish the audit scope

- Clone the repo fresh (don't use a working copy).
- Confirm the commit hash being audited.
- Read the spec end-to-end. Note the deliverables list and the constraints.

### Step 2: Mechanical checks (fast; do these first)

Run these in order. Any failure here is a blocker; surface and resolve before deeper review.

- [ ] Verification gate passes. Run the project's gate (typecheck + build + lint + tests). If any step fails, the session isn't done.
- [ ] Commit shape is correct. `git log --oneline -10`. Single commit on main (or PR set up to squash-merge). Commit message follows the format in the spec.
- [ ] Diff stat matches expected scope. `git diff --stat <parent>..<commit>`. File count and rough insertion count match the spec.
- [ ] No files modified outside scope. `git diff --name-status <parent>..<commit> | awk '$1 != "A"'` for additive-only sessions; or compare modified files against the spec's scope list.
- [ ] No new dependencies the spec didn't authorize. Check `package.json` / `go.mod` / equivalent.
- [ ] No new environment variables or config additions undocumented.

### Step 3: Substantive checks

Read the diff against the spec.

- [ ] Each deliverable in the spec is present in the diff.
- [ ] Each deliverable meets the spec's acceptance criteria (not just "the file exists").
- [ ] Constraints from the spec are respected (named patterns followed; anti-patterns absent).
- [ ] Test coverage exists for new code, calibrated to the spec's expectations.
- [ ] Deliberate-violation passes performed where the spec required them.
- [ ] Cross-references from new files to other docs/patterns resolve.
- [ ] For verbatim-drafting sessions (e.g., documentation): byte-fidelity check on each embedded block.

### Step 4: Findings

For each issue found, classify:

- **BLOCKER** — must fix before declaring the session done. Correctness, security, scope drift, missing verification, broken cross-references, gate failures.
- **NIT** — should fix eventually but not gating. Cosmetic issues, recurring small inconsistencies, comments that could be clearer.
- **ACCEPTED** — known issue, explicitly deferred with rationale. TODOs tracked elsewhere; incomplete patterns consistent with the spec's scope; planned next-session work.

Each finding has:

- A short description (one or two sentences).
- The file and location.
- The classification.

### Step 5: Verdict

Based on findings:

- **SHIP.** No blockers; session is done. List any NITs and accepted items for the record.
- **FIX-UP.** Blockers exist; write a fix-up spec to address them. Don't reject the session; iterate.
- **REWORK.** Blockers are severe enough that the spec was wrong. Rewrite the spec; restart the session.

The verdict goes at the bottom of the audit document, with a one-sentence rationale.

## Output format

```markdown
# Audit: Session [N] — [name]

**Commit:** [hash]
**Spec:** [link or quote]

## Mechanical checks
[Checklist with pass/fail for each item.]

## Substantive checks
[Checklist with pass/fail for each item.]

## Findings

### BLOCKER (n)
1. [Description] — [file:line]

### NIT (n)
1. [Description] — [file:line]

### ACCEPTED (n)
1. [Description] — [file:line] — [rationale]

## Verdict
[SHIP / FIX-UP / REWORK]

[One sentence: why this verdict.]

## What's unblocked
[What the next session can now do.]
```

## Quality checks before delivering

- [ ] Every finding has a classification.
- [ ] Every ACCEPTED finding has a rationale.
- [ ] The verdict matches the blockers count (zero blockers → SHIP).
- [ ] If the verdict is FIX-UP, identify what the fix-up spec needs to cover.
- [ ] If the verdict is REWORK, identify what the spec rewrite should change.

## Anti-patterns to avoid

- **Auditing without the spec.** "Does this diff look good?" without the spec is just code review. The spec is the contract; the audit checks against it.
- **Skipping mechanical checks.** "The CI is green" doesn't catch scope drift or missing references. Walk every box.
- **Findings without classification.** "There's an issue here" doesn't tell anyone what to do.
- **Verdicts without rationale.** "SHIP" with no explanation isn't auditable later.
- **Audits longer than the session.** Calibrate effort to session size; a 30-minute session deserves a 5-minute audit, not a 90-minute one.
- **Treating every cosmetic drift as a blocker.** Cosmetic issues (markdown numbering, curly quotes) are usually NITs and often ACCEPTED. Reserve BLOCKER for real problems.

## Reference patterns

This skill operationalizes:

- `process/audit-pass-checklist.md` — the canonical checklist this skill implements.
- `process/spec-execute-audit-loop.md` — the loop the audit is one phase of.
- `process/four-step-verification-gate.md` — the mechanical check that's first on the audit.
- `patterns/test-correctness/deliberate-violation-verification.md` — the technique for verifying the audit's own effectiveness over time.

## Example output

For a hypothetical request "audit the session that just added the password reset flow," the skill would produce:

- Mechanical checks: gate passed; single commit; 5 files added (matches spec); no out-of-scope changes; no new deps.
- Substantive checks: all 5 files present; tests in place; expired-token test exists; no constraint violations.
- Findings: 0 BLOCKER, 1 NIT (the email template has a typo in "reciever" — should be "receiver"), 0 ACCEPTED.
- Verdict: SHIP. The nit doesn't gate.
- What's unblocked: Session N+1 (rate-limiting on the reset endpoint) can proceed.

The user can hand the output directly into their session-tracking notes.
